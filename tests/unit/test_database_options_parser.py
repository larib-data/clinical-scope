"""Unit tests for database_options_parser.py."""

import logging

from clinical_data_visualizer.database_options_parser import (
    normalize_datasource_options,
    validate_database_options_structure,
    warn_redundant_entries,
)

# ---------------------------------------------------------------------------
# normalize_datasource_options
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_auto_populates_field_display(self):
        raw = {"signals": {"ART": {}, "PAP": {}}}
        result = normalize_datasource_options(raw)
        assert set(result["field_display"]) == {"ART", "PAP"}

    def test_preserves_explicit_field_display(self):
        raw = {"signals": {"ART": {}, "PAP": {}}, "field_display": ["ART"]}
        result = normalize_datasource_options(raw)
        assert result["field_display"] == ["ART"]

    def test_no_signals_key(self):
        raw = {"numerics": {"priority": 1}}
        result = normalize_datasource_options(raw)
        assert "field_display" not in result

    def test_does_not_mutate_original(self):
        raw = {"signals": {"X": {}}}
        original_keys = set(raw.keys())
        normalize_datasource_options(raw)
        assert set(raw.keys()) == original_keys

    def test_warns_unknown_signal_keys(self, caplog):
        raw = {"signals": {"ART": {"label": "ok", "bogus_key": 42}}}
        with caplog.at_level(logging.WARNING):
            normalize_datasource_options(raw)
        assert any("Unknown key" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# validate_database_options_structure
# ---------------------------------------------------------------------------


class TestValidateStructure:
    def test_valid_structure_no_warnings(self):
        db_opts = {
            "philips_waves": {
                "signals": {},
                "field_display": [],
                "numerics": {},
                "grouped_fields": {},
            },
            "global": {"grouped_fields": {}},
        }
        warnings = validate_database_options_structure(db_opts)
        assert warnings == []

    def test_unknown_section_key(self):
        db_opts = {
            "philips_waves": {
                "signals": {},
                "unknown_key": "value",
            }
        }
        warnings = validate_database_options_structure(db_opts)
        assert len(warnings) == 1
        assert "unknown_key" in warnings[0]

    def test_global_section_ignored(self):
        db_opts = {"global": {"anything": "goes"}}
        warnings = validate_database_options_structure(db_opts)
        assert warnings == []


# ---------------------------------------------------------------------------
# warn_redundant_entries
# ---------------------------------------------------------------------------


class TestWarnRedundant:
    def test_warns_label_equals_raw_name(self, caplog):
        raw = {"signals": {"ART": {"label": "ART"}}}
        with caplog.at_level(logging.INFO):
            warn_redundant_entries(raw, "test_ds")
        assert any("identical to raw_name" in msg for msg in caplog.messages)

    def test_warns_unit_conversion_1(self, caplog):
        raw = {"signals": {"ART": {"unit_conversion": 1.0}}}
        with caplog.at_level(logging.INFO):
            warn_redundant_entries(raw, "test_ds")
        assert any("unit_conversion" in msg for msg in caplog.messages)

    def test_warns_default_unit(self, caplog):
        raw = {"signals": {"ART": {"unit": "-"}}}
        with caplog.at_level(logging.INFO):
            warn_redundant_entries(raw, "test_ds")
        assert any("default" in msg for msg in caplog.messages)

    def test_no_warnings_for_good_config(self, caplog):
        raw = {"signals": {"ART": {"label": "Arterial", "unit": "mmHg"}}}
        with caplog.at_level(logging.INFO):
            warn_redundant_entries(raw, "test_ds")
        assert not caplog.messages

    def test_no_signals_key(self, caplog):
        raw = {"numerics": {}}
        with caplog.at_level(logging.INFO):
            warn_redundant_entries(raw, "test_ds")
        assert not caplog.messages
