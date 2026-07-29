"""
Equality tests for parquet column pruning.

A pruned read must return exactly what a full read, subset to the finally-selected
columns, would — pruning only changes which columns are read off disk, never their
values, and never the datetime axis (dropping it would crash `set_datetime_index`).

The invariant everywhere is ``read(pruned) == read(all)[list(pruned.columns)]``, checked
across {materialized cache index, non-materialized raw index} × {literal, wildcard 0/1/2+
matches}, on every wire point: the low-level `read_parquet_pruned`, the quick-load cache
(`_quick_load`), `philips_waves` (uncached parquet), and `other`.

Column pruning is orthogonal to the datetime window — it must fire even with no window set
(the common case) — so most tests deliberately set no window.
"""

import logging
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

import clinical_scope.constants as cst
from clinical_scope.io.file_utils import (
    _pruned_columns,
    get_column_name_from_pattern,
    read_parquet_pruned,
)

OTHER_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "example"
    / "example_patients"
    / "Patient_difficult_format"
    / "other"
)
# Materialized DatetimeIndex ('time'), several signal columns incl. a "Solar8000/" prefix
# family (wildcard 2+) and a lone "BIS/BIS" (literal / wildcard 1).
MATERIALIZED_PARQUET = OTHER_DIR / "waves_first_half_filtered.parquet"


def _make_nonmaterialized_parquet(tmp_path: Path) -> Path:
    """Synthetic RangeIndex parquet: a named datetime column + prefixed value columns."""
    path = tmp_path / "raw.parquet"
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=60, freq="1min"),
            "pre_a": range(60),
            "pre_b": range(60, 120),
            "other": range(120, 180),
        }
    )
    df.to_parquet(path)  # default RangeIndex → not a materialized index
    return path


# ---------------------------------------------------------------------------
# _pruned_columns: the pure schema-name resolver (superset rule)
# ---------------------------------------------------------------------------


class TestPrunedColumnsResolver:
    """Unit tests for the superset rule — no data read, schema names only."""

    SCHEMA = ["Solar8000/HR", "Solar8000/SPO2", "BIS/BIS", "time"]

    def test_absent_field_display_returns_none(self):
        assert _pruned_columns(None, self.SCHEMA) is None

    def test_literal_present_included(self):
        assert _pruned_columns(["BIS/BIS"], self.SCHEMA) == ["BIS/BIS"]

    def test_literal_absent_excluded(self):
        # An absent literal must NOT appear — passing it to columns= would raise.
        assert _pruned_columns(["Nonexistent"], self.SCHEMA) == []

    def test_wildcard_two_plus_matches_returns_all(self):
        assert _pruned_columns(["Solar8000/*"], self.SCHEMA) == ["Solar8000/HR", "Solar8000/SPO2"]

    def test_wildcard_single_match(self):
        assert _pruned_columns(["BIS/*"], self.SCHEMA) == ["BIS/BIS"]

    def test_wildcard_zero_matches_returns_empty(self):
        assert _pruned_columns(["ZZZ*"], self.SCHEMA) == []

    def test_dedup_preserves_first_seen_order(self):
        # Overlapping wildcard + literal must not duplicate a column.
        assert _pruned_columns(["Solar8000/*", "Solar8000/HR"], self.SCHEMA) == [
            "Solar8000/HR",
            "Solar8000/SPO2",
        ]

    def test_mixed_literal_and_wildcard(self):
        assert _pruned_columns(["BIS/BIS", "Solar8000/*"], self.SCHEMA) == [
            "BIS/BIS",
            "Solar8000/HR",
            "Solar8000/SPO2",
        ]


# ---------------------------------------------------------------------------
# Low-level: read_parquet_pruned, materialized DatetimeIndex
# ---------------------------------------------------------------------------


def _expected_cols(full: pd.DataFrame, field_display: list[str]) -> list[str]:
    """Independent oracle for the selected columns (does not use _pruned_columns)."""
    out: list[str] = []
    for pattern in field_display:
        if pattern.endswith("*"):
            out += [c for c in full.columns if c.startswith(pattern[:-1]) and c not in out]
        elif pattern in full.columns and pattern not in out:
            out.append(pattern)
    return out


