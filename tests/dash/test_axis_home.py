"""Tests for axis_home.py — the reset-axes healing helpers, no browser."""

import plotly.graph_objects as go
from dash import Patch
from plotly.subplots import make_subplots

from clinical_scope.dash_api import axis_home

# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def _two_axis_figure() -> go.Figure:
    """Two stacked subplots, the way PlotModel.to_figure builds them."""
    fig = make_subplots(rows=2, cols=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[3, 4]), row=1, col=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[5, 6]), row=2, col=1)
    return fig


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
# reset_axes — telling a reset click apart from every other relayout
# ---------------------------------------------------------------------------


class TestResetAxes:
    def test_healthy_reset_is_detected(self):
        relayout = {
            "xaxis.autorange": True,
            "xaxis.showspikes": False,
            "yaxis.autorange": True,
            "yaxis.showspikes": False,
        }

        assert axis_home.reset_axes(relayout) == ["xaxis", "yaxis"]

    def test_corrupted_reset_is_detected(self):
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis.showspikes": False,
            "yaxis.range": [0.0, 1.0],
            "yaxis.showspikes": False,
        }

        assert axis_home.reset_axes(relayout) == ["xaxis", "yaxis"]

    def test_falsy_showspikes_still_counts(self):
        # plotly replays the saved initial value, which is normally False.
        assert axis_home.reset_axes({"xaxis.showspikes": False}) == ["xaxis"]

    def test_zoom_is_not_a_reset(self):
        relayout = {"xaxis.range[0]": 10.0, "xaxis.range[1]": 20.0}

        assert axis_home.reset_axes(relayout) == []

    def test_pan_is_not_a_reset(self):
        relayout = {
            "xaxis.range[0]": 10.0,
            "xaxis.range[1]": 20.0,
            "yaxis.range[0]": 1.0,
            "yaxis.range[1]": 2.0,
        }

        assert axis_home.reset_axes(relayout) == []

    def test_autoscale_is_not_a_reset(self):
        assert axis_home.reset_axes({"xaxis.autorange": True}) == []

    def test_dragmode_change_is_not_a_reset(self):
        assert axis_home.reset_axes({"dragmode": "pan"}) == []

    def test_shape_drag_is_not_a_reset(self):
        assert axis_home.reset_axes({"shapes[0].x0": 5.0, "shapes[0].x1": 7.0}) == []

    def test_numbered_axes(self):
        relayout = {"xaxis3.showspikes": False, "yaxis12.showspikes": True}

        assert sorted(axis_home.reset_axes(relayout)) == ["xaxis3", "yaxis12"]


# ---------------------------------------------------------------------------
# heal_relayout — what the resampler is asked to aggregate
# ---------------------------------------------------------------------------


