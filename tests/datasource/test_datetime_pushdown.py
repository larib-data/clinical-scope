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
from clinical_scope.io.parquet_pruning import read_cache_pruned, read_parquet_pruned
from clinical_scope.io.time_axis import (
    detect_time_axis_in_frame,
    detect_time_axis_in_parquet,
    set_datetime_index,
)

OTHER_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "patients"
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
        actual = read_parquet_pruned(TZ_AWARE_STORED_INDEX_PARQUET, compute_bounds=lambda _tz: None)
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
# Pruning decisions, observed through the two readers
# ---------------------------------------------------------------------------


class TestPruningDecisionsThroughTheReader:
    """
    What each pruning decision does to the frame a caller receives.

    Every expectation is an independent full read plus a plain pandas slice -- never the
    library's own resolution replayed -- so a wrong decision shows up as wrong data rather
    than as agreement with itself.
    """

    @staticmethod
    def _detection_parquet(tmp_path: Path) -> Path:
        """RangeIndex file: the time axis is a column, so detection has to find it."""
        path = tmp_path / "detected.parquet"
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2020-01-01", periods=50, freq="1min"),
                "pre_a": range(50),
                "other": range(50),
            }
        ).to_parquet(path, index=False)
        return path

    @staticmethod
    def _float_index_parquet(tmp_path: Path) -> Path:
        """EIT-shaped: a stored index that is the time axis but is not range-comparable."""
        path = tmp_path / "float_index.parquet"
        index = pd.Index([minute / 1440 for minute in range(60)], name="Time")
        pd.DataFrame({"Global": range(60), "Local 1": range(60, 120)}, index=index).to_parquet(path)
        return path

    def test_time_axis_survives_a_selection_that_omits_it(self, tmp_path):
        """Dropping the axis would strand the frame with no index to set downstream."""
        path = self._detection_parquet(tmp_path)
        actual = read_parquet_pruned(path, select_columns=lambda _names: ["pre_a"])
        assert "timestamp" in actual.columns
        pd.testing.assert_frame_equal(actual, pd.read_parquet(path)[list(actual.columns)])

    def test_unresolvable_axis_reads_every_column(self, tmp_path):
        """With no detectable axis there is nothing to protect, so pruning is declined."""
        path = tmp_path / "no_axis.parquet"
        pd.DataFrame({"pre_a": range(10), "other": range(10)}).to_parquet(path, index=False)
        actual = read_parquet_pruned(path, select_columns=lambda _names: ["pre_a"])
        pd.testing.assert_frame_equal(actual, pd.read_parquet(path))

    def test_column_pruning_does_not_need_a_window(self, tmp_path):
        """The two prunings are orthogonal -- the common case is a wide file and no window."""
        path = self._detection_parquet(tmp_path)
        full = pd.read_parquet(path)
        actual = read_parquet_pruned(
            path, compute_bounds=lambda _tz: None, select_columns=lambda _names: ["pre_a"]
        )
        assert "other" not in actual.columns
        assert len(actual) == len(full)

    def test_epoch_column_window_matches_a_plain_slice(self, tmp_path):
        """A numeric epoch axis needs integer bounds on disk; wrong types read wrong rows."""
        path = tmp_path / "epoch.parquet"
        stamps = pd.date_range("2020-01-01", periods=50, freq="1min")
        pd.DataFrame(
            {"epoch": stamps.as_unit("ns").astype("int64"), "value": range(50)}
        ).to_parquet(path, index=False)
        start, end = stamps[10], stamps[20]

        actual = read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))

        full = pd.read_parquet(path)
        as_time = pd.to_datetime(full["epoch"], unit="ns")
        expected = full[(as_time >= start) & (as_time <= end)]
        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True), expected.reset_index(drop=True)
        )
        assert 0 < len(actual) < len(full)

    def test_stored_non_temporal_index_is_read_not_rejected(self, tmp_path):
        """
        Regression: detection samples a materialized index column by name. Restoring pandas
        metadata would turn it back into the frame's index mid-detection and raise KeyError,
        so a plain parquet with a float index used to crash instead of declining to prune.
        """
        path = self._float_index_parquet(tmp_path)
        actual = read_parquet_pruned(path, select_columns=lambda _names: ["Global"])
        pd.testing.assert_frame_equal(actual, pd.read_parquet(path))


# ---------------------------------------------------------------------------
# _pushdown_bounds: conservative-loose bounds computation (base.py)
# ---------------------------------------------------------------------------


