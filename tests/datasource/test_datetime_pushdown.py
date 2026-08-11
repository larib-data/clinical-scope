"""
Equality tests for parquet datetime row-pushdown (issue #57).

A windowed read must return exactly what a full read followed by the authoritative
`_filter_by_datetime` would — pushdown only changes how many rows are read from disk,
never which rows survive. Covers all three pushdown paths from the issue: the
quick-load parquet cache (most standard datasources) and `other`/parquet (no cache,
stored-index + footer name-detection, read fresh every run).
"""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import clinical_scope.constants as cst
from clinical_scope.datasource.formatting.timezone import to_aware_display_ts
from clinical_scope.io.file_utils import (
    _detect_datetime_column_from_parquet,
    _find_datetime_col_parsed,
    _is_numeric_pa_type,
    load_parquet_with_datetime_index,
    read_parquet_pruned,
)

OTHER_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "example"
    / "example_patients"
    / "Patient_difficult_format"
    / "other"
)
TZ_AWARE_STORED_INDEX_PARQUET = OTHER_DIR / "waves_first_half_filtered.parquet"
TZ_NAIVE_STORED_INDEX_PARQUET = OTHER_DIR / "waves_naive_index_filtered.parquet"


def _reference_slice(
    path: Path, start: pd.Timestamp | None, end: pd.Timestamp | None
) -> pd.DataFrame:
    """Ground truth: full read, then a plain index slice — no pushdown involved."""
    df = pd.read_parquet(path)
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index <= end]
    return df


# ---------------------------------------------------------------------------
# Low-level: read_parquet_pruned against a materialized index
# ---------------------------------------------------------------------------


class TestReadParquetWithDatetimePushdownLowLevel:
    """Direct tests of the shared pushdown reader, independent of any datasource class."""

    @pytest.mark.parametrize(
        "path,tz",
        [
            (TZ_AWARE_STORED_INDEX_PARQUET, "Europe/Paris"),
            (TZ_NAIVE_STORED_INDEX_PARQUET, None),
        ],
    )
    def test_two_sided_window_matches_reference_slice(self, path, tz):
        start = pd.Timestamp("2004-09-20 00:00:00", tz=tz)
        end = pd.Timestamp("2004-09-25 00:00:00", tz=tz)
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))
        expected = _reference_slice(path, start, end)
        pd.testing.assert_frame_equal(actual, expected)
        assert 0 < len(actual) < len(pd.read_parquet(path))

    @pytest.mark.parametrize(
        "path,tz",
        [
            (TZ_AWARE_STORED_INDEX_PARQUET, "Europe/Paris"),
            (TZ_NAIVE_STORED_INDEX_PARQUET, None),
        ],
    )
    def test_one_sided_start_only(self, path, tz):
        start = pd.Timestamp("2004-10-15 00:00:00", tz=tz)
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, None))
        expected = _reference_slice(path, start, None)
        pd.testing.assert_frame_equal(actual, expected)

    @pytest.mark.parametrize(
        "path,tz",
        [
            (TZ_AWARE_STORED_INDEX_PARQUET, "Europe/Paris"),
            (TZ_NAIVE_STORED_INDEX_PARQUET, None),
        ],
    )
    def test_one_sided_end_only(self, path, tz):
        end = pd.Timestamp("2004-09-16 00:00:00", tz=tz)
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (None, end))
        expected = _reference_slice(path, None, end)
        pd.testing.assert_frame_equal(actual, expected)

    @pytest.mark.parametrize(
        "path,tz",
        [
            (TZ_AWARE_STORED_INDEX_PARQUET, "Europe/Paris"),
            (TZ_NAIVE_STORED_INDEX_PARQUET, None),
        ],
    )
    def test_window_fully_outside_data_range_is_empty_but_matches(self, path, tz):
        start = pd.Timestamp("1990-01-01", tz=tz)
        end = pd.Timestamp("1990-01-02", tz=tz)
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))
        expected = _reference_slice(path, start, end)
        assert len(actual) == 0
        pd.testing.assert_frame_equal(actual, expected)

    @pytest.mark.parametrize(
        "path,tz",
        [
            (TZ_AWARE_STORED_INDEX_PARQUET, "Europe/Paris"),
            (TZ_NAIVE_STORED_INDEX_PARQUET, None),
        ],
    )
    def test_window_between_two_rows_is_empty_but_matches(self, path, tz):
        # Rows are spaced ~36s apart (08:12:33, 08:13:09, ...). Unlike the fully-outside-range
        # case above, this window sits *inside* the file's overall min/max span but between two
        # consecutive samples — the shape of gap a too-tight buffer could get wrong.
        start = pd.Timestamp("2004-09-15 08:12:40", tz=tz)
        end = pd.Timestamp("2004-09-15 08:13:00", tz=tz)
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))
        expected = _reference_slice(path, start, end)
        assert len(actual) == 0
        pd.testing.assert_frame_equal(actual, expected)

    def test_no_bounds_returns_full_unfiltered_read(self):
        actual = read_parquet_pruned(
            TZ_AWARE_STORED_INDEX_PARQUET, compute_bounds=lambda _tz: None
        )
        expected = pd.read_parquet(TZ_AWARE_STORED_INDEX_PARQUET)
        pd.testing.assert_frame_equal(actual, expected)

    def test_compute_bounds_receives_stored_index_tz(self):
        """The resolved tz of the materialized index is passed to compute_bounds, not guessed."""
        seen_tz = []

        def compute_bounds(tz):
            seen_tz.append(tz)
            return None

        read_parquet_pruned(TZ_AWARE_STORED_INDEX_PARQUET, compute_bounds)
        assert seen_tz == ["Europe/Paris"]

        seen_tz.clear()
        read_parquet_pruned(TZ_NAIVE_STORED_INDEX_PARQUET, compute_bounds)
        assert seen_tz == [None]


