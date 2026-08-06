"""Tests for the schema-driven widget factory — CHOICE widgets and SECTION headers."""

from dash import dcc, html

import clinical_scope.constants as cst
from clinical_scope.dash_api import ui_components
from clinical_scope.dash_api.helper_api import iter_user_option_fields
from clinical_scope.dash_api.ui_components import (
    build_ui_and_schema_registry,
    dash_widget_factory,
    from_widget_value,
    to_widget_value,
)
from clinical_scope.dash_api.validation import validate_value

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _widgets(container):
    """Flatten a built form to (component_id, component) pairs, skipping section headers."""
    found = []

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif hasattr(node, "id") and isinstance(node.id, dict):
            found.append((node.id["name"], node))
        elif hasattr(node, "children"):
            visit(node.children)

    visit(container.children)
    return found


def _section_headers(container):
    return [
        child.children
        for child in container.children
        if isinstance(child, html.Div) and isinstance(child.children, str)
    ]


class _Choice:
    """Stand-in schema class: the factory only ever sees these attributes."""

    ORDER = 1
    NAME = "flavour"
    API_TYPE = cst.ApiType.CHOICE
    DEFAULT = "vanilla"
    MANDATORY = False
    CHOICES = (("vanilla", "Vanilla"), ("pistachio", "Pistachio"))
    DESCRIPTION = "Flavour"


# ---------------------------------------------------------------------------
# ApiType.CHOICE
# ---------------------------------------------------------------------------


class TestChoiceWidget:
    def test_renders_a_dropdown(self):
        container = dash_widget_factory(_Choice, "prefix", "user-option")
        _label, widget = container.children
        assert isinstance(widget, dcc.Dropdown)

    def test_options_come_from_the_schema(self):
        _label, widget = dash_widget_factory(_Choice, "prefix", "user-option").children
        assert widget.options == [
            {"label": "Vanilla", "value": "vanilla"},
            {"label": "Pistachio", "value": "pistachio"},
        ]

    def test_default_is_preselected_and_not_clearable(self):
        _label, widget = dash_widget_factory(_Choice, "prefix", "user-option").children
        assert widget.value == "vanilla"
        assert widget.clearable is False

    def test_widget_id_is_pattern_matching(self):
        _label, widget = dash_widget_factory(_Choice, "prefix", "user-option").children
        assert widget.id == {"type": "user-option", "name": "prefix.flavour"}

    def test_value_round_trips_unchanged(self):
        encoded = to_widget_value(cst.ApiType.CHOICE, "pistachio")
        assert encoded == "pistachio"
        assert from_widget_value(cst.ApiType.CHOICE, encoded) == "pistachio"

    def test_int_choice_round_trips_as_int(self):
        """loops_per_row and y_significant_digits store ints, not strings."""
        assert from_widget_value(cst.ApiType.CHOICE, to_widget_value(cst.ApiType.CHOICE, 3)) == 3


# ---------------------------------------------------------------------------
# SECTION headers
# ---------------------------------------------------------------------------


class TestSectionHeaders:
    def test_user_options_form_shows_both_sections(self):
        container, _ = build_ui_and_schema_registry(
            cst.UserOptions, "user_options", id_type="user-option"
        )
        assert _section_headers(container) == [
            cst.UserOptionSection.APP_BEHAVIOR,
            cst.UserOptionSection.PLOT_DEFAULTS,
        ]

    def test_header_is_emitted_once_per_section(self):
        container, _ = build_ui_and_schema_registry(
            cst.UserOptions, "user_options", id_type="user-option"
        )
        headers = _section_headers(container)
        assert len(headers) == len(set(headers))

    def test_patient_options_form_has_no_headers(self):
        """Schema classes without SECTION render exactly as before."""
        container, _ = build_ui_and_schema_registry(cst.PatientOptions, "global")
        assert _section_headers(container) == []

    def test_every_user_option_still_gets_a_widget(self):
        container, _ = build_ui_and_schema_registry(
            cst.UserOptions, "user_options", id_type="user-option"
        )
        built = {component_id for component_id, _ in _widgets(container)}
        assert built == {f"user_options.{field.NAME}" for field in iter_user_option_fields()}

    def test_every_declared_section_is_ranked(self):
        """A section missing from SECTION_ORDER would silently sort to the top."""
        declared = {getattr(schema, "SECTION", None) for schema in iter_user_option_fields()}
        assert declared <= set(cst.UserOptions.SECTION_ORDER)


# ---------------------------------------------------------------------------
# CHOICE validation (shared with the patient-options form)
# ---------------------------------------------------------------------------


class TestChoiceValidation:
    def test_value_from_the_set_is_valid(self):
        is_valid, message = validate_value(_Choice, "pistachio")
        assert is_valid
        assert message == ""

    def test_value_outside_the_set_is_rejected(self):
        is_valid, message = validate_value(_Choice, "durian")
        assert not is_valid
        assert "must be one of" in message


# ---------------------------------------------------------------------------
# Save-HTML indicator (unchanged contract, guarded while the modal grew)
# ---------------------------------------------------------------------------


class TestSaveHtmlIndicator:
    def test_on_and_off(self):
        assert ui_components.save_html_indicator_text(True).endswith("on")
        assert ui_components.save_html_indicator_text(False).endswith("off")


# ---------------------------------------------------------------------------
# Paired TIMESTAMP fields (datetime_start / datetime_end)
# ---------------------------------------------------------------------------


class TestTimestampPairLayout:
    def test_without_extras_renders_as_one_side_by_side_row(self):
        """Regression guard: the compact row is unchanged when nothing is attached to it."""
        container, _ = build_ui_and_schema_registry(cst.PatientOptions, "global")
        row = next(
            child
            for child in container.children
            if isinstance(child, html.Div) and child.style.get("gap") == "24px"
        )
        assert len(row.children) == 2  # just the two widgets, nothing else on the row
        assert [component_id for component_id, _ in _widgets(row)] == [
            "global.datetime_start",
            "global.datetime_end",
        ]

    def test_extras_split_the_pair_onto_separate_lines(self):
        """
        An extra on datetime_start/end used to trail after both boxes on one flex row,
        wrapping to two lines on a narrow viewport. Each field now gets its own line
        instead, so its extra sits directly beside it.
        """
        start_extra = html.Span("start-extra")
        end_extra = html.Span("end-extra")
        container, _ = build_ui_and_schema_registry(
            cst.PatientOptions,
            "global",
            extra_per_field={
                "global.datetime_start": [start_extra],
                "global.datetime_end": [end_extra],
            },
        )
        start_line = next(
            child
            for child in container.children
            if isinstance(child, html.Div) and start_extra in getattr(child, "children", [])
        )
        end_line = next(
            child
            for child in container.children
            if isinstance(child, html.Div) and end_extra in getattr(child, "children", [])
        )
        assert start_line is not end_line
