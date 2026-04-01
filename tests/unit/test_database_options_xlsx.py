"""Tests for database_options_xlsx converter."""

import io
from pathlib import Path

import openpyxl
import pytest

from clinical_data_visualizer.database_options_parser import (
    validate_database_options_structure,
)
from clinical_data_visualizer.database_options_xlsx import xlsx_bytes_to_database_options

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_xlsx(signals_rows: list[list], loops_rows: list[list] | None = None) -> bytes:
    """
    Build a minimal XLSX bytes object with a ``signals`` sheet and optional ``loops`` sheet.

    *signals_rows* must include the header as the first element.
    *loops_rows* must include the header as the first element (if provided).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "signals"
    for row in signals_rows:
        ws.append(row)

    if loops_rows is not None:
        ws_loops = wb.create_sheet("loops")
        for row in loops_rows:
            ws_loops.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SIGNALS_HEADER = [
    "datasource",
    "signal",
    "label",
    "unit",
    "unit_conversion",
    "range_min",
    "range_max",
    "priority",
    "color",
    "visible",
    "line_dash",
    "period_resampling",
    "display",
    "groups",
]

LOOPS_HEADER = ["datasource", "loop_name", "x_signal", "y_signal"]


# ---------------------------------------------------------------------------
# Tests: basic signal parsing
# ---------------------------------------------------------------------------


class TestBasicSignalParsing:
    def test_single_signal_minimal(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "ds_a" in result
        assert "SIG1" in result["ds_a"]["signals"]

    def test_signal_label_included_when_different_from_name(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "My label", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_a"]["signals"]["SIG1"]["label"] == "My label"

    def test_signal_label_omitted_when_equal_to_name(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "SIG1", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "label" not in result["ds_a"]["signals"]["SIG1"]

    def test_unit_and_unit_conversion(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "mmHg", "1.35951", "", "", "", "", "", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["unit"] == "mmHg"
        assert sig["unit_conversion"] == pytest.approx(1.35951)

    def test_range_both_bounds(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "-5", "25", "", "", "", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["range"] == [-5.0, 25.0]

    def test_range_only_min(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "-5", "", "", "", "", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["range"] == [-5.0, None]

    def test_range_absent_when_empty(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert "range" not in sig

    def test_color_priority_line_dash(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "2", "red", "", "dash", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["color"] == "red"
        assert sig["priority"] == pytest.approx(2.0)
        assert sig["line_dash"] == "dash"

    def test_period_resampling_on_signal(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "0.8", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["period_resampling"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Tests: display column → field_display
# ---------------------------------------------------------------------------


class TestDisplayColumn:
    def test_empty_display_means_visible(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "SIG1" in result["ds_a"]["field_display"]

    def test_display_yes_explicit(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "yes", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "SIG1" in result["ds_a"]["field_display"]

    def test_display_no_excludes_from_field_display(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "no", ""],
                ["ds_a", "SIG2", "", "", "", "", "", "", "", "", "", "", "yes", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "SIG1" not in result["ds_a"]["field_display"]
        assert "SIG2" in result["ds_a"]["field_display"]

    def test_display_zero_excludes(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "0", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "SIG1" not in result["ds_a"].get("field_display", [])


# ---------------------------------------------------------------------------
# Tests: visible column
# ---------------------------------------------------------------------------


class TestVisibleColumn:
    def test_empty_visible_not_added_to_sig_opts(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert "visible" not in sig

    def test_visible_no_adds_false(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "no", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert sig["visible"] is False

    def test_visible_yes_not_added(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "yes", "", "", "", ""],
            ]
        )
        sig = xlsx_bytes_to_database_options(data)["ds_a"]["signals"]["SIG1"]
        assert "visible" not in sig


# ---------------------------------------------------------------------------
# Tests: sentinel row (*) → numerics
# ---------------------------------------------------------------------------


class TestSentinelRow:
    def test_sentinel_creates_numerics(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "*", "", "", "", "", "", "2.5", "", "", "", "0.2", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_a"]["numerics"] == {"priority": 2.5, "period_resampling": 0.2}

    def test_sentinel_partial_numerics(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "*", "", "", "", "", "", "3", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_a"]["numerics"] == {"priority": 3.0}

    def test_sentinel_not_added_to_signals(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "*", "", "", "", "", "", "1", "", "", "", "0.5", "", ""],
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "*" not in result["ds_a"].get("signals", {})

    def test_sentinel_not_added_to_field_display(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "*", "", "", "", "", "", "1", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "*" not in result["ds_a"].get("field_display", [])


# ---------------------------------------------------------------------------
# Tests: group scope resolution
# ---------------------------------------------------------------------------


class TestGroupResolution:
    def test_local_group_single_datasource(self):
        """Signals from one datasource → datasource grouped_fields."""
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", "MyGroup"],
                ["ds_a", "S2", "", "", "", "", "", "", "", "", "", "", "", "MyGroup"],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "grouped_fields" in result["ds_a"]
        assert result["ds_a"]["grouped_fields"]["MyGroup"] == ["S1", "S2"]
        assert "global" not in result

    def test_global_group_multiple_datasources(self):
        """Same group name across datasources → global.grouped_fields."""
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", "SharedGroup"],
                ["ds_b", "S2", "", "", "", "", "", "", "", "", "", "", "", "SharedGroup"],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "global" in result
        assert result["global"]["grouped_fields"]["SharedGroup"] == ["S1", "S2"]
        assert "grouped_fields" not in result["ds_a"]
        assert "grouped_fields" not in result["ds_b"]

    def test_mixed_local_and_global_groups(self):
        """One global group, one local group — both resolved independently."""
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", "Global; Local"],
                ["ds_b", "S2", "", "", "", "", "", "", "", "", "", "", "", "Global"],
                ["ds_a", "S3", "", "", "", "", "", "", "", "", "", "", "", "Local"],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        # "Global" spans ds_a and ds_b → global
        assert result["global"]["grouped_fields"]["Global"] == ["S1", "S2"]
        # "Local" only in ds_a → local
        assert result["ds_a"]["grouped_fields"]["Local"] == ["S1", "S3"]

    def test_multiple_groups_semicolon_separated(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", "G1; G2"],
                ["ds_a", "S2", "", "", "", "", "", "", "", "", "", "", "", "G2"],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_a"]["grouped_fields"]["G1"] == ["S1"]
        assert result["ds_a"]["grouped_fields"]["G2"] == ["S1", "S2"]


# ---------------------------------------------------------------------------
# Tests: loops sheet
# ---------------------------------------------------------------------------


class TestLoopsSheet:
    def test_loop_parsed(self):
        data = _build_xlsx(
            [SIGNALS_HEADER, ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", ""]],
            loops_rows=[LOOPS_HEADER, ["ds_a", "pv_loop", "Paw", "Vol"]],
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_a"]["loop"] == {"pv_loop": ["Paw", "Vol"]}

    def test_no_loops_sheet(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert "loop" not in result["ds_a"]

    def test_loop_for_unknown_datasource_creates_entry(self):
        """A loop row whose datasource doesn't appear in signals still creates an entry."""
        data = _build_xlsx(
            [SIGNALS_HEADER, ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", ""]],
            loops_rows=[LOOPS_HEADER, ["ds_b", "loop1", "X", "Y"]],
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["ds_b"]["loop"] == {"loop1": ["X", "Y"]}

    def test_global_loop_datasource_sentinel(self):
        """datasource='global' routes loop into result['global']['loop']."""
        data = _build_xlsx(
            [SIGNALS_HEADER, ["ds_a", "S1", "", "", "", "", "", "", "", "", "", "", "", ""]],
            loops_rows=[LOOPS_HEADER, ["global", "cross_pv", "ds_a::Paw", "ds_b::Vol"]],
        )
        result = xlsx_bytes_to_database_options(data)
        assert result["global"]["loop"] == {"cross_pv": ["ds_a::Paw", "ds_b::Vol"]}

    def test_global_loop_coexists_with_global_grouped_fields(self):
        """global.loop and global.grouped_fields can coexist under the same 'global' key."""
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["ds_a", "Paw", "", "", "", "", "", "", "", "", "", "", "", "MyGroup"],
                ["ds_b", "Vol", "", "", "", "", "", "", "", "", "", "", "", "MyGroup"],
            ],
            loops_rows=[LOOPS_HEADER, ["global", "pv", "ds_a::Paw", "ds_b::Vol"]],
        )
        result = xlsx_bytes_to_database_options(data)
        assert "grouped_fields" in result["global"]
        assert "loop" in result["global"]


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_signals_sheet_raises(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "other"
        buf = io.BytesIO()
        wb.save(buf)
        with pytest.raises(ValueError, match="signals"):
            xlsx_bytes_to_database_options(buf.getvalue())

    def test_missing_required_columns_raises(self):
        data = _build_xlsx([["only_col"], ["val"]])
        with pytest.raises(ValueError, match="missing required columns"):
            xlsx_bytes_to_database_options(data)

    def test_empty_rows_ignored(self):
        data = _build_xlsx(
            [
                SIGNALS_HEADER,
                ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
                ["ds_a", "SIG1", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )
        result = xlsx_bytes_to_database_options(data)
        assert list(result.keys()) == ["ds_a"]


# ---------------------------------------------------------------------------
# Tests: round-trip with example file
# ---------------------------------------------------------------------------


class TestExampleFileRoundTrip:
    """Smoke test against the shipped example XLSX."""

    def test_example_xlsx_parses_without_error(self):

        example = Path("example/option_files/example_database_options.xlsx")
        if not example.exists():
            pytest.skip("Example XLSX not found")
        data = example.read_bytes()
        result = xlsx_bytes_to_database_options(data)
        assert "philips_waves" in result
        assert "eit" in result
        assert "global" in result

    def test_example_passes_validation(self):

        example = Path("example/option_files/example_database_options.xlsx")
        if not example.exists():
            pytest.skip("Example XLSX not found")
        result = xlsx_bytes_to_database_options(example.read_bytes())
        warnings = validate_database_options_structure(result)
        assert warnings == []
