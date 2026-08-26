"""
Equality tests for parquet column pruning.

A pruned read must return exactly what a full read, subset to the finally-selected
columns, would — pruning only changes which columns are read off disk, never their
values, and never the datetime axis (dropping it would crash `set_datetime_index`).

The invariant everywhere is ``read(pruned) == read(all)[list(pruned.columns)]``, checked
across {timestamp index, caller-declared non-temporal index, non-materialized raw index} ×
{literal, wildcard 0/1/2+ matches}, on every wire point: the low-level `read_parquet_pruned`,
the quick-load cache (`_quick_load`), and `other` (uncached parquet, read fresh every run).

Column pruning is orthogonal to the datetime window — it must fire even with no window set
(the common case) — so most tests deliberately set no window.

`inspect(configured_columns_only=True)` is the one caller that opts *into* pruning while still
refusing row pushdown; its section checks both halves of that, plus the promise that a pruned
table says so.
"""

import logging
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

import clinical_scope.constants as cst
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.io.column_patterns import _pruned_columns, get_column_name_from_pattern
from clinical_scope.io.parquet_pruning import read_cache_pruned, read_parquet_pruned

OTHER_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "patients"
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


def _make_non_temporal_index_parquet(tmp_path: Path) -> Path:
    """
    The EIT cache shape: a named float64 index of fractional days, plus a duration column.

    ``time_hours`` is not decoration: it is in the real cache, and it is what makes datetime
    detection abstain cleanly rather than crash, which is the state this class pins.
    """
    path = tmp_path / "non_temporal_index.parquet"
    index = pd.Index([minute / 1440 for minute in range(60)], name="Time")
    df = pd.DataFrame(
        {
            "time_hours": pd.to_timedelta(index, unit="D"),
            "pre_a": range(60),
            "pre_b": range(60, 120),
            "other": range(120, 180),
        },
        index=index,
    )
    df.to_parquet(path)
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
            select_columns=lambda names: _pruned_columns(field_display, names),
        )
        assert list(actual.columns) == _expected_cols(full, field_display)
        # check_column_type off: an all-pruned frame's empty columns Index has inferred dtype
        # "empty", differing harmlessly from the sliced oracle's "string".
        pd.testing.assert_frame_equal(actual, full[list(actual.columns)], check_column_type=False)
        pd.testing.assert_index_equal(actual.index, full.index)

    def test_absent_field_display_reads_all(self):
        full = pd.read_parquet(MATERIALIZED_PARQUET)
        actual = read_parquet_pruned(
            MATERIALIZED_PARQUET, select_columns=lambda names: _pruned_columns(None, names)
        )
        pd.testing.assert_frame_equal(actual, full)

    def test_composes_with_row_pushdown(self):
        full = pd.read_parquet(MATERIALIZED_PARQUET)
        start, end = full.index[10], full.index[20]
        actual = read_parquet_pruned(
            MATERIALIZED_PARQUET,
            compute_bounds=lambda _tz: (start, end),
            select_columns=lambda names: _pruned_columns(["BIS/BIS"], names),
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
            path, select_columns=lambda names: _pruned_columns(field_display, names)
        )
        # The detected datetime column ('timestamp') is always unioned in, even for 0 matches.
        assert "timestamp" in actual.columns
        assert set(actual.columns) == {"timestamp", *_expected_cols(full, field_display)}
        pd.testing.assert_frame_equal(actual, full[list(actual.columns)])


# ---------------------------------------------------------------------------
# Low-level: read_parquet_pruned, caller-declared (non-temporal) index
# ---------------------------------------------------------------------------


