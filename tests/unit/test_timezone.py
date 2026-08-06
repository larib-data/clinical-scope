"""Unit tests for timezone utility functions."""

import clinical_scope.constants as cst
from clinical_scope.constants import PatientOptions
from clinical_scope.dash_api.validation import validate_value
from clinical_scope.datasource.formatting.timezone import (
    resolve_display_timezone,
    to_aware_display_ts,
    to_naive_display_ts,
)


class TestToNaiveDisplayTs:
    def test_tz_aware_converted_to_display_tz(self):
        result = to_naive_display_ts("2023-06-15T12:00:00+00:00", "Europe/Paris")
        # UTC noon → 14:00 in Paris (CEST, +02:00 in summer)
        assert result == "2023-06-15T14:00:00"

    def test_tz_aware_utc_plus_one(self):
        result = to_naive_display_ts("2023-01-15T13:00:00+01:00", "UTC")
        # 13:00+01:00 = 12:00 UTC
        assert result == "2023-01-15T12:00:00"

    def test_already_naive_passthrough(self):
        ts = "2023-06-15T13:00:00"
        assert to_naive_display_ts(ts, "Europe/Paris") == ts

    def test_none_display_timezone_uses_default(self):
        result = to_naive_display_ts("2023-06-15T12:00:00+00:00", None)
        assert isinstance(result, str)
        assert "T" in result

    def test_non_datetime_string_passthrough(self):
        assert to_naive_display_ts("3.14159", "Europe/Paris") == "3.14159"
        assert to_naive_display_ts("not-a-date", "Europe/Paris") == "not-a-date"

    def test_empty_string_passthrough(self):
        assert to_naive_display_ts("", "Europe/Paris") == ""

    def test_invalid_timezone_logs_warning_and_falls_back(self):
        ts = "2023-06-15T12:00:00+00:00"
        result = to_naive_display_ts(ts, "Invalid/Timezone")
        # Falls back to cst.DISPLAY_TIMEZONE rather than raising.
        assert result == to_naive_display_ts(ts, cst.DISPLAY_TIMEZONE)

    def test_sep_argument_controls_separator(self):
        result = to_naive_display_ts("2023-06-15T12:00:00+00:00", "UTC", sep=" ")
        assert result == "2023-06-15 12:00:00"

    def test_default_sep_is_t(self):
        result = to_naive_display_ts("2023-06-15T12:00:00+00:00", "UTC")
        assert result == "2023-06-15T12:00:00"


class TestToAwareDisplayTs:
    def test_naive_localized_to_display_tz(self):
        result = to_aware_display_ts("2023-06-15 12:00:00", "Europe/Paris")
        assert result == "2023-06-15T12:00:00+02:00"

    def test_naive_localized_to_utc(self):
        result = to_aware_display_ts("2023-01-15 12:00:00", "UTC")
        assert result == "2023-01-15T12:00:00+00:00"

    def test_already_aware_passthrough_is_idempotent(self):
        ts = "2023-06-15T12:00:00+02:00"
        assert to_aware_display_ts(ts, "America/New_York") == ts

    def test_none_display_timezone_uses_default(self):
        result = to_aware_display_ts("2023-06-15 12:00:00", None)
        assert isinstance(result, str)
        assert "+" in result or "-" in result[10:]  # carries a UTC offset

    def test_non_datetime_string_passthrough(self):
        assert to_aware_display_ts("3.14159", "Europe/Paris") == "3.14159"
        assert to_aware_display_ts("not-a-date", "Europe/Paris") == "not-a-date"

    def test_empty_string_passthrough(self):
        assert to_aware_display_ts("", "Europe/Paris") == ""

    def test_invalid_timezone_logs_warning_and_falls_back(self):
        result = to_aware_display_ts("2023-06-15 12:00:00", "Invalid/Timezone")
        # Falls back to cst.DISPLAY_TIMEZONE rather than raising.
        assert result == to_aware_display_ts("2023-06-15 12:00:00", cst.DISPLAY_TIMEZONE)

    def test_round_trip_with_to_naive_display_ts(self):
        naive = "2023-06-15 12:00:00"
        aware = to_aware_display_ts(naive, "Europe/Paris")
        assert to_naive_display_ts(aware, "Europe/Paris", sep=" ") == naive


class TestResolveDisplayTimezone:
    def test_valid_name_passes_through(self):
        assert resolve_display_timezone("Europe/Paris") == "Europe/Paris"

    def test_none_falls_back_to_default(self):
        assert resolve_display_timezone(None) == cst.DISPLAY_TIMEZONE

    def test_empty_string_falls_back_to_default(self):
        assert resolve_display_timezone("") == cst.DISPLAY_TIMEZONE

    def test_invalid_name_falls_back_to_default_and_logs(self):
        assert resolve_display_timezone("NotATimezone") == cst.DISPLAY_TIMEZONE


class TestTimezoneValidation:
    """Timezone validation via validate_value (schema-class level)."""

    def test_valid_timezone_accepted(self):
        ok, msg = validate_value(PatientOptions.DisplayTimezone, "Europe/Paris")
        assert ok
        assert msg == ""

    def test_valid_utc_accepted(self):
        ok, _msg = validate_value(PatientOptions.DisplayTimezone, "UTC")
        assert ok

    def test_invalid_timezone_rejected(self):
        ok, msg = validate_value(PatientOptions.DisplayTimezone, "NotATimezone")
        assert not ok
        assert "IANA" in msg

    def test_empty_string_is_not_mandatory(self):
        ok, _msg = validate_value(PatientOptions.DisplayTimezone, "")
        assert ok  # not mandatory, empty is allowed
