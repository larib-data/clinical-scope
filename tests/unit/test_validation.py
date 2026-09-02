"""
Tests for validation.py -- the reporter every config-loading tier shares.

Covers:
- log_database_options_issues()  -- severity to log level, including a severity nobody declared
- the three callers (wrapper, config.parsing, dash_api data callbacks) -- each keeps
  its own logger name on the records it emits
"""

import json
import logging

from clinical_scope import validation
from clinical_scope.config.parsing import load_database_options_from_path
from clinical_scope.dash_api.callbacks.data_callbacks import _parse_database_options_file
from clinical_scope.wrapper import _resolve_database_options

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue_triple_config() -> dict:
    """A database_options tripping exactly one issue of each severity."""
    return {
        "servo_u": {
            "signals": {"HR": {"label": "HR"}},  # info: the label restates the raw name
            "field_display": "HR",  # error: must be a list
            "unknown_key": 1,  # warning: not a known section key
        }
    }


def _from(caplog, logger_name: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == logger_name]


# ===========================================================================
# log_database_options_issues — severity to level
# ===========================================================================


class TestLogDatabaseOptionsIssues:
    def test_each_severity_logs_at_the_level_it_names(self, caplog):
        issues = [
            validation.ValidationIssue(severity="error", path="p1", message="m1"),
            validation.ValidationIssue(severity="warning", path="p2", message="m2"),
            validation.ValidationIssue(severity="info", path="p3", message="m3"),
        ]
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues(issues, logging.getLogger("caller.under.test"))
        assert [record.levelname for record in caplog.records] == ["ERROR", "WARNING", "INFO"]

    def test_unrecognised_severity_reports_at_info(self, caplog):
        # severity is a Literal for type-checkers only; a stray value must not raise.
        issue = validation.ValidationIssue(severity="catastrophic", path="p", message="m")
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues([issue], logging.getLogger("caller.under.test"))
        assert [record.levelname for record in caplog.records] == ["INFO"]

    def test_path_and_message_reach_the_record(self, caplog):
        issue = validation.ValidationIssue(
            severity="error", path="servo_u.signals.HR", message="something is off"
        )
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues([issue], logging.getLogger("caller.under.test"))
        emitted = caplog.records[0].getMessage()
        assert "servo_u.signals.HR" in emitted
        assert "something is off" in emitted

    def test_logs_under_the_logger_it_is_handed(self, caplog):
        issue = validation.ValidationIssue(severity="error", path="p", message="m")
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues([issue], logging.getLogger("caller.under.test"))
        assert [record.name for record in caplog.records] == ["caller.under.test"]

    def test_record_origin_stays_with_the_caller(self, caplog):
        issue = validation.ValidationIssue(severity="error", path="p", message="m")
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues([issue], logging.getLogger("caller.under.test"))
        assert caplog.records[0].funcName == "test_record_origin_stays_with_the_caller"
        assert caplog.records[0].filename == "test_validation.py"

    def test_no_issues_logs_nothing(self, caplog):
        with caplog.at_level(logging.DEBUG):
            validation.log_database_options_issues([], logging.getLogger("caller.under.test"))
        assert caplog.records == []


# ===========================================================================
# The three callers — each reports under its own name
# ===========================================================================


class TestCallersKeepTheirOwnLoggerName:
    def test_wrapper(self, caplog):
        with caplog.at_level(logging.INFO):
            _resolve_database_options(_issue_triple_config())
        records = _from(caplog, "clinical_scope.wrapper")
        assert {record.levelname for record in records} == {"ERROR", "WARNING", "INFO"}

    def test_config_parsing(self, caplog, tmp_path):
        path = tmp_path / "database_options.json"
        path.write_text(json.dumps(_issue_triple_config()), encoding="utf-8")
        with caplog.at_level(logging.INFO):
            load_database_options_from_path(path)
        records = _from(caplog, "clinical_scope.config.parsing")
        assert {record.levelname for record in records} == {"ERROR", "WARNING", "INFO"}

    def test_dash_data_callbacks(self, caplog):
        content = json.dumps(_issue_triple_config()).encode("utf-8")
        with caplog.at_level(logging.INFO):
            _parse_database_options_file(content, "uploaded.json")
        records = _from(caplog, "clinical_scope.dash_api.callbacks.data_callbacks")
        assert {record.levelname for record in records} == {"ERROR", "WARNING", "INFO"}
