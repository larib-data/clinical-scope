"""Unit tests for database_options_parser.py."""

from clinical_scope.database_options_parser import (
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
            "servo_u": {
                "signals": {},
                "field_display": [],
                "numerics": {},
                "grouped_fields": {},
            },
            "global": {"grouped_fields": {}},
        }
        assert validate_database_options(db) == []

    def test_unknown_section_key(self):
        db = {"servo_u": {"signals": {}, "unknown_key": "value"}}
        warnings = _issues("warning", db)
        assert len(warnings) == 1
        assert "unknown_key" in warnings[0].message

    def test_global_section_ignored(self):
        db = {"global": {"anything": "goes"}}
        assert validate_database_options(db) == []

    def test_unknown_signal_key(self):
        db = {"servo_u": {"signals": {"HR": {"label": "ok", "bogus_key": 42}}}}
        warnings = _issues("warning", db)
        assert any("bogus_key" in i.message for i in warnings)

    def test_other_prefix_keys_validated(self):
        db = {"other::waves": {"signals": {}, "bad_key": 1}}
        warnings = _issues("warning", db)
        assert len(warnings) == 1
        assert "other.files.waves" in warnings[0].path

    def test_unknown_spectrogram_key(self):
        db = {
            "eit": {
                "spectrogram": {"S1": {"signal": "S1", "freq_range": [0.5, 30.0], "bogus_key": 1}}
            }
        }
        warnings = _issues("warning", db)
        assert any("bogus_key" in i.message for i in warnings)

    def test_unknown_psd_key(self):
        db = {
            "eit": {"psd": {"S1": {"signals": ["S1"], "freq_range": [0.5, 30.0], "bogus_key": 1}}}
        }
        warnings = _issues("warning", db)
        assert any("bogus_key" in i.message for i in warnings)


# ---------------------------------------------------------------------------
# Type errors
# ---------------------------------------------------------------------------