# ---------------------------------------------------------------------------
# _pushdown_bounds: conservative-loose bounds computation (base.py)
# ---------------------------------------------------------------------------


class TestPushdownBounds:
    """Unit tests for DataSourceBase._pushdown_bounds (buffer, time_shift, tz handling)."""

    def test_no_window_returns_none(self, other_cls):
        assert other_cls._pushdown_bounds({}, {}, index_tz=None) is None

    def test_naive_target_converts_from_display_tz_and_pads(self, other_cls, monkeypatch):
        # 'other' source tz is UTC; pin the display default to UTC too, isolating the
        # ± buffer as the only transformation left to verify.
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)
        assert start == pd.Timestamp("2004-09-15 08:20:00") - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00") + buffer

    def test_time_shift_is_inverted(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
            "other": {"time_shift": 30.0},
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)
        assert start == pd.Timestamp("2004-09-15 08:20:00") - pd.Timedelta(seconds=30.0) - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00") - pd.Timedelta(seconds=30.0) + buffer

    def test_negative_time_shift_is_inverted(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
            "other": {"time_shift": -30.0},
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)
        assert start == pd.Timestamp("2004-09-15 08:20:00") + pd.Timedelta(seconds=30.0) - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00") + pd.Timedelta(seconds=30.0) + buffer

    def test_one_sided_start_only(self, other_cls):
        patient_options = {"datetime_start": "2004-09-15 08:20:00"}
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        assert start is not None
        assert end is None

    def test_naive_target_falls_back_to_database_options_timezone_override(
        self, other_cls, monkeypatch
    ):
        """
        The exact configuration behind issue #57's bug: no materialized index tz, and a
        per-source timezone override that differs from both the library display default and
        the datasource default — must actually shift the bounds, not just take the fallback
        branch as a no-op (both prior unit tests above used UTC==UTC, hiding this).
        """
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
        }
        additional_info = other_cls.OPTIONS_MODULE.DatabaseOptionsAdditionalInformations
        database_options_specific = {
            cst.DatabaseOptions.ADDITIONAL_INFORMATIONS: {additional_info.TIMEZONE: "Europe/Paris"}
        }
        start, end = other_cls._pushdown_bounds(
            patient_options, database_options_specific, index_tz=None
        )
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)
        # UTC input converted to Europe/Paris wall-clock (+2h, CEST in September), tz stripped
        # to match the physically tz-naive on-disk column.
        assert start == pd.Timestamp("2004-09-15 10:20:00") - buffer
        assert end == pd.Timestamp("2004-09-15 10:25:00") + buffer
        assert start.tzinfo is None
        assert end.tzinfo is None

    def test_aware_target_uses_index_tz_directly(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz="UTC")
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)
        assert start == pd.Timestamp("2004-09-15 08:20:00", tz="UTC") - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00", tz="UTC") + buffer


