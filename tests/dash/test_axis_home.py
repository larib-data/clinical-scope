"""Tests for axis_home.py — the reset-axes healing helpers, no browser."""

import json
from datetime import datetime

import numpy as np
import plotly.graph_objects as go
import plotly.utils
import pytest
from dash import Patch
from plotly.subplots import make_subplots
from plotly_resampler import FigureResampler

from clinical_scope.dash_api import axis_home
from tests.dash.helpers import patch_ops

# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def _two_axis_figure() -> go.Figure:
    """Two stacked subplots, the way PlotModel.to_figure builds them."""
    fig = make_subplots(rows=2, cols=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[3, 4]), row=1, col=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[5, 6]), row=2, col=1)
    return fig


def _through_the_store(store: dict) -> dict:
    """The store as the callback receives it — dash serializes it to JSON and back."""
    return json.loads(json.dumps(store, cls=plotly.utils.PlotlyJSONEncoder))


class TestCapture:
    def test_autorange_axes_store_none(self):
        store = axis_home.capture(_two_axis_figure())

        assert store["axes"] == {
            "xaxis": None,
            "xaxis2": None,
            "yaxis": None,
            "yaxis2": None,
        }

    def test_explicit_range_is_kept(self):
        fig = _two_axis_figure()
        fig.update_xaxes(range=[0, 10], row=1, col=1)
        fig.update_yaxes(range=[-1, 1], row=2, col=1)

        store = axis_home.capture(fig)

        assert store["axes"]["xaxis"] == [0, 10]
        assert store["axes"]["yaxis2"] == [-1, 1]
        assert store["axes"]["xaxis2"] is None

    def test_matched_axes_are_recorded_against_their_master(self):
        fig = _two_axis_figure()
        fig.update_xaxes(matches="x", row=2, col=1)

        assert axis_home.capture(fig)["matched"] == {"xaxis2": "xaxis"}

    def test_unmatched_axes_are_not_recorded(self):
        assert axis_home.capture(_two_axis_figure())["matched"] == {}

    def test_axis_absent_from_the_layout_is_omitted(self):
        # Nothing states its range, so the reset path's autorange fallback covers it.
        fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))

        assert axis_home.capture(fig)["axes"] == {}

    def test_non_axis_layout_keys_are_ignored(self):
        fig = _two_axis_figure()
        fig.update_layout(title_text="hello", hovermode="x unified")

        assert set(axis_home.capture(fig)["axes"]) == {"xaxis", "xaxis2", "yaxis", "yaxis2"}


# ---------------------------------------------------------------------------
# rehome — telling a stale reset apart from every other relayout
# ---------------------------------------------------------------------------


class TestRehomeIgnoresEverythingButAReset:
    """Only an unsplit <axis>.range is plotly replaying a stored initial view."""

    def test_zoom_passes_through(self):
        relayout = {"xaxis.range[0]": 10.0, "xaxis.range[1]": 20.0}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_pan_passes_through(self):
        relayout = {
            "xaxis.range[0]": 10.0,
            "xaxis.range[1]": 20.0,
            "yaxis.range[0]": 1.0,
            "yaxis.range[1]": 2.0,
        }

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_autoscale_passes_through(self):
        relayout = {"xaxis.autorange": True}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_healthy_reset_passes_through(self):
        # plotly replays autorange as autorange; there is no stale range to overrule.
        relayout = {"xaxis.autorange": True, "xaxis.showspikes": False}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_spike_lines_toggle_passes_through(self):
        # The modebar's Toggle Spike Lines emits showspikes for every axis and no view
        # key at all; keying on that marker used to yank a configured range home.
        relayout = {"xaxis.showspikes": True, "yaxis.showspikes": True}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": [0.0, 10.0]}}) == (relayout, [])

    def test_dragmode_change_passes_through(self):
        relayout = {"dragmode": "pan"}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_shape_drag_passes_through(self):
        relayout = {"shapes[0].x0": 5.0, "shapes[0].x1": 7.0}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": None}}) == (relayout, [])

    def test_reset_already_on_a_configured_home_passes_through(self):
        relayout = {"xaxis.range": [0.5, 30.0], "xaxis.showspikes": False}

        assert axis_home.rehome(relayout, {"axes": {"xaxis": [0.5, 30.0]}}) == (relayout, [])