class TestReadParquetPrunedNonTemporalIndex:
    """A float64 index prunes only when the caller vouches that it is the time axis."""

    @pytest.mark.parametrize(
        "field_display",
        [
            ["pre_a"],  # literal, 1 match
            ["pre*"],  # wildcard, 2+ matches
            ["zzz*"],  # wildcard, 0 matches (index only)
        ],
    )
    def test_pruned_read_equals_full_subset(self, tmp_path, field_display):
        path = _make_non_temporal_index_parquet(tmp_path)
        full = pd.read_parquet(path)
        actual = read_cache_pruned(
            path,
            select_columns=lambda names: _pruned_columns(field_display, names),
        )
        assert list(actual.columns) == _expected_cols(full, field_display)
        # pandas restores the index without it ever being named in columns=, so unlike the
        # detection path there is nothing to union back.
        pd.testing.assert_index_equal(actual.index, full.index)
        pd.testing.assert_frame_equal(actual, full[list(actual.columns)], check_column_type=False)

    def test_without_declaration_reads_all_columns(self, tmp_path):
        """The gate: provenance unlocks pruning here, never anything read off the file."""
        path = _make_non_temporal_index_parquet(tmp_path)
        full = pd.read_parquet(path)
        actual = read_parquet_pruned(
            path, select_columns=lambda names: _pruned_columns(["pre_a"], names)
        )
        pd.testing.assert_frame_equal(actual, full)

    def test_declaration_is_inert_without_a_stored_index(self, tmp_path):
        """A RangeIndex file has no index column to vouch for, so detection still runs."""
        path = _make_nonmaterialized_parquet(tmp_path)
        full = pd.read_parquet(path)
        actual = read_cache_pruned(
            path,
            select_columns=lambda names: _pruned_columns(["pre_a"], names),
        )
        assert set(actual.columns) == {"timestamp", "pre_a"}
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

    def test_composes_row_and_column_pruning(self, servo_u_cls, tmp_path, monkeypatch):
        # The materialized cache index is tz-aware UTC (_make_cache); pin the naive-bound
        # default to UTC so the naive window lands inside it.
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        path = _make_cache(tmp_path)
        full = pd.read_parquet(path)
        patient_options = {
            "data_folder": str(tmp_path),
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
# Wire point 2: other (uncached, per-file config, bare-name field_display)
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

    def _inspect(self, other_cls, patient_difficult_path, **kwargs):
        results = other_cls.inspect(
            {
                "data_folder": str(patient_difficult_path),
                "datetime_start": None,
                "datetime_end": None,
                "quick_load": False,
            },
            {cst.DatabaseOptions.FILES: {self.STEM: {"field_display": self.SELECTED}}},
            **kwargs,
        )
        return next(r for r in results if r.datasource_name == f"other::{self.STEM}")

    def test_inspect_default_reports_unconfigured_columns(self, other_cls, patient_difficult_path):
        entry = self._inspect(other_cls, patient_difficult_path)
        reported = {column.raw_name for column in entry.columns}
        assert reported > set(self.SELECTED), "default inspect must surface unconfigured columns"
        assert entry.columns_pruned is False

    def test_inspect_configured_columns_only_prunes_the_source_parquet(
        self, other_cls, patient_difficult_path
    ):
        # 'other' reads its source files directly, so pruning lands without any cache existing.
        entry = self._inspect(other_cls, patient_difficult_path, configured_columns_only=True)
        assert {column.raw_name for column in entry.columns} == set(self.SELECTED)
        assert entry.columns_pruned is True


# ---------------------------------------------------------------------------
# Wire point 3: inspect's opt-in column pruning
# ---------------------------------------------------------------------------


class _FakeOptions:
    """Minimal stand-in for an options module — only what `_format` reaches for."""

    class PatientOptionsDataSourceRelative:
        class TimeShift:
            NAME = "time_shift"


def _wide_frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=100, freq="1s", tz="UTC")
    idx.name = "datetime_index"
    return pd.DataFrame(
        {"HR": range(100), "SpO2": range(100, 200), "RR": range(200, 300)}, index=idx
    )