# ---------------------------------------------------------------------------
# Integration: extract() with pushdown enabled vs disabled must agree exactly
# ---------------------------------------------------------------------------


def _toggle_pushdown(cls, enabled: bool):
    """Context-free toggle helper — caller restores the original value."""
    original = cls.ALLOW_DATETIME_PUSHDOWN
    cls.ALLOW_DATETIME_PUSHDOWN = enabled
    return original


class TestQuickLoadCachePushdownEquality:
    """Path 1 (issue #57): the quick-load parquet cache, used by most standard sources."""

    @pytest.mark.parametrize(
        "datetime_start,datetime_end",
        [
            ("2004-09-15 06:12:40", "2004-09-15 06:12:50"),  # two-sided
            ("2004-09-15 06:12:45", None),  # one-sided start
            (None, "2004-09-15 06:12:45"),  # one-sided end
            ("1990-01-01 00:00:00", "1990-01-02 00:00:00"),  # fully outside range
        ],
    )
    def test_naive_cache_pushdown_matches_disabled(
        self, servo_u_cls, patient_full_path, monkeypatch, datetime_start, datetime_end
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": datetime_start,
            "datetime_end": datetime_end,
            "quick_load": True,
        }
        df_pushdown = servo_u_cls.extract(patient_options, {})

        original = _toggle_pushdown(servo_u_cls, False)
        try:
            df_disabled = servo_u_cls.extract(patient_options, {})
        finally:
            servo_u_cls.ALLOW_DATETIME_PUSHDOWN = original

        pd.testing.assert_frame_equal(df_pushdown, df_disabled)

    def test_aware_cache_pushdown_matches_disabled_with_time_shift(
        self, mindray_respi_numerics_cls, patient_full_path, monkeypatch
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": "2004-09-15 08:12:40",
            "datetime_end": "2004-09-15 08:13:00",
            "quick_load": True,
            "mindray_respi_numerics": {"time_shift": 5.0},
        }
        df_pushdown = mindray_respi_numerics_cls.extract(patient_options, {})

        original = _toggle_pushdown(mindray_respi_numerics_cls, False)
        try:
            df_disabled = mindray_respi_numerics_cls.extract(patient_options, {})
        finally:
            mindray_respi_numerics_cls.ALLOW_DATETIME_PUSHDOWN = original

        pd.testing.assert_frame_equal(df_pushdown, df_disabled)
        assert len(df_pushdown) > 0


class TestNaiveAwareBoundEquivalence:
    """
    A tz-aware bound must select exactly what the equivalent naive + display_timezone
    pair would.
    """

    @pytest.mark.parametrize(
        "datetime_start,datetime_end,display_timezone",
        [
            ("2004-09-15 06:12:40", "2004-09-15 06:12:50", "UTC"),
            ("2004-09-15 08:12:40", "2004-09-15 08:12:50", "Europe/Paris"),
        ],
    )
    def test_aware_bound_matches_naive_plus_display_timezone(
        self,
        servo_u_cls,
        patient_full_path,
        monkeypatch,
        datetime_start,
        datetime_end,
        display_timezone,
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", display_timezone)
        naive_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": datetime_start,
            "datetime_end": datetime_end,
            "quick_load": True,
        }
        df_naive = servo_u_cls.extract(naive_options, {})

        # Deliberately a different library default: an aware bound must not need this to agree.
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "America/New_York")
        aware_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": to_aware_display_ts(datetime_start, display_timezone),
            "datetime_end": to_aware_display_ts(datetime_end, display_timezone),
            "quick_load": True,
        }
        df_aware = servo_u_cls.extract(aware_options, {})

        pd.testing.assert_frame_equal(df_naive, df_aware)
        assert len(df_naive) > 0


class TestInspectCosmeticDisplayTimezone:
    """
    inspect()'s reported date ranges are cosmetic only; an omitted display_timezone falls
    back to cst.DISPLAY_TIMEZONE.
    """

    def test_explicit_param_controls_the_reported_timezone(self, servo_u_cls, patient_full_path):
        patient_options = {"data_folder": str(patient_full_path)}
        # raw_date_range is pre-_format and tz-naive for servo_u (a no-op for _to_display_tz);
        # filtered_date_range (post-_format, tz-aware) is the one that reflects display_timezone.
        result = servo_u_cls.inspect(patient_options, {}, display_timezone="Asia/Tokyo")
        assert result.filtered_date_range[0].endswith("JST")

    def test_omitted_param_falls_back_to_library_default(
        self, servo_u_cls, patient_full_path, monkeypatch
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "Asia/Tokyo")
        patient_options = {"data_folder": str(patient_full_path)}
        result = servo_u_cls.inspect(patient_options, {})
        assert result.filtered_date_range[0].endswith("JST")