class TestRehomeCatchesAStaleReset:
    def test_modebar_reset_is_caught(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        healed, off_home = axis_home.rehome(relayout, {"axes": {"xaxis": None}})

        assert off_home == ["xaxis"]
        assert healed == {"xaxis.showspikes": False, "xaxis.autorange": True}

    def test_double_click_reset_is_caught(self):
        # A double-click reset replays the same stale reference but carries no
        # showspikes companion, so the old marker missed it entirely.
        relayout = {"xaxis.range": [100.0, 200.0], "yaxis.range": [3.0, 4.0]}

        healed, off_home = axis_home.rehome(relayout, {"axes": {"xaxis": None, "yaxis": None}})

        assert off_home == ["xaxis", "yaxis"]
        assert healed == {
            "xaxis.autorange": True,
            "xaxis.showspikes": False,
            "yaxis.autorange": True,
            "yaxis.showspikes": False,
        }

    def test_configured_range_is_restored(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        healed, off_home = axis_home.rehome(relayout, {"axes": {"xaxis": [0.0, 10.0]}})

        assert off_home == ["xaxis"]
        assert healed["xaxis.range[0]"] == 0.0
        assert healed["xaxis.range[1]"] == 10.0
        assert "xaxis.range" not in healed

    def test_wrong_range_where_home_is_a_range_is_caught(self):
        relayout = {"xaxis.range": [2.0, 5.0], "xaxis.showspikes": False}

        _, off_home = axis_home.rehome(relayout, {"axes": {"xaxis": [0.5, 30.0]}})

        assert off_home == ["xaxis"]

    def test_unknown_axis_falls_back_to_autorange(self):
        healed, off_home = axis_home.rehome({"xaxis9.range": [1.0, 2.0]}, {})

        assert off_home == ["xaxis9"]
        assert healed["xaxis9.autorange"] is True

    def test_keys_of_other_axes_survive(self):
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis.showspikes": False,
            "hovermode": "x unified",
        }

        healed, _ = axis_home.rehome(relayout, {"axes": {"xaxis": None}})

        assert healed["xaxis.showspikes"] is False
        assert healed["hovermode"] == "x unified"

    def test_input_is_not_mutated(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        axis_home.rehome(relayout, {"axes": {"xaxis": None}})

        assert relayout == {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

    def test_partial_reset_carrying_autorange_too_is_healed(self):
        # plotly writes both keys when only one bound had an initial value.
        relayout = {"xaxis.range": [None, 200.0], "xaxis.autorange": "min"}

        healed, off_home = axis_home.rehome(relayout, {"axes": {"xaxis": None}})

        assert off_home == ["xaxis"]
        assert healed == {"xaxis.autorange": True, "xaxis.showspikes": False}


# ---------------------------------------------------------------------------
# rehome — matches-constrained axes
# ---------------------------------------------------------------------------


class TestRehomeAndMatchedAxes:
    def test_matched_axes_are_never_corrected_directly(self):
        # A matched axis goes through plotly's constraint solver, so a range written to
        # it does not move it.
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis2.range": [100.0, 200.0],
        }
        store = {"axes": {"xaxis": None, "xaxis2": None}, "matched": {"xaxis2": "xaxis"}}

        _, off_home = axis_home.rehome(relayout, store)

        assert off_home == ["xaxis"]

    def test_matched_axis_is_still_healed_for_the_resampler(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis2.range": [100.0, 200.0]}
        store = {"axes": {"xaxis": [0.0, 10.0], "xaxis2": None}, "matched": {"xaxis2": "xaxis"}}

        healed, _ = axis_home.rehome(relayout, store)

        assert healed["xaxis2.range[0]"] == 0.0
        assert healed["xaxis2.range[1]"] == 10.0

    def test_a_reset_all_of_whose_off_home_axes_are_matched_does_nothing(self):
        relayout = {"xaxis2.range": [100.0, 200.0]}
        store = {"axes": {"xaxis": None, "xaxis2": None}, "matched": {"xaxis2": "xaxis"}}

        assert axis_home.rehome(relayout, store) == (relayout, [])


# ---------------------------------------------------------------------------
# rehome — date ranges, which change representation on the way to the browser
# ---------------------------------------------------------------------------


class TestRehomeWithDateRanges:
    def test_a_healthy_reset_survives_the_store_round_trip(self):
        # The store holds a datetime that JSON-encodes to '2004-09-15T08:12:33', while
        # plotly sends the same instant space-separated. Comparing them as raw text
        # reports every reset off-home and defeats the pass-through.
        fig = _two_axis_figure()
        fig.update_xaxes(
            range=[datetime(2004, 9, 15, 8, 12, 33), datetime(2004, 9, 15, 13, 43, 31)],
            row=1,
            col=1,
        )
        store = _through_the_store(axis_home.capture(fig))
        relayout = {"xaxis.range": ["2004-09-15 08:12:33", "2004-09-15 13:43:31"]}

        assert axis_home.rehome(relayout, store) == (relayout, [])

    def test_a_stale_reset_on_a_date_axis_is_still_caught(self):
        fig = _two_axis_figure()
        fig.update_xaxes(
            range=[datetime(2004, 9, 15, 8, 12, 33), datetime(2004, 9, 15, 13, 43, 31)],
            row=1,
            col=1,
        )
        store = _through_the_store(axis_home.capture(fig))
        relayout = {"xaxis.range": ["2004-09-15 10:00:00", "2004-09-15 10:30:00"]}

        _, off_home = axis_home.rehome(relayout, store)

        assert off_home == ["xaxis"]

    def test_fractional_seconds_still_compare_equal(self):
        store = {"axes": {"xaxis": ["2004-09-15T08:12:33.500000"]}}
        relayout = {"xaxis.range": ["2004-09-15 08:12:33.5"]}

        assert axis_home.rehome(relayout, store) == (relayout, [])

    def test_a_non_date_string_is_not_forced_into_a_date(self):
        store = {"axes": {"xaxis": ["a", "b"]}}
        relayout = {"xaxis.range": ["a", "c"]}

        _, off_home = axis_home.rehome(relayout, store)

        assert off_home == ["xaxis"]


# ---------------------------------------------------------------------------
# apply_to_patch — what the front-end figure is told
# ---------------------------------------------------------------------------


class TestApplyToPatch:
    def test_autorange_home_is_imposed(self):
        ops = patch_ops(axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": None}}))

        assert ops["layout.xaxis.autorange"] is True
        assert ops["layout.xaxis.range"] is None

    def test_configured_range_home_is_imposed(self):
        ops = patch_ops(axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": [0, 10]}}))

        assert ops["layout.xaxis.autorange"] is False
        assert ops["layout.xaxis.range"] == [0, 10]

    def test_uirevision_is_never_touched(self):
        # editrevision falls back to uirevision, so bumping it would drop shape edits.
        ops = patch_ops(axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": None}}))

        assert "layout.uirevision" not in ops

    def test_only_the_named_axes_are_written(self):
        ops = patch_ops(
            axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": None, "yaxis": None}})
        )

        assert not [key for key in ops if key.startswith("layout.yaxis")]

    def test_every_named_axis_is_covered(self):
        ops = patch_ops(
            axis_home.apply_to_patch(
                Patch(),
                ["xaxis", "yaxis", "yaxis2"],
                {"axes": {"xaxis": None, "yaxis": [0, 1], "yaxis2": None}},
            )
        )

        assert ops["layout.yaxis.range"] == [0, 1]
        assert ops["layout.yaxis2.autorange"] is True


# ---------------------------------------------------------------------------
# What the healed relayout has to look like to plotly-resampler
# ---------------------------------------------------------------------------


class TestHealedResetReachesTheResampler:
    """A healed reset must re-aggregate the traces, not just move the axes."""

    def _resampled_figure(self) -> FigureResampler:
        fig = FigureResampler(go.Figure())
        fig.add_trace(go.Scatter(name="s"), hf_x=np.arange(200_000), hf_y=np.zeros(200_000))
        return fig

    def _x_span(self, patch) -> tuple[float, float]:
        for location, value in patch_ops(patch).items():
            if location.endswith(".x"):
                return value[0], value[-1]
        raise AssertionError("the resampler patch carries no trace data")

    @pytest.mark.parametrize(
        ("gesture", "relayout"),
        [
            ("modebar", {"xaxis.range": [1000.0, 2000.0], "xaxis.showspikes": False}),
            ("double click", {"xaxis.range": [1000.0, 2000.0]}),
        ],
    )
    def test_both_reset_gestures_re_aggregate_the_whole_recording(self, gesture, relayout):
        fig = self._resampled_figure()
        store = axis_home.capture(fig)
        fig.construct_update_data_patch({"xaxis.range[0]": 1000.0, "xaxis.range[1]": 2000.0})

        healed, off_home = axis_home.rehome(relayout, store)
        patch = fig.construct_update_data_patch(healed)

        assert off_home == ["xaxis"], gesture
        assert self._x_span(patch) == (0, 199_999), gesture