class TestHealRelayout:
    def test_corrupted_range_becomes_autorange(self):
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis.showspikes": False,
        }

        healed = axis_home.heal_relayout(relayout, ["xaxis"], {"axes": {"xaxis": None}})

        assert healed == {"xaxis.showspikes": False, "xaxis.autorange": True}

    def test_split_range_keys_are_dropped_too(self):
        relayout = {
            "xaxis.range[0]": 100.0,
            "xaxis.range[1]": 200.0,
            "xaxis.showspikes": False,
        }

        healed = axis_home.heal_relayout(relayout, ["xaxis"], {"axes": {"xaxis": None}})

        assert healed == {"xaxis.showspikes": False, "xaxis.autorange": True}

    def test_configured_range_is_restored(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        healed = axis_home.heal_relayout(relayout, ["xaxis"], {"axes": {"xaxis": [0.0, 10.0]}})

        assert healed["xaxis.range[0]"] == 0.0
        assert healed["xaxis.range[1]"] == 10.0
        assert "xaxis.range" not in healed
        assert "xaxis.autorange" not in healed

    def test_unknown_axis_falls_back_to_autorange(self):
        healed = axis_home.heal_relayout({"xaxis9.showspikes": False}, ["xaxis9"], {})

        assert healed["xaxis9.autorange"] is True

    def test_keys_of_other_axes_survive(self):
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis.showspikes": False,
            "yaxis.range": [0.0, 1.0],
            "yaxis.showspikes": False,
        }

        healed = axis_home.heal_relayout(relayout, ["xaxis"], {"axes": {"xaxis": None}})

        assert healed["yaxis.range"] == [0.0, 1.0]
        assert healed["yaxis.showspikes"] is False

    def test_input_is_not_mutated(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        axis_home.heal_relayout(relayout, ["xaxis"], {"axes": {"xaxis": None}})

        assert relayout == {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}


# ---------------------------------------------------------------------------
# apply_to_patch — what the front-end figure is told
# ---------------------------------------------------------------------------


def _ops(patch) -> dict:
    return {
        ".".join(str(part) for part in op["location"]): op["params"].get("value")
        for op in patch.to_plotly_json()["operations"]
    }


class TestApplyToPatch:
    def test_autorange_home_is_imposed(self):
        ops = _ops(
            axis_home.apply_to_patch(
                Patch(), ["xaxis"], {"axes": {"xaxis": None}}
            )
        )

        assert ops["layout.xaxis.autorange"] is True
        assert ops["layout.xaxis.range"] is None

    def test_configured_range_home_is_imposed(self):
        ops = _ops(
            axis_home.apply_to_patch(
                Patch(), ["xaxis"], {"axes": {"xaxis": [0, 10]}}
            )
        )

        assert ops["layout.xaxis.autorange"] is False
        assert ops["layout.xaxis.range"] == [0, 10]

    def test_uirevision_is_never_touched(self):
        # editrevision falls back to uirevision, so bumping it would drop shape edits.
        ops = _ops(axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": None}}))

        assert "layout.uirevision" not in ops

    def test_only_the_named_axes_are_written(self):
        ops = _ops(
            axis_home.apply_to_patch(Patch(), ["xaxis"], {"axes": {"xaxis": None, "yaxis": None}})
        )

        assert not [key for key in ops if key.startswith("layout.yaxis")]

    def test_every_reset_axis_is_covered(self):
        ops = _ops(
            axis_home.apply_to_patch(
                Patch(),
                ["xaxis", "yaxis", "yaxis2"],
                {"axes": {"xaxis": None, "yaxis": [0, 1], "yaxis2": None}},
            )
        )

        assert ops["layout.yaxis.range"] == [0, 1]
        assert ops["layout.yaxis2.autorange"] is True


# ---------------------------------------------------------------------------
# corrupted_axes — the narrow gate that leaves a healthy reset alone
# ---------------------------------------------------------------------------


class TestCorruptedAxes:
    def test_healthy_autorange_reset_is_left_alone(self):
        relayout = {"xaxis.autorange": True, "xaxis.showspikes": False}

        assert axis_home.corrupted_axes(relayout, ["xaxis"], {"axes": {"xaxis": None}}) == []

    def test_healthy_configured_range_reset_is_left_alone(self):
        relayout = {"xaxis.range": [0.5, 30.0], "xaxis.showspikes": False}

        assert axis_home.corrupted_axes(relayout, ["xaxis"], {"axes": {"xaxis": [0.5, 30.0]}}) == []

    def test_range_where_home_is_autorange_is_corrupted(self):
        relayout = {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False}

        assert axis_home.corrupted_axes(relayout, ["xaxis"], {"axes": {"xaxis": None}}) == ["xaxis"]

    def test_wrong_range_where_home_is_a_range_is_corrupted(self):
        relayout = {"xaxis.range": [2.0, 5.0], "xaxis.showspikes": False}

        store = {"axes": {"xaxis": [0.5, 30.0]}}
        assert axis_home.corrupted_axes(relayout, ["xaxis"], store) == ["xaxis"]

    def test_autorange_where_home_is_a_range_is_corrupted(self):
        relayout = {"xaxis.autorange": True, "xaxis.showspikes": False}

        store = {"axes": {"xaxis": [0.5, 30.0]}}
        assert axis_home.corrupted_axes(relayout, ["xaxis"], store) == ["xaxis"]

    def test_matched_axes_are_never_corrected_directly(self):
        # A matched axis goes through plotly's constraint solver, so a range written to
        # it does not move it.
        relayout = {
            "xaxis.range": [100.0, 200.0],
            "xaxis.showspikes": False,
            "xaxis2.range": [100.0, 200.0],
            "xaxis2.showspikes": False,
        }
        store = {"axes": {"xaxis": None, "xaxis2": None}, "matched": {"xaxis2": "xaxis"}}

        assert axis_home.corrupted_axes(relayout, ["xaxis", "xaxis2"], store) == ["xaxis"]

    def test_dates_compare_as_text(self):
        relayout = {"xaxis.range": ["2004-09-15 08:12:33", "2004-09-15 13:43:31"]}
        store = {"axes": {"xaxis": ["2004-09-15 08:12:33", "2004-09-15 13:43:31"]}}

        assert axis_home.corrupted_axes(relayout, ["xaxis"], store) == []

    def test_split_range_keys_are_read_too(self):
        relayout = {"xaxis.range[0]": 100.0, "xaxis.range[1]": 200.0, "xaxis.showspikes": False}

        assert axis_home.corrupted_axes(relayout, ["xaxis"], {"axes": {"xaxis": None}}) == ["xaxis"]


class TestHealRelayoutFollowsTheMaster:
    def test_matched_axis_takes_its_masters_home(self):
        relayout = {"xaxis2.range": [100.0, 200.0], "xaxis2.showspikes": False}
        store = {"axes": {"xaxis": [0.0, 10.0], "xaxis2": None}, "matched": {"xaxis2": "xaxis"}}

        healed = axis_home.heal_relayout(relayout, ["xaxis2"], store)

        assert healed["xaxis2.range[0]"] == 0.0
        assert healed["xaxis2.range[1]"] == 10.0