class TestOtherParquetPushdownEquality:
    """Path 3 (issue #57): other/parquet — stored-index fast path, every run."""

    @pytest.mark.parametrize(
        "datetime_start,datetime_end",
        [
            ("2004-09-20 00:00:00", "2004-09-25 00:00:00"),
            ("2004-10-15 00:00:00", None),
            (None, "2004-09-16 00:00:00"),
            ("1990-01-01 00:00:00", "1990-01-02 00:00:00"),
        ],
    )
    def test_pushdown_matches_disabled(
        self, other_cls, patient_difficult_path, monkeypatch, datetime_start, datetime_end
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": datetime_start,
            "datetime_end": datetime_end,
            "quick_load": False,
        }

        signals_pushdown = other_cls.main(patient_options, {})
        target = [
            s for s in signals_pushdown if s.raw_name.startswith("waves_first_half_filtered::")
        ]

        original = _toggle_pushdown(other_cls, False)
        try:
            signals_disabled = other_cls.main(patient_options, {})
        finally:
            other_cls.ALLOW_DATETIME_PUSHDOWN = original
        target_disabled = {
            s.raw_name: s
            for s in signals_disabled
            if s.raw_name.startswith("waves_first_half_filtered::")
        }

        assert {s.raw_name for s in target} == set(target_disabled)
        for sig in target:
            other_sig = target_disabled[sig.raw_name]
            assert list(sig.data.x) == list(other_sig.data.x)
            assert list(sig.data.y) == list(other_sig.data.y)


class TestOtherDatetimeColumnDetectionTimezoneOverride:
    """
    Regression test for the issue #57 fix (schema-only tz detection vs. semantic tz).

    A parquet column named with "utc" but physically tz-naive on disk gets force-localized
    to UTC by `_pick_best_candidate` (semantic tz), while a per-file `additional_informations`
    timezone override changes what tz the *bounds* should be computed in. Before the fix,
    `_detect_datetime_column_from_parquet` used the raw physical field's tz (always naive
    here) instead of the resolved semantic one, silently returning zero rows for this exact
    shape of file/config.
    """

    def test_naive_utc_named_column_with_timezone_override_matches_disabled(
        self, other_cls, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cst, "DISPLAY_TIMEZONE", "UTC")
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        file_path = other_dir / "device_export.parquet"

        # Naive column but "utc" in the name; no materialized DatetimeIndex (default
        # RangeIndex), forcing the schema-only detection path rather than the fast
        # stored-index path.
        times = pd.date_range("2004-09-15 00:00:00", periods=20, freq="1h")
        df = pd.DataFrame({"time_utc": times, "value": range(20)})
        df.to_parquet(file_path)

        patient_options = {
            "data_folder": str(tmp_path),
            "datetime_start": "2004-09-15 06:00:00",
            "datetime_end": "2004-09-15 10:00:00",
            "quick_load": False,
        }
        file_config = {
            cst.DatabaseOptions.ADDITIONAL_INFORMATIONS: {"timezone": "Europe/Paris"},
        }
        database_options = {cst.DatabaseOptions.FILES: {"device_export": file_config}}

        signals_pushdown = other_cls.main(patient_options, dict(database_options))
        target = [s for s in signals_pushdown if s.raw_name.startswith("device_export::")]

        original = _toggle_pushdown(other_cls, False)
        try:
            signals_disabled = other_cls.main(patient_options, dict(database_options))
        finally:
            other_cls.ALLOW_DATETIME_PUSHDOWN = original
        target_disabled = {
            s.raw_name: s
            for s in signals_disabled
            if s.raw_name.startswith("device_export::")
        }

        # Guards the original bug directly: pushdown used to silently return zero signals here.
        assert len(target) > 0
        assert {s.raw_name for s in target} == set(target_disabled)
        for sig in target:
            other_sig = target_disabled[sig.raw_name]
            assert list(sig.data.x) == list(other_sig.data.x)
            assert list(sig.data.y) == list(other_sig.data.y)