class TestReadParquetPrunedMaterializedIndex:
    """The materialized-index path: pandas auto-restores the index under columns=."""

    @pytest.mark.parametrize(
        "field_display",
        [
            ["BIS/BIS"],  # literal, 1 match
            ["Solar8000/HR"],  # literal, 1 match (single of a family)
            ["Solar8000/*"],  # wildcard, 2+ matches
            ["ZZZ*"],  # wildcard, 0 matches
            ["BIS/BIS", "Solar8000/*"],  # mixed
        ],
    )
    def test_pruned_read_equals_full_subset(self, field_display):
        full = pd.read_parquet(MATERIALIZED_PARQUET)
        actual = read_parquet_pruned(
            MATERIALIZED_PARQUET,
            columns_fn=lambda names: _pruned_columns(field_display, names),
        )
        assert list(actual.columns) == _expected_cols(full, field_display)
        # check_column_type off: an all-pruned frame's empty columns Index has inferred dtype
        # "empty", differing harmlessly from the sliced oracle's "string".
        pd.testing.assert_frame_equal(actual, full[list(actual.columns)], check_column_type=False)
        pd.testing.assert_index_equal(actual.index, full.index)

    def test_absent_field_display_reads_all(self):
        full = pd.read_parquet(MATERIALIZED_PARQUET)
        actual = read_parquet_pruned(
            MATERIALIZED_PARQUET, columns_fn=lambda names: _pruned_columns(None, names)
        )
        pd.testing.assert_frame_equal(actual, full)

    def test_composes_with_row_pushdown(self):
        full = pd.read_parquet(MATERIALIZED_PARQUET)
        start, end = full.index[10], full.index[20]
        actual = read_parquet_pruned(
            MATERIALIZED_PARQUET,
            bounds_fn=lambda _tz: (start, end),
            columns_fn=lambda names: _pruned_columns(["BIS/BIS"], names),
        )
        expected = full.loc[(full.index >= start) & (full.index <= end), ["BIS/BIS"]]
        pd.testing.assert_frame_equal(actual, expected)


# ---------------------------------------------------------------------------
# Low-level: read_parquet_pruned, non-materialized (detected) datetime column
# ---------------------------------------------------------------------------


class TestReadParquetPrunedNonMaterializedIndex:
    """The detection path: the datetime column is unioned back so the time axis survives."""

    @pytest.mark.parametrize(
        "field_display",
        [
            ["pre_a"],  # literal, 1 match
            ["pre*"],  # wildcard, 2+ matches
            ["zzz*"],  # wildcard, 0 matches (only the datetime col survives)
        ],
    )
    def test_pruned_read_equals_full_subset_with_datetime_col_kept(
        self, tmp_path, field_display
    ):
        path = _make_nonmaterialized_parquet(tmp_path)
        full = pd.read_parquet(path)
        actual = read_parquet_pruned(
            path, columns_fn=lambda names: _pruned_columns(field_display, names)
        )
        # The detected datetime column ('timestamp') is always unioned in, even for 0 matches.
        assert "timestamp" in actual.columns
        assert set(actual.columns) == {"timestamp", *_expected_cols(full, field_display)}
        pd.testing.assert_frame_equal(actual, full[list(actual.columns)])


# ---------------------------------------------------------------------------
# Wire point 1: the quick-load parquet cache (_quick_load)
# ---------------------------------------------------------------------------


def _make_cache(tmp_path: Path) -> Path:
    """A materialized tz-aware DatetimeIndex cache (mirrors a real per-signal cache)."""
    idx = pd.date_range("2020-01-01", periods=100, freq="1s", tz="UTC")
    idx.name = "datetime_index"
    df = pd.DataFrame(
        {"HR": range(100), "SpO2": range(100, 200), "RR": range(200, 300)}, index=idx
    )
    path = tmp_path / "cache.parquet"
    df.to_parquet(path)
    return path


class TestQuickLoadCachePruning:
    """Column pruning fires on the cache independent of any datetime window."""

    def test_prunes_columns_with_no_window(self, servo_u_cls, tmp_path):
        path = _make_cache(tmp_path)
        out = servo_u_cls._quick_load(
            path, patient_options=None, database_options_specific={"field_display": ["HR", "SpO2"]}
        )
        assert list(out.columns) == ["HR", "SpO2"]
        pd.testing.assert_frame_equal(out, pd.read_parquet(path)[["HR", "SpO2"]])

    def test_absent_field_display_reads_all_columns(self, servo_u_cls, tmp_path):
        # This is exactly the inspect() contract: it strips field_display upstream, so the
        # cache must be read in full (every column reported, including unconfigured ones).
        path = _make_cache(tmp_path)
        out = servo_u_cls._quick_load(path, patient_options=None, database_options_specific={})
        assert list(out.columns) == ["HR", "SpO2", "RR"]

    def test_composes_row_and_column_pruning(self, servo_u_cls, tmp_path):
        path = _make_cache(tmp_path)
        full = pd.read_parquet(path)
        patient_options = {
            "data_folder": str(tmp_path),
            "display_timezone": "UTC",
            "datetime_start": "2020-01-01 00:00:10",
            "datetime_end": "2020-01-01 00:00:20",
        }
        out = servo_u_cls._quick_load(
            path,
            patient_options=patient_options,
            database_options_specific={"field_display": ["HR"]},
        )
        # Column pruned to HR; rows are a (loose) subset — values must still agree with the
        # full frame on the rows that were read (the authoritative cut runs downstream).
        assert list(out.columns) == ["HR"]
        assert 0 < len(out) < len(full)
        pd.testing.assert_series_equal(out["HR"], full.loc[out.index, "HR"])


