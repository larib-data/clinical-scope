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
        assert fallbacks.display_timezone == cst.DISPLAY_TIMEZONE

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
    """A projection, not a check — validation is tested in test_user_options.py."""

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
                cst.UserOptions.DisplayTimezone.NAME: "America/New_York",
                cst.UserOptions.SpectrogramDbMin.NAME: -20.0,
                cst.UserOptions.SpectrogramDbMax.NAME: 60.0,
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
            display_timezone="America/New_York",
            spectrogram_db_range=(-20.0, 60.0),
        )

    def test_a_missing_tenant_keeps_its_default(self):
        """Options predating a setting are the normal case, not something to warn about."""
        fallbacks = DisplayFallbacks.from_user_options({cst.UserOptions.LoopsPerRow.NAME: 3})
        assert fallbacks == DisplayFallbacks(loops_per_row=3)

    def test_invalid_display_timezone_falls_back_to_default(self):
        """
        The one tenant still resolved here: a bad IANA name raises inside pandas/zoneinfo,
        so a dict hand-built by a library caller must not carry it into the render layer.
        """
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.DisplayTimezone.NAME: "NotATimezone"}
        )
        assert fallbacks.display_timezone == cst.DISPLAY_TIMEZONE

    def test_app_behaviour_tenants_are_ignored(self):
        """save_html_on_process is not a display fallback; it must not leak into the carrier."""
        fallbacks = DisplayFallbacks.from_user_options(
            {cst.UserOptions.SaveHtmlOnProcess.NAME: True}
        )
        assert fallbacks == DisplayFallbacks()


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
