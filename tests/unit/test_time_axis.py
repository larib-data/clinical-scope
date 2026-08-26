"""
Tests for the shared, validated datetime-column detector behind set_datetime_index (ADR 0004).

Covers the detection pipeline:
  1. Tiered name search (exact match, then substring buckets)
  2. Content validation gates (≥90% parseable in [2000, 2100], ≥90% non-decreasing)
  3. Within-tier tiebreak (uniqueness ratio, then utc-name preference)
  4. Widen-to-all-columns fallback, numeric-epoch (ns) last resort
  5. Fail-loudly when nothing passes
"""

import pandas as pd
import pyarrow as pa
import pytest

from clinical_scope.io.time_axis import (
    _is_numeric_pa_type,
    detect_time_axis_in_frame,
    set_datetime_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def dt_strings(n: int = 10, start: str = "2024-03-01 08:00:00", freq: str = "15s") -> list[str]:
    """Build *n* sorted ISO datetime strings."""
    return pd.date_range(start=start, periods=n, freq=freq).strftime("%Y-%m-%d %H:%M:%S").tolist()


def find_datetime_col(df: pd.DataFrame) -> str:
    """Detect the datetime column via the real public entry point, without mutating *df*."""
    return set_datetime_index(df).index.name


# ===========================================================================
# Content validation gates
# ===========================================================================


class TestContentValidation:
    """A name match alone is not enough: content must parse as plausible datetimes."""

    def test_unparseable_named_candidate_rejected_in_favor_of_valid_column(self):
        """'timestamp' full of garbage loses to a valid lower-tier 'acquisition_time'."""
        df = pd.DataFrame(
            {
                "timestamp": ["garbage"] * 10,
                "acquisition_time": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "acquisition_time"

    def test_mostly_parseable_column_accepted(self):
        """A single garbage value in 20 rows (95% parseable) clears the ≥90% gate."""
        values = dt_strings(20)
        values[10] = "sensor glitch"
        df = pd.DataFrame({"timestamp": values})
        assert find_datetime_col(df) == "timestamp"

    def test_heavily_garbled_column_rejected(self):
        """15% garbage fails the ≥90% parseable gate."""
        values = dt_strings(20)
        for i in (3, 9, 15):
            values[i] = "garbage"
        df = pd.DataFrame({"timestamp": values})
        with pytest.raises(ValueError, match="No datetime column detected"):
            find_datetime_col(df)

    def test_out_of_range_years_rejected(self):
        """Valid datetimes outside [2000, 2100] (e.g. legacy 1970 defaults) are rejected."""
        df = pd.DataFrame({"timestamp": dt_strings(10, start="1970-01-01 00:00:00")})
        with pytest.raises(ValueError, match="No datetime column detected"):
            find_datetime_col(df)

    def test_reversed_datetimes_fail_sortedness_gate(self):
        values = list(reversed(dt_strings(50)))
        df = pd.DataFrame({"timestamp": values})
        with pytest.raises(ValueError, match="No datetime column detected"):
            find_datetime_col(df)

    def test_minor_buffering_jitter_tolerated(self):
        """A couple of out-of-order values in 50 rows still clears the ≥90% sortedness gate."""
        values = dt_strings(50)
        values[10], values[11] = values[11], values[10]
        values[30], values[31] = values[31], values[30]
        df = pd.DataFrame({"timestamp": values})
        assert find_datetime_col(df) == "timestamp"


# ===========================================================================
# Tiered name search
# ===========================================================================


class TestNameTiers:
    """Exact matches beat substring matches; higher-confidence substrings beat lower."""

    def test_exact_name_beats_substring_candidate(self):
        df = pd.DataFrame(
            {
                "recording_datetime": dt_strings(10),
                "datetime": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "datetime"

    def test_datetime_substring_beats_time_substring(self):
        df = pd.DataFrame(
            {
                "chart_time": dt_strings(10),
                "recording_datetime": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "recording_datetime"

    def test_widen_tier_finds_unnamed_valid_column(self):
        """No name matches at all: a valid datetime column is still found by content."""
        df = pd.DataFrame(
            {
                "sensor_reading": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
                "recorded": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "recorded"

    def test_numeric_relative_time_column_skipped_in_name_tiers(self):
        """A numeric 'time' column (relative seconds) must lose to a real datetime column."""
        df = pd.DataFrame(
            {
                "time": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
                "recorded": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "recorded"

    def test_string_time_column_loses_to_explicit_datetime_utc(self):
        """
        A bare 'time' column, even if it parses fine, must lose to a more explicit name.

        'time' is ambiguous in real device exports (fluxmed's own raw format uses it for
        relative elapsed seconds, not an absolute timestamp) so it's deliberately not in
        EXACT_NAMES — only the lower-confidence substring tier, below 'datetime'.
        """
        df = pd.DataFrame(
            {
                "time": dt_strings(10),
                "datetime_utc": dt_strings(10),
            }
        )
        assert find_datetime_col(df) == "datetime_utc"

    def test_no_plausible_column_raises(self):
        df = pd.DataFrame({"a": ["x"] * 5, "b": [1.0, 2.0, 3.0, 4.0, 5.0]})
        with pytest.raises(ValueError, match="No datetime column detected"):
            find_datetime_col(df)


# ===========================================================================
# set_datetime_index
# ===========================================================================


class TestSetDatetimeIndex:
    def test_short_circuits_on_existing_datetime_index(self):
        df = pd.DataFrame(
            {"garbage_timestamp": ["x"] * 5, "value": range(5)},
            index=pd.date_range("2024-03-01", periods=5, freq="1min"),
        )
        result = set_datetime_index(df)
        assert result is df  # untouched, despite the unparseable name-matching column

    def test_sets_detected_column_as_datetime_index(self):
        df = pd.DataFrame({"timestamp": dt_strings(10), "value": range(10)})
        result = set_datetime_index(df)
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.name == "timestamp"
        assert list(result.columns) == ["value"]

    def test_raises_when_nothing_detected(self):
        df = pd.DataFrame({"a": ["x"] * 5})
        with pytest.raises(ValueError, match="No datetime column detected"):
            set_datetime_index(df)


# ===========================================================================
# Loaders
# ===========================================================================


class TestLoaders:
    def test_load_parquet_short_circuits_pre_indexed_file(self, tmp_path):
        df = pd.DataFrame(
            {"value": range(5)},
            index=pd.date_range("2024-03-01", periods=5, freq="1min", name="datetime"),
        )
        path = tmp_path / "data.parquet"
        df.to_parquet(path)
        result = set_datetime_index(pd.read_parquet(path))
        assert isinstance(result.index, pd.DatetimeIndex)
        assert list(result.columns) == ["value"]

    def test_load_parquet_detects_datetime_column(self, tmp_path):
        df = pd.DataFrame({"timestamp": dt_strings(10), "value": range(10)})
        path = tmp_path / "data.parquet"
        df.to_parquet(path)
        result = set_datetime_index(pd.read_parquet(path))
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.name == "timestamp"

    def test_load_csv_detects_datetime_column(self, tmp_path):
        df = pd.DataFrame({"acquisition_time": dt_strings(10), "value": range(10)})
        path = tmp_path / "data.csv"
        df.to_csv(path, index=False)
        result = set_datetime_index(pd.read_csv(path))
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.name == "acquisition_time"

    def test_load_csv_raises_on_undetectable_file(self, tmp_path):
        df = pd.DataFrame({"a": ["x"] * 5, "b": range(5)})
        path = tmp_path / "data.csv"
        df.to_csv(path, index=False)
        with pytest.raises(ValueError, match="No datetime column detected"):
            set_datetime_index(pd.read_csv(path))


# ===========================================================================
# Within-tier tiebreak: uniqueness ratio, then utc-name preference
# ===========================================================================

# Real intraoperative anesthesia record excerpt (Cerner SurgiNet/PowerChart-style schema,
# attributeId == 2423, first 20 rows): six simultaneously-plausible time columns plus two
# always-empty decoys. chartTime/measurementTime tie exactly on uniqueness (11/20 each,
# same "two readings per charting cycle" device quirk); storeTime is batchy (6/20).
# All three pairs are 100% non-decreasing, so only the tiebreak layer can separate them.

_CHART_TIME = [
    "2004-09-15 09:12:33.000000",
    "2004-09-15 09:12:48.000000",
    "2004-09-15 09:12:48.000000",
    "2004-09-15 09:13:03.000000",
    "2004-09-15 09:13:03.000000",
    "2004-09-15 09:13:18.000000",
    "2004-09-15 09:13:18.000000",
    "2004-09-15 09:13:33.000000",
    "2004-09-15 09:13:33.000000",
    "2004-09-15 09:13:48.000000",
    "2004-09-15 09:13:48.000000",
    "2004-09-15 09:14:03.000000",
    "2004-09-15 09:14:03.000000",
    "2004-09-15 09:14:18.000000",
    "2004-09-15 09:14:18.000000",
    "2004-09-15 09:14:33.000000",
    "2004-09-15 09:14:33.000000",
    "2004-09-15 09:14:48.000000",
    "2004-09-15 09:14:48.000000",
    "2004-09-15 09:15:03.000000",
]

_MEASUREMENT_TIME = [
    "2004-09-15 09:12:38.993000",
    "2004-09-15 09:12:54.003000",
    "2004-09-15 09:12:54.003000",
    "2004-09-15 09:13:09.007000",
    "2004-09-15 09:13:09.007000",
    "2004-09-15 09:13:24.007000",
    "2004-09-15 09:13:24.007000",
    "2004-09-15 09:13:40.000000",
    "2004-09-15 09:13:40.000000",
    "2004-09-15 09:13:54.997000",
    "2004-09-15 09:13:54.997000",
    "2004-09-15 09:14:09.993000",
    "2004-09-15 09:14:09.993000",
    "2004-09-15 09:14:25.007000",
    "2004-09-15 09:14:25.007000",
    "2004-09-15 09:14:40.007000",
    "2004-09-15 09:14:40.007000",
    "2004-09-15 09:14:55.993000",
    "2004-09-15 09:14:55.993000",
    "2004-09-15 09:15:11.007000",
]

_STORE_TIME = [
    "2004-09-15 09:13:22.807000",
    "2004-09-15 09:13:22.807000",
    "2004-09-15 09:13:22.807000",
    "2004-09-15 09:15:23.707000",
    "2004-09-15 09:15:23.710000",
    "2004-09-15 09:15:23.710000",
    "2004-09-15 09:15:23.710000",
    "2004-09-15 09:15:23.710000",
    "2004-09-15 09:15:23.710000",
    "2004-09-15 09:15:23.713000",
    "2004-09-15 09:15:23.713000",
    "2004-09-15 09:15:23.713000",
    "2004-09-15 09:15:23.713000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:15:23.717000",
    "2004-09-15 09:17:24.277000",
]

_VALUE_NUMBER = [
    89.144493,
    80.902524,
    83.28179,
    57.148389,
    85.222195,
    90.622976,
    85.570173,
    94.384176,
    82.129432,
    82.856329,
    75.289005,
    76.269333,
    77.937789,
    78.909847,
    91.028646,
    87.648064,
    56.926951,
    59.250567,
    88.793401,
    82.28927,
]

# Numeric-looking strings, unsorted — must never be picked as datetime.
_TERSE_FORM = [
    "82",
    "89",
    "83",
    "92",
    "79",
    "77",
    "76",
    "101",
    "82",
    "92",
    "59",
    "77",
    "100",
    "83",
    "83",
    "93",
    "85",
    "88",
    "65",
    "97",
]


def _shift_to_utc(local: list[str]) -> list[str]:
    """The utc twins in the real file lag local time by exactly one hour."""
    return (
        (pd.to_datetime(pd.Series(local)) - pd.Timedelta(hours=1))
        .dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        .tolist()
    )


def anesthesia_record_df() -> pd.DataFrame:
    """Column order mirrors the real file (matters for the final column-order tiebreak)."""
    return pd.DataFrame(
        {
            "chartTime": _CHART_TIME,
            "utcChartTime": _shift_to_utc(_CHART_TIME),
            "measurementTime": _MEASUREMENT_TIME,
            "utcmeasurementTime": _shift_to_utc(_MEASUREMENT_TIME),
            "valueDateTime": [""] * 20,
            "utcValueDateTime": [""] * 20,
            "valueNumber": _VALUE_NUMBER,
            "terseForm": _TERSE_FORM,
            "storeTime": _STORE_TIME,
            "utcStoreTime": _shift_to_utc(_STORE_TIME),
        }
    )


class TestWithinTierTiebreak:
    """Several same-tier candidates all pass validation: uniqueness ratio, then utc-preference."""

    def test_anesthesia_record_lands_on_a_utc_high_uniqueness_column(self):
        """
        Uniqueness ratio, then utc-preference, must land on a utc twin.

        Uniqueness eliminates the batchy storeTime pair (6/20 unique vs 11/20);
        utc-preference then eliminates the DST-prone naive-local pair. The remaining
        tie (utcChartTime vs utcmeasurementTime) is broken by incidental column order,
        so either is acceptable — but never storeTime, the empty decoys, or terseForm.
        """
        result = find_datetime_col(anesthesia_record_df())
        assert result in {"utcChartTime", "utcmeasurementTime"}


# ===========================================================================
# Numeric-epoch tier (nanoseconds only, tried last)
# ===========================================================================


class TestNumericEpochTier:
    """Numeric columns are only considered last, as nanosecond epochs."""

    def test_ns_epoch_column_detected_when_no_string_candidate_exists(self):
        dates = pd.date_range("2024-03-01 08:00:00", periods=10, freq="15s")
        epoch_ns = dates.as_unit("ns").astype("int64")
        df = pd.DataFrame(
            {
                "sensor_reading": [89.1, 80.9, 83.2, 57.1, 85.2, 90.6, 85.5, 94.3, 82.1, 82.8],
                "acquisition": epoch_ns,
            }
        )
        assert find_datetime_col(df) == "acquisition"


# ===========================================================================
# Multilingual name tiers (mirrors fluxmed's TIME_HEADER_PREFIXES convention)
# ===========================================================================


class TestMultilingualNames:
    """Non-English 'time' tokens (Spanish/Portuguese-Italian/French/German) are recognized."""

    @pytest.mark.parametrize("column_name", ["Tiempo", "Tempo", "Temps", "Zeit"])
    def test_translated_time_column_detected(self, column_name):
        df = pd.DataFrame({column_name: dt_strings(10), "value": range(10)})
        assert find_datetime_col(df) == column_name


# ===========================================================================
# UTC auto-localization on utc-named winners
# ===========================================================================


class TestUtcAutoLocalization:
    """A winning column whose name says 'utc' gets localized to UTC, not left tz-naive."""

    def test_utc_named_naive_winner_is_localized(self):
        df = pd.DataFrame({"utcTimestamp": dt_strings(10), "value": range(10)})
        result = set_datetime_index(df)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_non_utc_named_winner_stays_naive(self):
        df = pd.DataFrame({"timestamp": dt_strings(10), "value": range(10)})
        result = set_datetime_index(df)
        assert result.index.tz is None


class TestNumericTypeClassificationAgreement:
    """
    Tripwire for a code-review finding on issue #57: schema-only detection
    (`_is_numeric_pa_type`, pyarrow-type-based) and full-frame detection
    (`detect_time_axis_in_frame`, `pd.api.types.is_numeric_dtype`-based) each decide
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