class TestSampledDetection:
    """
    Fix B (issue #57): schema-only detection validates a bounded, spread sample of row
    groups instead of the whole file, and abstains when a sample can't pick unambiguously.
    """

    def test_spread_sample_still_detects_across_many_row_groups(self, tmp_path, monkeypatch):
        """A tiny budget forces the multi-group spread path; detection must still resolve."""
        det = cst.DatetimeColumnDetection
        # Shrink the budget/block so a small file exercises the spread read, not the
        # whole-file short-circuit (real files trip this only above 1M rows).
        monkeypatch.setattr(det, "SAMPLE_MAX_ROW_DECODED", 100)
        monkeypatch.setattr(det, "SAMPLE_ROWS_PER_BLOCK", 50)

        path = tmp_path / "multi.parquet"
        n = 2_000
        df = pd.DataFrame(
            {"timestamp": pd.date_range("2020-01-01", periods=n, freq="1s"), "value": range(n)}
        )
        df.to_parquet(path, row_group_size=100)  # 20 row groups
        assert pq.ParquetFile(path).num_row_groups > 1  # spread path is actually exercised

        detected = _detect_datetime_column_from_parquet(path)
        assert detected is not None
        col, kind, _tz, _naive = detected
        assert (col, kind) == ("timestamp", "timestamp")

    def test_two_datetime_columns_in_one_tier_abstains_and_reads_all(self, tmp_path):
        """
        Two columns matching the same name tier both validate → the sample can't be trusted
        to pick the one the full-frame detector would, so detection abstains (None) and the
        windowed read falls back to a full unfiltered read — never silently dropping rows.
        """
        path = tmp_path / "ambiguous.parquet"
        n = 100
        df = pd.DataFrame(
            {
                "timestamp_a": pd.date_range("2020-01-01", periods=n, freq="1s"),
                "timestamp_b": pd.date_range("2021-06-01", periods=n, freq="1s"),
                "value": range(n),
            }
        )
        df.to_parquet(path)  # default RangeIndex → detection path, not stored-index

        assert _detect_datetime_column_from_parquet(path) is None

        start = pd.Timestamp("2020-01-01 00:00:10")
        end = pd.Timestamp("2020-01-01 00:00:20")
        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))
        pd.testing.assert_frame_equal(actual, pd.read_parquet(path))

    def test_higher_tier_column_hidden_by_sample_does_not_desync(self, tmp_path, monkeypatch):
        """
        The limit case (ADR 0004 tension): a higher-priority datetime column that is valid
        over the *whole* file but garbage in exactly the sampled row groups. Sampled detection
        can't see it, so pushdown filters on the lower-priority ``timestamp``, while the
        authoritative full-frame detector indexes on ``datetime`` — filtering one column and
        indexing another silently drops rows. A windowed (pushdown) read must equal the
        full-read-then-filter result.
        """
        det = cst.DatetimeColumnDetection
        # Force the spread path to sample only the first and last row groups.
        monkeypatch.setattr(det, "SAMPLE_MAX_ROW_DECODED", 100)
        monkeypatch.setattr(det, "SAMPLE_ROWS_PER_BLOCK", 100)

        n_groups, group = 30, 100
        n = n_groups * group
        ts = pd.date_range("2020-01-01", periods=n, freq="1min")  # 'timestamp': lower tier, clean
        datetime_strs = (ts + pd.Timedelta(hours=1)).astype(str).to_numpy(dtype=object)
        # 'datetime': higher tier, valid everywhere except the two sampled groups (0 and last).
        datetime_strs[:group] = "not-a-date"
        datetime_strs[(n_groups - 1) * group :] = "not-a-date"
        df = pd.DataFrame({"datetime": datetime_strs, "timestamp": ts, "value": range(n)})
        path = tmp_path / "pathological.parquet"
        df.to_parquet(path, row_group_size=group)
        assert pq.ParquetFile(path).num_row_groups == n_groups

        # The file genuinely has a valid higher-priority 'datetime' column (garbage only in the
        # sampled groups), so the authoritative full-frame detector indexes on it...
        assert _find_datetime_col_parsed(pd.read_parquet(path))[0] == "datetime"
        # ...while sampled pushdown can't confirm it and must abstain — never pick 'timestamp'
        # and prune on it (the desync). Abstaining falls back to a full read.
        assert _detect_datetime_column_from_parquet(path) is None

        # Window over the middle (valid) region, expressed on the authoritative 'datetime' axis.
        start = pd.Timestamp("2020-01-01 10:00:00")
        end = pd.Timestamp("2020-01-01 13:00:00")

        enabled = load_parquet_with_datetime_index(path, compute_bounds=lambda _tz: (start, end))
        disabled = load_parquet_with_datetime_index(path)  # no pushdown → full read

        # The authoritative datetime-window cut (_filter_by_datetime) runs on both downstream.
        enabled = enabled[(enabled.index >= start) & (enabled.index <= end)]
        disabled = disabled[(disabled.index >= start) & (disabled.index <= end)]

        pd.testing.assert_frame_equal(enabled, disabled)