def _make_source() -> type:
    """A datasource whose fresh `_load` returns the same wide frame the cache holds."""

    class _FakeCachedSource(DataSourceBase):
        DATASOURCE_NAME = "fake_cached"
        FILE_NAME_DATAFRAME_LOADED = "fake_cached.parquet"
        OPTIONS_MODULE = _FakeOptions

        @classmethod
        def _find_folder(cls, folder_path: Path) -> Path:
            return folder_path

        @classmethod
        def _find(cls, folder_path: Path) -> Path:
            return folder_path / "raw_data.bin"

        @classmethod
        def _load(cls, file_path):  # noqa: ARG003
            return _wide_frame()

    return _FakeCachedSource


def _patient_options(folder: Path, **overrides) -> dict:
    return {"data_folder": str(folder), "quick_load": True, **overrides}


@pytest.fixture
def cached_patient(tmp_path: Path) -> Path:
    """A patient folder already carrying a wide parquet cache (i.e. re-inspection)."""
    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
    output_folder.mkdir()
    _wide_frame().to_parquet(output_folder / "fake_cached.parquet")
    return tmp_path


class TestInspectConfiguredColumnsOnly:
    """
    The opt-in trades the unconfigured-column rows for the memory — and nothing else.

    Rows stay unpruned in every case (inspect's `% retained` and raw date range are
    comparisons against the *unwindowed* file), and a fresh load reads every column — `_load`
    takes no configuration, so an inspect can never narrow the cache a first load writes.
    """

    DB_OPTIONS = {"field_display": ["HR", "SpO2"]}

    def test_default_reports_every_column(self, cached_patient):
        result = _make_source().inspect(_patient_options(cached_patient), self.DB_OPTIONS)
        assert {column.raw_name for column in result.columns} == {"HR", "SpO2", "RR"}
        assert result.columns_pruned is False

    def test_flag_reads_only_configured_columns(self, cached_patient):
        result = _make_source().inspect(
            _patient_options(cached_patient), self.DB_OPTIONS, configured_columns_only=True
        )
        assert {column.raw_name for column in result.columns} == {"HR", "SpO2"}
        assert result.columns_pruned is True

    def test_flag_without_field_display_reads_everything(self, cached_patient):
        # Nothing configured → nothing to prune by; the marker must stay off rather than
        # claim a pruned view of a full table.
        result = _make_source().inspect(
            _patient_options(cached_patient), {}, configured_columns_only=True
        )
        assert {column.raw_name for column in result.columns} == {"HR", "SpO2", "RR"}
        assert result.columns_pruned is False

    def test_flag_on_a_first_load_reports_every_column(self, tmp_path):
        # No cache yet: the manufacturer's export has no pushdown, so the flag can't bite.
        (tmp_path / cst.FOLDER_NAME_OUTPUT).mkdir()
        result = _make_source().inspect(
            _patient_options(tmp_path), self.DB_OPTIONS, configured_columns_only=True
        )
        assert {column.raw_name for column in result.columns} == {"HR", "SpO2", "RR"}
        assert result.columns_pruned is False

    @pytest.mark.parametrize("configured_columns_only", [False, True])
    def test_rows_are_never_pruned(self, cached_patient, monkeypatch, configured_columns_only):
        # The window must cut only *after* the read, or "% retained" would always be 100%.
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        result = _make_source().inspect(
            _patient_options(
                cached_patient,
                datetime_start="2024-01-01 00:00:10",
                datetime_end="2024-01-01 00:00:19",
            ),
            self.DB_OPTIONS,
            configured_columns_only=configured_columns_only,
        )
        heart_rate = next(column for column in result.columns if column.raw_name == "HR")
        assert heart_rate.raw_point_count == 100  # the whole file, window ignored on read
        assert heart_rate.filtered_point_count == 10


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
        pruned = _pruned_columns(["zzz*"], self.SCHEMA)
        with caplog.at_level(logging.WARNING):
            result = get_column_name_from_pattern(pruned, "zzz*")
        assert result is None  # 0 matches → skipped, same as full schema
        assert get_column_name_from_pattern(self.SCHEMA, "zzz*") is None
        assert any("No column found" in m for m in caplog.messages)
