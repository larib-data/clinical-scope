"""
Tests for the one-line found/not-found datasource summary (cheap debugging aid).

Covers:
- _format_datasource_summary()   (wrapper.py) -- pure rendering
- wrapper.main() / inspect() / extract_patient() -- each logs the summary; 'other'
  gets special handling (file-stem breakdown for main/inspect, excluded from extract)
"""

from clinical_scope import wrapper
from clinical_scope.wrapper import _format_datasource_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary_lines(caplog) -> list[str]:
    """The captured found/not-found summary line(s), among all other captured logs."""
    return [line for line in caplog.messages if line.startswith(("Found:", "Not found"))]


# ===========================================================================
# _format_datasource_summary — pure rendering
# ===========================================================================


class TestFormatDatasourceSummary:
    def test_nothing_requested(self):
        assert _format_datasource_summary({}, []) == "No datasource requested."

    def test_all_found_no_annotation(self):
        found = {"eit": "", "philips_waves": ""}
        message = _format_datasource_summary(found, ["eit", "philips_waves"])
        assert message == "Found: eit, philips_waves"

    def test_all_not_found(self):
        message = _format_datasource_summary({}, ["eit", "philips_waves"])
        assert message == "Not found (2): eit, philips_waves"

    def test_mixed_found_and_not_found(self):
        message = _format_datasource_summary({"eit": ""}, ["eit", "philips_waves", "syringe"])
        assert message == "Found: eit | Not found (2): philips_waves, syringe"

    def test_annotation_is_rendered_in_parens(self):
        message = _format_datasource_summary({"other": "waves, numerics"}, ["other"])
        assert message == "Found: other (waves, numerics)"

    def test_found_but_not_in_requested_is_ignored_for_not_found(self):
        """A name present in `found` but absent from `requested` shouldn't create a stray entry."""
        message = _format_datasource_summary({"eit": ""}, ["eit"])
        assert "Not found" not in message


# ===========================================================================
# wrapper.main() -- 'other' gets a file-stem breakdown, not a bare "found"
# ===========================================================================


class TestMainDatasourceSummary:
    def test_logs_found_and_not_found(self, patient_options_difficult, caplog):
        with caplog.at_level("INFO"):
            wrapper.main(patient_options=patient_options_difficult)

        lines = _summary_lines(caplog)
        assert len(lines) == 1
        assert "philips_waves" in lines[0]
        assert "eit" in lines[0]  # eit has no folder in Patient_difficult_format -> "not found"

    def test_other_shows_file_stems_not_bare_found(self, patient_options_difficult, caplog):
        with caplog.at_level("INFO"):
            wrapper.main(patient_options=patient_options_difficult)

        summary = next(line for line in _summary_lines(caplog) if line.startswith("Found:"))
        assert "other (" in summary
        assert "waves_first_half_filtered" in summary


# ===========================================================================
# wrapper.inspect() -- same 'other' file-stem breakdown, derived from the
# "other::<stem>" DataSourceInspection naming convention
# ===========================================================================


class TestInspectDatasourceSummary:
    def test_other_shows_file_stems(self, patient_options_difficult, caplog):
        with caplog.at_level("INFO"):
            wrapper.inspect(patient_options=patient_options_difficult)

        summary = next(line for line in _summary_lines(caplog) if line.startswith("Found:"))
        assert "other (" in summary
        assert "waves_first_half_filtered" in summary


# ===========================================================================
# wrapper.extract_patient() -- 'other' excluded entirely (extract() always
# returns None for it by design, so it would always misreport as "not found")
# ===========================================================================


class TestExtractPatientDatasourceSummary:
    def test_other_excluded_from_summary(self, patient_difficult_path, caplog):
        with caplog.at_level("INFO"):
            wrapper.extract_patient(patient_difficult_path)

        lines = _summary_lines(caplog)
        assert len(lines) == 1
        assert "other" not in lines[0]

    def test_extractable_datasources_still_reported(self, patient_difficult_path, caplog):
        with caplog.at_level("INFO"):
            wrapper.extract_patient(patient_difficult_path)

        summary = _summary_lines(caplog)[0]
        assert "philips_waves" in summary
        assert "eit" in summary  # not found in Patient_difficult_format