# ---------------------------------------------------------------------------
# Wire point 2: philips_waves (uncached, wide, parquet branch)
# ---------------------------------------------------------------------------


class TestPhilipsWavesColumnPruning:
    """philips_waves reads its source parquet fresh every run — pruning applies each time."""

    def test_extract_pruned_matches_full_subset(self, philips_waves_cls, patient_full_path):
        folder = philips_waves_cls._find_folder(patient_full_path)
        file_path = philips_waves_cls._find(folder)
        if file_path is None or file_path.suffix.lower() != ".parquet":
            pytest.skip("philips_waves parquet fixture not found in demo_patient")

        base_options = {
            "data_folder": str(patient_full_path),
            "display_timezone": "UTC",
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        full = philips_waves_cls.extract(base_options, {})
        # 'art' literal + 'p*' wildcard (paw / pleth / p4) — a real 1 + 2+ mix.
        field_display = ["art", "p*"]
        pruned = philips_waves_cls.extract(base_options, {"field_display": field_display})

        assert list(pruned.columns) == _expected_cols(full, field_display)
        pd.testing.assert_frame_equal(pruned, full[list(pruned.columns)])

    def test_inspect_reports_unconfigured_columns(self, philips_waves_cls, patient_full_path):
        """inspect() strips field_display → full read → unconfigured columns still reported."""
        folder = philips_waves_cls._find_folder(patient_full_path)
        file_path = philips_waves_cls._find(folder)
        if file_path is None or file_path.suffix.lower() != ".parquet":
            pytest.skip("philips_waves parquet fixture not found in demo_patient")

        insp = philips_waves_cls.inspect(
            {
                "data_folder": str(patient_full_path),
                "display_timezone": "UTC",
                "datetime_start": None,
                "datetime_end": None,
                "quick_load": False,
            },
            {"field_display": ["art"]},  # only 'art' configured
        )
        assert insp.status == "ok"
        reported = {c.raw_name for c in insp.columns}
        assert "art" in reported
        assert "vol" in reported  # unconfigured, but inspect must still surface it


# ---------------------------------------------------------------------------
# Wire point 3: other (uncached, per-file config, bare-name field_display)
# ---------------------------------------------------------------------------


class TestOtherColumnPruning:
    """other prunes per-file; a bare-name field_display selects exactly those signals."""

    STEM = "waves_first_half_filtered"
    SELECTED = ["Solar8000/HR", "BIS/BIS"]

    def _by_name(self, signals):
        return {s.raw_name: s for s in signals if s.raw_name.startswith(f"{self.STEM}::")}

    def test_main_pruned_matches_full(self, other_cls, patient_difficult_path):
        base_options = {
            "data_folder": str(patient_difficult_path),
            "display_timezone": "UTC",
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        full = self._by_name(other_cls.main(base_options, {}))

        database_options = {cst.DatabaseOptions.FILES: {self.STEM: {"field_display": self.SELECTED}}}
        pruned = self._by_name(other_cls.main(base_options, dict(database_options)))

        assert set(pruned) == {f"{self.STEM}::{c}" for c in self.SELECTED}
        for name, sig in pruned.items():
            assert list(sig.data.x) == list(full[name].data.x)
            assert list(sig.data.y) == list(full[name].data.y)


# ---------------------------------------------------------------------------
# Warning preservation: pruning is a superset, so match counts are unchanged
# ---------------------------------------------------------------------------


class TestWarningPreservation:
    """
    The superset rule guarantees `get_column_name_from_pattern` sees identical 0/1/2+ match
    counts on the pruned columns as on the full schema — so every warning and skip is
    unchanged. Verified directly by composing the resolver with the matcher.
    """

    SCHEMA = ["pre_a", "pre_b", "x", "time"]

    def test_two_plus_wildcard_still_warns_and_skips(self, caplog):
        pruned = _pruned_columns(["pre*"], self.SCHEMA)  # superset: both pre_a, pre_b
        with caplog.at_level(logging.WARNING):
            result = get_column_name_from_pattern(pruned, "pre*")
        assert result is None  # 2+ matches → ignored, same as full schema
        assert get_column_name_from_pattern(self.SCHEMA, "pre*") is None
        assert any("More than one" in m for m in caplog.messages)

    def test_zero_match_wildcard_still_warns_and_skips(self, caplog):
        pruned = _pruned_columns(["zzz*"], self.SCHEMA)  # []
        with caplog.at_level(logging.WARNING):
            result = get_column_name_from_pattern(pruned, "zzz*")
        assert result is None  # 0 matches → skipped, same as full schema
        assert get_column_name_from_pattern(self.SCHEMA, "zzz*") is None
        assert any("No column found" in m for m in caplog.messages)
