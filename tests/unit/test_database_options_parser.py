"""Unit tests for database_options_parser.py."""

from clinical_data_visualizer.database_options_parser import (
    ValidationIssue,
    validate_database_options,
)


def _issues(severity: str, db: dict) -> list[ValidationIssue]:
    return [i for i in validate_database_options(db) if i.severity == severity]


# ---------------------------------------------------------------------------
# Unknown keys
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    def test_valid_structure_no_warnings(self):
        db = {
            "philips_waves": {
                "signals": {},
                "field_display": [],
                "numerics": {},
                "grouped_fields": {},
            },
            "global": {"grouped_fields": {}},
        }
        assert validate_database_options(db) == []

    def test_unknown_section_key(self):
        db = {"philips_waves": {"signals": {}, "unknown_key": "value"}}
        warnings = _issues("warning", db)
        assert len(warnings) == 1
        assert "unknown_key" in warnings[0].message

    def test_global_section_ignored(self):
        db = {"global": {"anything": "goes"}}
        assert validate_database_options(db) == []

    def test_unknown_signal_key(self):
        db = {"philips_waves": {"signals": {"HR": {"label": "ok", "bogus_key": 42}}}}
        warnings = _issues("warning", db)
        assert any("bogus_key" in i.message for i in warnings)

    def test_other_prefix_keys_validated(self):
        db = {"other::waves": {"signals": {}, "bad_key": 1}}
        warnings = _issues("warning", db)
        assert len(warnings) == 1
        assert "other.files.waves" in warnings[0].path


# ---------------------------------------------------------------------------
# Type errors
# ---------------------------------------------------------------------------


class TestTypeChecks:
    def test_signals_must_be_dict(self):
        db = {"philips_waves": {"signals": ["HR", "SpO2"]}}
        errors = _issues("error", db)
        assert any("signals" in i.path for i in errors)

    def test_field_display_must_be_list(self):
        db = {"philips_waves": {"field_display": "HR"}}
        errors = _issues("error", db)
        assert any("field_display" in i.path for i in errors)

    def test_grouped_fields_must_be_dict(self):
        db = {"philips_waves": {"grouped_fields": ["HR"]}}
        errors = _issues("error", db)
        assert any("grouped_fields" in i.path for i in errors)

    def test_unit_conversion_must_be_numeric(self):
        db = {"philips_waves": {"signals": {"HR": {"unit_conversion": "not_a_number"}}}}
        errors = _issues("error", db)
        assert any("unit_conversion" in i.path for i in errors)

    def test_range_must_be_two_element_list(self):
        db = {"philips_waves": {"signals": {"HR": {"range": [0]}}}}
        errors = _issues("error", db)
        assert any("range" in i.path for i in errors)

    def test_range_elements_must_be_numeric(self):
        db = {"philips_waves": {"signals": {"HR": {"range": ["low", "high"]}}}}
        errors = _issues("error", db)
        assert any("range" in i.path for i in errors)

    def test_visible_non_bool_is_warning(self):
        db = {"philips_waves": {"signals": {"HR": {"visible": "yes"}}}}
        warnings = _issues("warning", db)
        assert any("visible" in i.path for i in warnings)

    def test_valid_types_no_errors(self):
        db = {
            "philips_waves": {
                "signals": {
                    "HR": {
                        "unit_conversion": 0.5,
                        "range": [0, 200],
                        "visible": True,
                    }
                }
            }
        }
        assert _issues("error", db) == []


# ---------------------------------------------------------------------------
# Redundant entries (info severity)
# ---------------------------------------------------------------------------


class TestRedundantEntries:
    def test_label_equals_raw_name(self):
        db = {"philips_waves": {"signals": {"ART": {"label": "ART"}}}}
        infos = _issues("info", db)
        assert any("identical to raw_name" in i.message for i in infos)

    def test_unit_conversion_is_default(self):
        db = {"philips_waves": {"signals": {"ART": {"unit_conversion": 1.0}}}}
        infos = _issues("info", db)
        assert any("unit_conversion" in i.message for i in infos)

    def test_unit_is_default(self):
        db = {"philips_waves": {"signals": {"ART": {"unit": "-"}}}}
        infos = _issues("info", db)
        assert any("unit='-'" in i.message for i in infos)

    def test_no_redundancy_for_good_config(self):
        db = {"philips_waves": {"signals": {"ART": {"label": "Arterial", "unit": "mmHg"}}}}
        assert _issues("info", db) == []

    def test_no_signals_key(self):
        db = {"philips_waves": {"numerics": {}}}
        assert validate_database_options(db) == []
