"""Unit tests for the user_options schema module — traversal and validation (ADR-0014)."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import clinical_scope.constants as cst
from clinical_scope import user_options
from clinical_scope.user_options import Correction, api_type, defaults, iter_fields, validate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(raw):
    """Validated dict only, for cases that do not care about the corrections."""
    return validate(raw)[0]


def _corrections(raw):
    """Corrections only, for cases that do not care about the cleaned values."""
    return validate(raw)[1]


def _by_name(corrections, name):
    return next(correction for correction in corrections if correction.name == name)


# ---------------------------------------------------------------------------
# Schema traversal
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_every_field_is_reachable(self):
        """A nested class the traversal misses would never get a widget or a default."""
        assert {field.NAME for field in iter_fields()} == {
            "save_html_on_process",
            "self_contained_html",
            "inspect_configured_columns_only",
            "display_timezone",
            "default_subplot_height",
            "loop_subplot_height",
            "loops_per_row",
            "legend_entry_width",
            "colorway",
            "plot_template",
            "hover_time_format",
            "hovermode",
            "y_significant_digits",
            "spectrogram_db_min",
            "spectrogram_db_max",
        }

    def test_defaults_are_the_pre_settings_look(self):
        """Golden values: what the app did before any of this was settable."""
        values = defaults()
        assert values["save_html_on_process"] is False
        assert values["default_subplot_height"] == 300
        assert values["loops_per_row"] == 2
        assert values["colorway"] == "okabe_ito"
        assert values["spectrogram_db_min"] == 0.0
        assert values["spectrogram_db_max"] == 40.0

    def test_api_type_of_a_known_field(self):
        assert api_type("default_subplot_height") == cst.ApiType.INT
        assert api_type("colorway") == cst.ApiType.CHOICE

    def test_api_type_of_an_unknown_field_is_none(self):
        """The widget helpers pass whatever id they were given; an unknown one must not raise."""
        assert api_type("retired_setting") is None


# ---------------------------------------------------------------------------
# validate — the quiet path
# ---------------------------------------------------------------------------


class TestValidateAcceptsGoodInput:
    def test_empty_input_gives_defaults_silently(self):
        """A settings file predating an option is the normal case, not something to report."""
        assert validate({}) == (defaults(), [])

    def test_none_input_gives_defaults_silently(self):
        assert validate(None) == (defaults(), [])

    def test_result_always_carries_every_field(self):
        assert set(_clean({"colorway": cst.Colorway.TOL_MUTED})) == set(defaults())

    def test_valid_values_are_kept(self):
        raw = {
            "default_subplot_height": 450,
            "loops_per_row": 3,
            "colorway": cst.Colorway.TOL_MUTED,
            "display_timezone": "America/New_York",
            "spectrogram_db_min": -20.0,
            "spectrogram_db_max": 60.0,
        }
        clean, corrections = validate(raw)
        assert corrections == []
        assert {key: clean[key] for key in raw} == raw

    def test_a_string_number_is_accepted(self):
        """A hand-edited file can quote its numbers; that is not a mistake worth reporting."""
        assert validate({"default_subplot_height": "420"}) == (
            {**defaults(), "default_subplot_height": 420},
            [],
        )

    def test_booleans_pass_through(self):
        assert _clean({"save_html_on_process": True})["save_html_on_process"] is True

    def test_unknown_keys_are_absent_from_the_result(self):
        """validate walks the schema, so a retired name cannot survive it."""
        assert "retired_setting" not in _clean({"retired_setting": 1})


# ---------------------------------------------------------------------------
# validate — numbers
# ---------------------------------------------------------------------------


class TestValidateNumbers:
    def test_int_above_max_is_clamped(self):
        clean, corrections = validate({"default_subplot_height": 99999})
        assert clean["default_subplot_height"] == 2000
        assert _by_name(corrections, "default_subplot_height").used == 2000

    def test_int_below_min_is_clamped(self):
        assert _clean({"default_subplot_height": 1})["default_subplot_height"] == 100

    def test_float_bounds_are_clamped(self):
        assert _clean({"spectrogram_db_min": -99999.0})["spectrogram_db_min"] == -100.0

    def test_unparseable_number_falls_back_to_default(self):
        clean, corrections = validate({"default_subplot_height": "tall"})
        assert clean["default_subplot_height"] == 300
        assert _by_name(corrections, "default_subplot_height").given == "tall"

    def test_cleared_number_input_falls_back_to_default(self):
        """A cleared Dash number input arrives as None."""
        assert _clean({"legend_entry_width": None})["legend_entry_width"] == 220

    def test_a_value_already_in_range_is_not_reported(self):
        assert _corrections({"default_subplot_height": 450}) == []


# ---------------------------------------------------------------------------
# validate — choices and timezone
# ---------------------------------------------------------------------------


class TestValidateChoices:
    def test_unknown_choice_falls_back_to_default(self):
        clean, corrections = validate({"colorway": "retired_palette"})
        assert clean["colorway"] == "okabe_ito"
        assert _by_name(corrections, "colorway").given == "retired_palette"

    def test_choice_outside_the_set_falls_back_to_default(self):
        assert _clean({"loops_per_row": 12})["loops_per_row"] == 2

    def test_invalid_timezone_falls_back_to_default(self):
        clean, corrections = validate({"display_timezone": "NotATimezone"})
        assert clean["display_timezone"] == cst.DISPLAY_TIMEZONE
        assert _by_name(corrections, "display_timezone").used == cst.DISPLAY_TIMEZONE

    def test_valid_timezone_is_kept_silently(self):
        assert validate({"display_timezone": "Asia/Tokyo"}) == (
            {**defaults(), "display_timezone": "Asia/Tokyo"},
            [],
        )

    def test_cleared_timezone_falls_back_to_default(self):
        assert _clean({"display_timezone": ""})["display_timezone"] == cst.DISPLAY_TIMEZONE


# ---------------------------------------------------------------------------
# validate — the cross-field spectrogram rule
# ---------------------------------------------------------------------------


class TestSpectrogramRange:
    def test_inverted_pair_resets_both_bounds(self):
        """Each bound is inside its own MIN/MAX, yet the pair reaches Plotly as zmin > zmax."""
        clean, corrections = validate({"spectrogram_db_min": 100.0, "spectrogram_db_max": 40.0})
        assert (clean["spectrogram_db_min"], clean["spectrogram_db_max"]) == (0.0, 40.0)
        assert _by_name(corrections, "spectrogram_db_min").used == (0.0, 40.0)

    def test_equal_bounds_reset_both(self):
        clean = _clean({"spectrogram_db_min": 20.0, "spectrogram_db_max": 20.0})
        assert (clean["spectrogram_db_min"], clean["spectrogram_db_max"]) == (0.0, 40.0)

    def test_out_of_range_bounds_are_clamped_then_ordered(self):
        """Clamping each bound on its own still leaves the pair inverted — two corrections."""
        clean, corrections = validate(
            {"spectrogram_db_min": 99999.0, "spectrogram_db_max": -99999.0}
        )
        assert (clean["spectrogram_db_min"], clean["spectrogram_db_max"]) == (0.0, 40.0)
        assert len(corrections) == 3

    def test_one_bound_alone_is_ordered_against_the_default_of_the_other(self):
        clean = _clean({"spectrogram_db_max": -10.0})
        assert (clean["spectrogram_db_min"], clean["spectrogram_db_max"]) == (0.0, 40.0)


# ---------------------------------------------------------------------------
# Correction
# ---------------------------------------------------------------------------


class TestCorrection:
    def test_message_names_the_option_and_both_values(self):
        """Only the loader renders this; the modal reacts to the object, not the prose."""
        message = Correction("colorway", "retired", "okabe_ito", "is not one of []").message
        assert "colorway" in message
        assert "retired" in message
        assert "okabe_ito" in message

    def test_is_frozen(self):
        """Corrections travel to a caller that only reads them; none may edit one in place."""
        with pytest.raises(FrozenInstanceError):
            _corrections({"colorway": "retired_palette"})[0].used = "anything"


# ---------------------------------------------------------------------------
# Purity — the reason this module is not in dash_api
# ---------------------------------------------------------------------------


def test_module_never_touches_the_home_directory():
    """
    The core must stay unable to read ``~/.clinical_scope/user_options.json`` (ADR-0014):
    an ``extract_*`` run may not depend on who is at the keyboard. Disk I/O is helper_api's.
    """
    source = Path(user_options.__file__).read_text()
    assert "Path.home" not in source
    assert "open(" not in source
