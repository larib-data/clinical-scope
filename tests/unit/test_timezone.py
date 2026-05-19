"""Unit tests for timezone utility functions."""

from clinical_scope.constants import PatientOptions
from clinical_scope.dash_api.validation import validate_value
from clinical_scope.datasource.formatting.timezone import to_naive_display_ts


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

    def test_invalid_timezone_logs_warning_and_returns_input(self):
        ts = "2023-06-15T12:00:00+00:00"
        result = to_naive_display_ts(ts, "Invalid/Timezone")
        assert result == ts


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
