"""Unit tests for DisplayFallbacks — the carrier built from user_options (ADR-0005)."""

from dataclasses import FrozenInstanceError

import pytest

import clinical_scope.constants as cst
from clinical_scope.signal_container import DisplayFallbacks

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_bare_carrier_is_the_pre_settings_look(self):
        """Golden values: what the app rendered before any of this was settable."""
        fallbacks = DisplayFallbacks()
        assert fallbacks.subplot_height == 300
        assert fallbacks.loop_subplot_height == 600
        assert fallbacks.loops_per_row == 2
        assert fallbacks.legend_entry_width == 220
        assert fallbacks.y_significant_digits == 4
        assert fallbacks.colorway == "okabe_ito"
        assert fallbacks.template == "plotly"
        assert fallbacks.hovermode == "x unified"
        assert fallbacks.hover_time_format == "%H:%M:%S.%3f"

    def test_empty_user_options_gives_defaults(self):
        assert DisplayFallbacks.from_user_options({}) == DisplayFallbacks()

    def test_none_user_options_gives_defaults(self):
        assert DisplayFallbacks.from_user_options(None) == DisplayFallbacks()

    def test_is_frozen(self):
        """One carrier is shared by every Signal and PlotModel of a run — it must not be edited."""
        with pytest.raises(FrozenInstanceError):
            DisplayFallbacks().subplot_height = 1


# ---------------------------------------------------------------------------
# from_user_options
# ---------------------------------------------------------------------------


class TestFromUserOptions:
    def test_reads_every_display_tenant(self):
        fallbacks = DisplayFallbacks.from_user_options(
            {
                cst.UserOptions.DefaultSubplotHeight.NAME: 450,
                cst.UserOptions.LoopSubplotHeight.NAME: 700,
                cst.UserOptions.LoopsPerRow.NAME: 3,
                cst.UserOptions.LegendEntryWidth.NAME: 120,
                cst.UserOptions.YSignificantDigits.NAME: 6,
                cst.UserOptions.FallbackColorway.NAME: cst.Colorway.TOL_MUTED,
                cst.UserOptions.Template.NAME: cst.PlotTemplate.DARK,
                cst.UserOptions.HoverModeOption.NAME: cst.HoverMode.CLOSEST,
                cst.UserOptions.HoverTimeFormatOption.NAME: cst.HoverTimeFormat.DATE_TIME,
            }
        )
        assert fallbacks == DisplayFallbacks(
            subplot_height=450,
            loop_subplot_height=700,
            loops_per_row=3,
            legend_entry_width=120,
            y_significant_digits=6,
            colorway=cst.Colorway.TOL_MUTED,
            template=cst.PlotTemplate.DARK,
            hovermode=cst.HoverMode.CLOSEST,
            hover_time_format=cst.HoverTimeFormat.DATE_TIME,
        )

    def test_app_behaviour_tenants_are_ignored(self):
        """save_html_on_process is not a display fallback; it must not leak into the carrier."""
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.SaveHtmlOnProcess.NAME: True}
        )
        assert fallbacks == DisplayFallbacks()

    def test_height_clamped_to_schema_bounds(self):
        too_big = DisplayFallbacks.from_user_options(
            {cst.UserOptions.DefaultSubplotHeight.NAME: 99999}
        )
        too_small = DisplayFallbacks.from_user_options(
            {cst.UserOptions.DefaultSubplotHeight.NAME: 1}
        )
        assert too_big.subplot_height == 2000
        assert too_small.subplot_height == 100

    def test_unparseable_int_falls_back_to_default(self):
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.DefaultSubplotHeight.NAME: "tall"}
        )
        assert fallbacks.subplot_height == 300

    def test_none_int_falls_back_to_default(self):
        """A cleared number input arrives as None."""
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.LegendEntryWidth.NAME: None}
        )
        assert fallbacks.legend_entry_width == 220

    def test_discarded_value_is_logged(self, caplog):
        """The modal validates, so a bad value here means a hand-edited file — say so in the log."""
        with caplog.at_level("WARNING"):
            DisplayFallbacks.from_user_options(
                {
                    cst.UserOptions.DefaultSubplotHeight.NAME: "tall",
                    cst.UserOptions.FallbackColorway.NAME: "retired_palette",
                }
            )
        assert len(caplog.records) == 2

    def test_absent_key_is_not_logged(self, caplog):
        """Options predating a setting are the normal case, not something to warn about."""
        with caplog.at_level("WARNING"):
            DisplayFallbacks.from_user_options({})
        assert caplog.records == []

    def test_string_int_is_accepted(self):
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.DefaultSubplotHeight.NAME: "420"}
        )
        assert fallbacks.subplot_height == 420

    def test_unknown_choice_falls_back_to_default(self):
        """A value from an older options file must not reach the render layer."""
        fallbacks = DisplayFallbacks.from_user_options(
            {
                cst.UserOptions.FallbackColorway.NAME: "retired_palette",
                cst.UserOptions.HoverModeOption.NAME: "y unified",
                cst.UserOptions.LoopsPerRow.NAME: 12,
            }
        )
        assert fallbacks.colorway == "okabe_ito"
        assert fallbacks.hovermode == "x unified"
        assert fallbacks.loops_per_row == 2


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------


class TestDerivedValues:
    def test_colorway_palette_resolved(self):
        palette = DisplayFallbacks(colorway=cst.Colorway.OKABE_ITO).colorway_palette
        assert palette[0] == "#E69F00"
        assert len(palette) == 8

    def test_plotly_colorway_means_leave_alone(self):
        assert DisplayFallbacks(colorway=cst.Colorway.PLOTLY).colorway_palette is None

    def test_value_format_per_axis(self):
        fallbacks = DisplayFallbacks(y_significant_digits=3)
        assert fallbacks.value_format("y") == "%{y:.3g}"
        assert fallbacks.value_format("x") == "%{x:.3g}"

    def test_every_choice_maps_to_a_palette(self):
        for choice_value, _ in cst.Colorway.CHOICES:
            assert choice_value in cst.Colorway.PALETTES