class TestPushdownBounds:
    """Unit tests for DataSourceBase._pushdown_bounds (buffer, time_shift, tz handling)."""

    def test_no_window_returns_none(self, other_cls):
        assert other_cls._pushdown_bounds({}, {}, index_tz=None) is None

    def test_naive_target_converts_from_naive_bound_tz_and_pads(self, other_cls, monkeypatch):
        # 'other' source tz is UTC; pin the naive-bound default to UTC too, isolating the
        # ± buffer as the only transformation left to verify.
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=1.0)
        assert start == pd.Timestamp("2004-09-15 08:20:00") - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00") + buffer

    def test_time_shift_is_inverted(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
            "other": {"time_shift": 30.0},
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=1.0)
        assert start == pd.Timestamp("2004-09-15 08:20:00") - pd.Timedelta(seconds=30.0) - buffer
        assert end == pd.Timestamp("2004-09-15 08:25:00") - pd.Timedelta(seconds=30.0) + buffer

    def test_negative_time_shift_is_inverted(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
            "other": {"time_shift": -30.0},
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz=None)
        buffer = pd.Timedelta(seconds=1.0)
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
        per-source timezone override that differs from both the naive-bound default and
        the datasource default — must actually shift the bounds, not just take the fallback
        branch as a no-op (both prior unit tests above used UTC==UTC, hiding this).
        """
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
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
        buffer = pd.Timedelta(seconds=1.0)
        # UTC input converted to Europe/Paris wall-clock (+2h, CEST in September), tz stripped
        # to match the physically tz-naive on-disk column.
        assert start == pd.Timestamp("2004-09-15 10:20:00") - buffer
        assert end == pd.Timestamp("2004-09-15 10:25:00") + buffer
        assert start.tzinfo is None
        assert end.tzinfo is None

    def test_aware_target_uses_index_tz_directly(self, other_cls, monkeypatch):
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
        patient_options = {
            "datetime_start": "2004-09-15 08:20:00",
            "datetime_end": "2004-09-15 08:25:00",
        }
        start, end = other_cls._pushdown_bounds(patient_options, {}, index_tz="UTC")
        buffer = pd.Timedelta(seconds=1.0)
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
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
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
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
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
    A tz-aware bound must select exactly what the equivalent naive + cst.NAIVE_BOUND_TZ
    pair would -- and, being already qualified, must not depend on that constant at all.
    """

    @pytest.mark.parametrize(
        "datetime_start,datetime_end,naive_bound_tz",
        [
            ("2004-09-15 08:12:40", "2004-09-15 08:12:50", "UTC"),
            ("2004-09-15 10:12:40", "2004-09-15 10:12:50", "Europe/Paris"),
        ],
    )
    def test_aware_bound_matches_naive_plus_naive_bound_tz(
        self,
        servo_u_cls,
        patient_full_path,
        monkeypatch,
        datetime_start,
        datetime_end,
        naive_bound_tz,
    ):
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", naive_bound_tz)
        naive_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": datetime_start,
            "datetime_end": datetime_end,
            "quick_load": True,
        }
        df_naive = servo_u_cls.extract(naive_options, {})

        # Deliberately a different default: an aware bound must not need this to agree.
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "America/New_York")
        aware_options = {
            "data_folder": str(patient_full_path),
            "datetime_start": to_aware_display_ts(datetime_start, naive_bound_tz),
            "datetime_end": to_aware_display_ts(datetime_end, naive_bound_tz),
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
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
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
        monkeypatch.setattr(cst, "NAIVE_BOUND_TZ", "UTC")
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
            s.raw_name: s for s in signals_disabled if s.raw_name.startswith("device_export::")
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

        detected = detect_time_axis_in_parquet(path)
        assert detected is not None
        col, kind = detected.column_name, detected.kind
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

        assert detect_time_axis_in_parquet(path) is None

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
        assert detect_time_axis_in_frame(pd.read_parquet(path))[0] == "datetime"
        # ...while sampled pushdown can't confirm it and must abstain — never pick 'timestamp'
        # and prune on it (the desync). Abstaining falls back to a full read.
        assert detect_time_axis_in_parquet(path) is None

        # Window over the middle (valid) region, expressed on the authoritative 'datetime' axis.
        start = pd.Timestamp("2020-01-01 10:00:00")
        end = pd.Timestamp("2020-01-01 13:00:00")

        enabled = set_datetime_index(
            read_parquet_pruned(path, compute_bounds=lambda _tz: (start, end))
        )
        disabled = set_datetime_index(pd.read_parquet(path))  # no pushdown → full read

        # The authoritative datetime-window cut (_filter_by_datetime) runs on both downstream.
        enabled = enabled[(enabled.index >= start) & (enabled.index <= end)]
        disabled = disabled[(disabled.index >= start) & (disabled.index <= end)]

        pd.testing.assert_frame_equal(enabled, disabled)


class TestNameAssertedTimezoneBounds:
    """
    The one input that reaches the tz-label strip: a utc-named column stored tz-NAIVE.

    Detection asserts UTC from the name (`_pick_best_candidate`), so the semantic tz and the
    on-disk type disagree. A bound expressed in any zone must still land on the right instant:
    pyarrow compares against the bare stored values, and an unconverted label would shift the
    window by the offset.
    """

    @staticmethod
    def _naive_utc_parquet(tmp_path):
        path = tmp_path / "naive_utc.parquet"
        pd.DataFrame(
            {
                "time_utc": pd.to_datetime([f"2020-07-01 {hour}:00:00" for hour in range(11, 16)]),
                "value": range(5),
            }
        ).to_parquet(path, index=False)
        return path

    def test_detection_asserts_utc_over_a_naive_column(self, tmp_path):
        detected = detect_time_axis_in_parquet(self._naive_utc_parquet(tmp_path))
        assert (detected.tz, detected.tz_from_name) == ("UTC", True)

    @pytest.mark.parametrize(
        "start_text,end_text,bound_tz,expected_hours",
        [
            ("12:00", "15:00", "UTC", [12, 13, 14, 15]),
            # Two different zones naming the same instants must select the same rows.
            ("12:00", "15:00", "Europe/Paris", [11, 12, 13]),  # +02:00 -> 10:00-13:00Z
            ("07:00", "09:00", "America/New_York", [11, 12, 13]),  # -04:00 -> 11:00-13:00Z
        ],
    )
    def test_window_lands_on_the_same_instant_whatever_zone_expressed_it(
        self, tmp_path, start_text, end_text, bound_tz, expected_hours
    ):
        path = self._naive_utc_parquet(tmp_path)
        start = pd.Timestamp(f"2020-07-01 {start_text}", tz=bound_tz)
        end = pd.Timestamp(f"2020-07-01 {end_text}", tz=bound_tz)

        pushed = read_parquet_pruned(path, compute_bounds=lambda tz: (start, end))
        assert sorted(set_datetime_index(pushed).index.hour.tolist()) == expected_hours

    def test_pushdown_never_drops_a_row_the_authoritative_cut_keeps(self, tmp_path):
        """Pushdown may under-prune; it may never lose a row the downstream filter would keep."""
        path = self._naive_utc_parquet(tmp_path)
        start = pd.Timestamp("2020-07-01 12:00", tz="Europe/Paris")
        end = pd.Timestamp("2020-07-01 15:00", tz="Europe/Paris")

        pushed = set_datetime_index(
            read_parquet_pruned(path, compute_bounds=lambda tz: (start, end))
        )
        full = set_datetime_index(pd.read_parquet(path))
        cut = full[(full.index >= start) & (full.index <= end)]

        assert cut.index.isin(pushed.index).all()
        assert len(pushed) < len(full)  # it really did prune


class TestInspectIgnoresPushdownWindow:
    """inspect() always passes apply_datetime_pushdown=False (base.py) — it needs whole-file
    raw stats, so a narrow datetime_start/end window set by patient_options must not shrink
    the reported raw_date_range. By design, not incidental."""

    def test_narrow_window_does_not_shrink_raw_date_range(self, servo_u_cls, patient_full_path):
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


class TestEitPushdownOptOut:
    """EIT filters by time-of-day — a min/max pushdown predicate can't express that."""

    def test_allow_datetime_pushdown_is_false(self, eit_cls):
        assert eit_cls.ALLOW_DATETIME_PUSHDOWN is False


class TestDeclaredIndexNeverPushesDownRows:
    """Vouching that an index *is* the axis says nothing about it being range-comparable."""

    @staticmethod
    def _float_index_parquet(tmp_path: Path) -> Path:
        path = tmp_path / "float_index.parquet"
        index = pd.Index([minute / 1440 for minute in range(60)], name="Time")
        pd.DataFrame({"Global": range(60), "Local 1": range(60, 120)}, index=index).to_parquet(path)
        return path

    def test_bounds_are_never_requested(self, tmp_path):
        """No bounds asked for means no predicate can be built — the safety is structural."""
        path = self._float_index_parquet(tmp_path)
        requested_tz = []

        def compute_bounds(tz):
            requested_tz.append(tz)
            return pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-02")

        actual = read_cache_pruned(path, compute_bounds=compute_bounds)

        assert requested_tz == []
        pd.testing.assert_frame_equal(actual, pd.read_parquet(path))

    def test_row_filter_would_have_emptied_the_frame(self, tmp_path):
        """Every row survives, so the window could not have been quietly applied."""
        path = self._float_index_parquet(tmp_path)
        actual = read_cache_pruned(
            path,
            compute_bounds=lambda _tz: (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-02")),
            select_columns=lambda names: ["Global"],
        )
        assert list(actual.columns) == ["Global"]
        assert len(actual) == len(pd.read_parquet(path))
