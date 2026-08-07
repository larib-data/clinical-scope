"""Tests for the user-options callbacks and their on-disk round-trip."""

import json

import pytest
from dash import no_update

import clinical_scope.constants as cst
from clinical_scope.dash_api import helper_api as ui_helper
from clinical_scope.dash_api.callbacks.user_options_callbacks import (
    persist_user_options,
    reflect_user_options,
)
from clinical_scope.signal_container import DisplayFallbacks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _widget_id(name):
    return {"type": "user-option", "name": f"user_options.{name}"}


@pytest.fixture
def user_options_home(tmp_path, monkeypatch):
    """Redirect ~/.clinical_scope to a temp folder so the real file is never touched."""
    monkeypatch.setattr(ui_helper.Path, "home", lambda: tmp_path)
    return tmp_path / cst.CLINICAL_SCOPE_DIR_NAME / cst.USER_OPTIONS_FILE_NAME


# ---------------------------------------------------------------------------
# Coercion: a value is held to its schema on the way into the store
# ---------------------------------------------------------------------------


class TestValueCoercionOnSave:
    @staticmethod
    def _saved(name, widget_value):
        """Save one widget's value and return what landed in the store."""
        return persist_user_options([widget_value], [_widget_id(name)], {})[name]

    def test_int_clamped_to_bounds(self, user_options_home):
        name = cst.UserOptions.DefaultSubplotHeight.NAME
        assert self._saved(name, 99999) == 2000
        assert self._saved(name, 1) == 100

    def test_cleared_int_input_falls_back_to_default(self, user_options_home):
        assert self._saved(cst.UserOptions.LegendEntryWidth.NAME, None) == 220

    def test_choice_outside_the_set_falls_back_to_default(self, user_options_home):
        name = cst.UserOptions.FallbackColorway.NAME
        assert self._saved(name, "retired_palette") == "okabe_ito"

    def test_valid_choice_kept(self, user_options_home):
        name = cst.UserOptions.HoverModeOption.NAME
        assert self._saved(name, cst.HoverMode.CLOSEST) == "closest"

    def test_invalid_timezone_falls_back_to_default(self, user_options_home):
        name = cst.UserOptions.DisplayTimezone.NAME
        assert self._saved(name, "NotATimezone") == cst.DISPLAY_TIMEZONE

    def test_valid_timezone_kept(self, user_options_home):
        name = cst.UserOptions.DisplayTimezone.NAME
        assert self._saved(name, "Asia/Tokyo") == "Asia/Tokyo"

    def test_invalid_value_still_forces_a_widget_resync_when_it_falls_back_to_the_stored_value(
        self, user_options_home
    ):
        """
        Regression: an invalid entry can coerce back to the value the store already holds,
        so ``updated == store`` alone must not read as "nothing changed" and skip the resync.
        """
        name = cst.UserOptions.DisplayTimezone.NAME
        store = {name: cst.DISPLAY_TIMEZONE}
        result = persist_user_options(["NotATimezone"], [_widget_id(name)], store)
        assert result is not no_update
        assert result[name] == cst.DISPLAY_TIMEZONE

    def test_checklist_is_stored_as_a_bool(self, user_options_home):
        assert self._saved(cst.UserOptions.SaveHtmlOnProcess.NAME, [True]) is True
        assert self._saved(cst.UserOptions.SaveHtmlOnProcess.NAME, []) is False


# ---------------------------------------------------------------------------
# persist_user_options
# ---------------------------------------------------------------------------


class TestPersistUserOptions:
    def test_writes_every_widget_to_the_store(self, user_options_home):
        names = [
            cst.UserOptions.SaveHtmlOnProcess.NAME,
            cst.UserOptions.FallbackColorway.NAME,
            cst.UserOptions.LoopsPerRow.NAME,
        ]
        values = [[True], cst.Colorway.TOL_MUTED, 3]

        store = persist_user_options(values, [_widget_id(name) for name in names], {})

        assert store == {
            cst.UserOptions.SaveHtmlOnProcess.NAME: True,
            cst.UserOptions.FallbackColorway.NAME: cst.Colorway.TOL_MUTED,
            cst.UserOptions.LoopsPerRow.NAME: 3,
        }

    def test_persists_to_disk(self, user_options_home):
        name = cst.UserOptions.Template.NAME
        persist_user_options([cst.PlotTemplate.DARK], [_widget_id(name)], {})

        assert json.loads(user_options_home.read_text())[name] == cst.PlotTemplate.DARK


# ---------------------------------------------------------------------------
# reflect_user_options
# ---------------------------------------------------------------------------


class TestReflectUserOptions:
    def test_store_values_reach_the_widgets(self):
        names = [cst.UserOptions.SaveHtmlOnProcess.NAME, cst.UserOptions.HoverModeOption.NAME]
        store = {names[0]: True, names[1]: cst.HoverMode.CLOSEST}

        values, save_html_indicator, pruning_indicator = reflect_user_options(
            store, [_widget_id(name) for name in names]
        )

        assert values == [[True], cst.HoverMode.CLOSEST]
        assert save_html_indicator.endswith("on")
        # Absent from the store -> schema default (False) -> "off", same rule as save-html.
        assert pruning_indicator.endswith("off")

    def test_missing_key_shows_the_schema_default(self):
        """An options file written before a setting existed must not blank its widget."""
        name = cst.UserOptions.FallbackColorway.NAME
        values, _, _ = reflect_user_options({}, [_widget_id(name)])
        assert values == ["okabe_ito"]

    def test_pruning_indicator_reflects_the_store(self):
        name = cst.UserOptions.InspectConfiguredColumnsOnly.NAME
        _, _, pruning_indicator = reflect_user_options({name: True}, [_widget_id(name)])
        assert pruning_indicator.endswith("on")


# ---------------------------------------------------------------------------
# Persistence round-trip: saved settings apply on the next Visualize
# ---------------------------------------------------------------------------


class TestUserOptionsRoundTrip:
    def test_defaults_cover_every_schema_field(self):
        defaults = ui_helper.user_options_defaults()
        assert set(defaults) == {field.NAME for field in ui_helper.iter_user_option_fields()}

    def test_saved_options_reload_and_reach_the_carrier(self, user_options_home):
        persist_user_options(
            [cst.Colorway.TOL_MUTED, 3],
            [
                _widget_id(cst.UserOptions.FallbackColorway.NAME),
                _widget_id(cst.UserOptions.LoopsPerRow.NAME),
            ],
            {},
        )

        reloaded = ui_helper.load_user_options()
        fallbacks = DisplayFallbacks.from_user_options(reloaded)

        assert fallbacks.colorway == cst.Colorway.TOL_MUTED
        assert fallbacks.loops_per_row == 3
        # Untouched settings still come from the schema defaults.
        assert fallbacks.subplot_height == 300

    def test_unknown_keys_from_an_older_file_are_dropped(self, user_options_home):
        user_options_home.parent.mkdir(parents=True, exist_ok=True)
        user_options_home.write_text(json.dumps({"retired_setting": 1}))

        assert "retired_setting" not in ui_helper.load_user_options()