class TestTypeChecks:
    def test_signals_must_be_dict(self):
        db = {"servo_u": {"signals": ["HR", "SpO2"]}}
        errors = _issues("error", db)
        assert any("signals" in i.path for i in errors)

    def test_field_display_must_be_list(self):
        db = {"servo_u": {"field_display": "HR"}}
        errors = _issues("error", db)
        assert any("field_display" in i.path for i in errors)

    def test_grouped_fields_must_be_dict(self):
        db = {"servo_u": {"grouped_fields": ["HR"]}}
        errors = _issues("error", db)
        assert any("grouped_fields" in i.path for i in errors)

    def test_unit_conversion_must_be_numeric(self):
        db = {"servo_u": {"signals": {"HR": {"unit_conversion": "not_a_number"}}}}
        errors = _issues("error", db)
        assert any("unit_conversion" in i.path for i in errors)

    def test_range_must_be_two_element_list(self):
        db = {"servo_u": {"signals": {"HR": {"range": [0]}}}}
        errors = _issues("error", db)
        assert any("range" in i.path for i in errors)

    def test_range_elements_must_be_numeric(self):
        db = {"servo_u": {"signals": {"HR": {"range": ["low", "high"]}}}}
        errors = _issues("error", db)
        assert any("range" in i.path for i in errors)

    def test_visible_non_bool_is_warning(self):
        db = {"servo_u": {"signals": {"HR": {"visible": "yes"}}}}
        warnings = _issues("warning", db)
        assert any("visible" in i.path for i in warnings)

    def test_valid_types_no_errors(self):
        db = {
            "servo_u": {
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

    def test_spectrogram_must_be_dict(self):
        db = {"eit": {"spectrogram": ["S1"]}}
        errors = _issues("error", db)
        assert any("spectrogram" in i.path for i in errors)

    def test_spectrogram_missing_signal_key(self):
        db = {"eit": {"spectrogram": {"S1": {"freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any("Missing required key 'signal'" in i.message for i in errors)

    def test_spectrogram_freq_range_missing(self):
        db = {"eit": {"spectrogram": {"S1": {"signal": "S1"}}}}
        errors = _issues("error", db)
        assert any("freq_range" in i.path for i in errors)

    def test_spectrogram_freq_range_must_be_two_numbers(self):
        db = {"eit": {"spectrogram": {"S1": {"signal": "S1", "freq_range": [0.5]}}}}
        errors = _issues("error", db)
        assert any("freq_range" in i.path for i in errors)

    def test_spectrogram_valid_no_errors(self):
        db = {"eit": {"spectrogram": {"S1": {"signal": "S1", "freq_range": [0.5, 30.0]}}}}
        assert _issues("error", db) == []

    def test_psd_must_be_dict(self):
        db = {"eit": {"psd": ["S1"]}}
        errors = _issues("error", db)
        assert any("psd" in i.path for i in errors)

    def test_psd_missing_signals_key(self):
        db = {"eit": {"psd": {"S1": {"freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any(i.path.endswith(".signals") for i in errors)

    def test_psd_signals_must_not_be_empty(self):
        db = {"eit": {"psd": {"S1": {"signals": [], "freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any(i.path.endswith(".signals") for i in errors)

    def test_psd_signals_must_be_a_list_not_a_bare_name(self):
        db = {"eit": {"psd": {"S1": {"signals": "S1", "freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any(i.path.endswith(".signals") for i in errors)

    def test_psd_freq_range_missing(self):
        db = {"eit": {"psd": {"S1": {"signals": ["S1"]}}}}
        errors = _issues("error", db)
        assert any("freq_range" in i.path for i in errors)

    def test_psd_valid_no_errors(self):
        db = {"eit": {"psd": {"S1": {"signals": ["S1", "S2"], "freq_range": [0.5, 30.0]}}}}
        assert _issues("error", db) == []

    def test_psd_entry_dict_valid_no_errors(self):
        db = {
            "eit": {
                "psd": {
                    "S1": {
                        "signals": [
                            {
                                "signal": "S1",
                                "window_s": 2,
                                "overlap": 0.5,
                                "label": "a",
                                "color": "red",
                                "line_dash": "dash",
                            }
                        ],
                        "freq_range": [0.5, 30.0],
                    }
                }
            }
        }
        assert _issues("error", db) == []

    def test_psd_entry_dict_missing_signal_key(self):
        db = {"eit": {"psd": {"S1": {"signals": [{"window_s": 2}], "freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any("Missing required key 'signal'" in i.message for i in errors)

    def test_psd_entry_dict_unknown_key_is_warning(self):
        db = {
            "eit": {
                "psd": {
                    "S1": {
                        "signals": [{"signal": "S1", "bogus_key": 1}],
                        "freq_range": [0.5, 30.0],
                    }
                }
            }
        }
        warnings = _issues("warning", db)
        assert any("bogus_key" in i.message for i in warnings)

    def test_psd_entry_neither_string_nor_dict_is_error(self):
        db = {"eit": {"psd": {"S1": {"signals": [123], "freq_range": [0.5, 30.0]}}}}
        errors = _issues("error", db)
        assert any(i.path.endswith(".signals[0]") for i in errors)


# ---------------------------------------------------------------------------
# Redundant entries (info severity)
# ---------------------------------------------------------------------------


class TestRedundantEntries:
    def test_label_equals_raw_name(self):
        db = {"servo_u": {"signals": {"ART": {"label": "ART"}}}}
        infos = _issues("info", db)
        assert any("identical to raw_name" in i.message for i in infos)

    def test_unit_conversion_is_default(self):
        db = {"servo_u": {"signals": {"ART": {"unit_conversion": 1.0}}}}
        infos = _issues("info", db)
        assert any("unit_conversion" in i.message for i in infos)

    def test_unit_is_default(self):
        db = {"servo_u": {"signals": {"ART": {"unit": "-"}}}}
        infos = _issues("info", db)
        assert any("unit='-'" in i.message for i in infos)

    def test_no_redundancy_for_good_config(self):
        db = {"servo_u": {"signals": {"ART": {"label": "Arterial", "unit": "mmHg"}}}}
        assert _issues("info", db) == []

    def test_no_signals_key(self):
        db = {"servo_u": {"numerics": {}}}
        assert validate_database_options(db) == []


# ---------------------------------------------------------------------------
# trace_options
# ---------------------------------------------------------------------------


class TestTraceOptions:
    def test_unknown_trace_option_key_warns(self):
        db = {"servo_u": {"trace_options": {"line_widht": 2.0}}}
        warnings = _issues("warning", db)
        assert len(warnings) == 1
        assert "line_widht" in warnings[0].message

    def test_documented_trace_option_keys_pass(self):
        db = {
            "servo_u": {
                "trace_options": {
                    "mode": "lines+markers",
                    "line_width": 2.0,
                    "line_dash": "dot",
                    "opacity": 0.8,
                    "marker_symbol": "circle",
                    "marker_size": 4.0,
                }
            }
        }
        assert _issues("warning", db) == []

    def test_trace_options_known_keys_are_real(self):
        """Every advertised key must be a TraceOptions field, else it is silently dropped."""
        from dataclasses import fields

        import clinical_scope.constants as cst
        from clinical_scope.signal_container import TraceOptions

        trace_option_fields = {field_obj.name for field_obj in fields(TraceOptions)}
        assert cst.DatabaseOptions.TraceOptionsConfig.KNOWN_KEYS <= trace_option_fields

    def test_trace_options_must_be_a_dict(self):
        db = {"servo_u": {"trace_options": "lines"}}
        errors = _issues("error", db)
        assert len(errors) == 1