class TestInspectIgnoresPushdownWindow:
    """inspect() always passes apply_datetime_pushdown=False (base.py) — it needs whole-file
    raw stats, so a narrow datetime_start/end window set by patient_options must not shrink
    the reported raw_date_range. By design, not incidental."""

    def test_narrow_window_does_not_shrink_raw_date_range(
        self, servo_u_cls, patient_full_path
    ):
        base_options = {
            "data_folder": str(patient_full_path),
            "quick_load": False,
        }
        full = servo_u_cls.inspect(base_options, {})
        narrow = servo_u_cls.inspect(
            {
                **base_options,
                "datetime_start": "2004-09-15 08:12:40",
                "datetime_end": "2004-09-15 08:12:50",
            },
            {},
        )
        assert narrow.status == "ok"
        assert narrow.raw_date_range == full.raw_date_range


class TestNumericTypeClassificationAgreement:
    """
    Tripwire for a code-review finding on issue #57: schema-only detection
    (`_is_numeric_pa_type`, pyarrow-type-based) and full-frame detection
    (`_find_datetime_col_parsed`, `pd.api.types.is_numeric_dtype`-based) each decide
    independently whether a column is "numeric" and should be deferred to the epoch tier.
    If they ever disagree on a dtype that also passes datetime-content validation, the
    pushdown fast-path and the full unfiltered read could pick *different* datetime
    columns — silently wrong filter results, not an error.

    This pins today's known-good agreement so a future pandas/pyarrow upgrade that shifts
    either classification is caught here first, rather than downstream as a silent mismatch.
    """

    # Every dtype that can plausibly appear as a real clinical parquet column.
    NUMERIC_TYPES = [pa.int32(), pa.int64(), pa.float32(), pa.float64()]
    NON_NUMERIC_TYPES = [pa.string(), pa.timestamp("ns"), pa.timestamp("ns", tz="UTC")]

    @pytest.mark.parametrize("pa_type", NUMERIC_TYPES)
    def test_numeric_types_agree(self, pa_type):
        assert _is_numeric_pa_type(pa_type) is True
        assert pd.api.types.is_numeric_dtype(pa_type.to_pandas_dtype()) is True

    @pytest.mark.parametrize("pa_type", NON_NUMERIC_TYPES)
    def test_non_numeric_types_agree(self, pa_type):
        assert _is_numeric_pa_type(pa_type) is False
        assert pd.api.types.is_numeric_dtype(pa_type.to_pandas_dtype()) is False

    def test_known_bool_divergence_is_unchanged(self):
        """
        The one known gap (code-review finding, deliberately not fixed): schema-only
        treats bool as non-numeric, pandas treats it as numeric. Harmless today because
        both paths still reject a bool column as a datetime candidate (schema-only fails
        string-parse; full-frame fails the epoch-ns year-range check) — but if this
        assertion ever starts failing, the two paths' agreement has shifted and
        `_is_numeric_pa_type` should be revisited.
        """
        assert _is_numeric_pa_type(pa.bool_()) is False
        assert pd.api.types.is_numeric_dtype(pa.bool_().to_pandas_dtype()) is True


class TestEitPushdownOptOut:
    """EIT filters by time-of-day — a min/max pushdown predicate can't express that."""

    def test_allow_datetime_pushdown_is_false(self, eit_cls):
        assert eit_cls.ALLOW_DATETIME_PUSHDOWN is False
