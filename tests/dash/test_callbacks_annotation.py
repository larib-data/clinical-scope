"""Tests for annotation_callbacks.py — direct invocation, no browser."""

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

import clinical_scope.constants as cst
from clinical_scope.dash_api.annotations.model import AnnotationSet, AnnotationType
from clinical_scope.dash_api.callbacks import annotation_callbacks
from clinical_scope.dash_api.callbacks.annotation_callbacks import (
    activate_group,
    cancel_annotation,
    default_mode,
    handle_graph_click,
    render_annotations,
    start_move,
    toggle_annotation_hidden,
    toggle_annotation_mode,
    toggle_group_hidden,
    update_annotation_list,
)


def _subplots_data(plot_type: str) -> dict:
    return {
        "plot_type": plot_type,
        "rows": [],
        "subplot_annotations": [],
        "yaxis_to_subplot": {},
    }


def _hovermode_ops(patch) -> list:
    operations = patch.to_plotly_json()["operations"]
    return [op for op in operations if op["location"] == ["layout", "hovermode"]]


class TestRenderAnnotationsHovermode:
    """Hovermode is a time_series-only fallback, matching PlotModel.to_figure."""

    def test_time_series_gets_hovermode(self):
        graph_ids = [{"name": "time_series"}]
        subplots_list = [_subplots_data("time_series")]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 1

    def test_loop_gets_no_hovermode(self):
        graph_ids = [{"name": "loop"}]
        subplots_list = [_subplots_data("loop")]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_spectrogram_gets_no_hovermode(self):
        graph_ids = [{"name": "spectrogram"}]
        subplots_list = [_subplots_data("spectrogram")]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_psd_gets_no_hovermode(self):
        graph_ids = [{"name": "psd"}]
        subplots_list = [_subplots_data("psd")]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_user_hovermode_survives_an_annotation_redraw(self):
        """This patch runs after to_figure, so a hardcoded value would silently discard it."""
        graph_ids = [{"name": "time_series"}]
        subplots_list = [_subplots_data("time_series")]
        patches = render_annotations(
            [],
            default_mode(),
            graph_ids,
            subplots_list,
            "UTC",
            {cst.UserOptions.HoverModeOption.NAME: "closest"},
        )
        assert _hovermode_ops(patches[0])[0]["params"]["value"] == "closest"

    def test_point_mode_overrides_the_user_hovermode(self):
        """Placing a point needs the nearest trace, whatever the panel style says."""
        graph_ids = [{"name": "time_series"}]
        subplots_list = [_subplots_data("time_series")]
        mode = {**default_mode(), "active": True, "type": AnnotationType.POINT.value}
        patches = render_annotations(
            [],
            mode,
            graph_ids,
            subplots_list,
            "UTC",
            {cst.UserOptions.HoverModeOption.NAME: "x unified"},
        )
        assert _hovermode_ops(patches[0])[0]["params"]["value"] == "closest"


class TestGraphClickTimeAxisGuard:
    """Time-based annotations need a time x-axis; loop and psd have neither."""

    # Position of the warning message in handle_graph_click's return tuple.
    WARNING_INDEX = 4

    @pytest.fixture
    def click_on(self, monkeypatch):
        def _click(plot_type: str, annotation_type: str, x_val):
            monkeypatch.setattr(
                annotation_callbacks,
                "ctx",
                type("Ctx", (), {"triggered_id": {"type": "graph", "name": plot_type}}),
            )
            mode = {**default_mode(), "active": True, "type": annotation_type}
            return handle_graph_click(
                click_data_list=[{"points": [{"x": x_val, "y": 42.0, "curveNumber": 0}]}],
                mode=mode,
                subplots_list=[_subplots_data(plot_type)],
                trace_map_list=[{}],
                graph_ids=[{"type": "graph", "name": plot_type}],
                annotations_raw=[],
                display_timezone="UTC",
            )

        return _click

    def test_time_event_refused_on_psd(self, click_on):
        result = click_on("psd", "time_event", 10.5)
        assert "not supported on psd plots" in result[self.WARNING_INDEX]

    def test_time_window_refused_on_psd(self, click_on):
        result = click_on("psd", "time_window", 10.5)
        assert "not supported on psd plots" in result[self.WARNING_INDEX]

    def test_point_accepted_on_psd_with_raw_frequency_x(self, click_on):
        """A frequency must reach the modal unchanged, not run through timezone localization."""
        result = click_on("psd", "point", 10.5)
        assert result[self.WARNING_INDEX] == ""
        assert result[1]["x"] == "10.5"

    def test_time_event_still_accepted_on_spectrogram(self, click_on):
        result = click_on("spectrogram", "time_event", "2024-01-01 00:00:00")
        assert result[self.WARNING_INDEX] == ""


def _subplots_with_axes() -> dict:
    """A two-row layout, so a move can land in a different subplot than it started in."""
    return {
        "plot_type": "time_series",
        "rows": [{"row": 1, "col": 1, "name": "Pressure"}, {"row": 2, "col": 1, "name": "Flow"}],
        "subplot_annotations": [],
        "n_cols": 1,
        "yaxis_to_subplot": {"y": {"name": "Pressure"}, "y2": {"name": "Flow"}},
    }


def _stored(annotation_type: str, **overrides) -> dict:
    """One annotation as the annotation-store holds it: plain JSON, no AnnotationSet."""
    return {
        "id": "a1",
        "type": annotation_type,
        "label": "Intubation",
        "color": "#3498db",
        "plot_name": "time_series",
        "subplot_name": "Pressure",
        "group_id": None,
        "group_name": None,
        "patient": None,
        "data": {"x": "2024-01-01T00:00:00+00:00", "xaxis": "x"},
        "trace_metadata": None,
        "label_hidden": False,
        "created_at": "2024-01-01T00:00:00+00:00",
        **overrides,
    }


class TestMoveMode:
    """Arming a move from the list panel, then re-placing the annotation with a plot click."""

    # Positions in handle_graph_click's return tuple.
    MODE = 0
    WARNING = 4
    STORE = 5
    DISPLAY = 6

    @pytest.fixture
    def arm(self, monkeypatch):
        def _arm(annotations_raw, annotation_id="a1", mode=None):
            monkeypatch.setattr(
                annotation_callbacks,
                "ctx",
                type(
                    "Ctx",
                    (),
                    {
                        "triggered": [{"value": 1}],
                        "triggered_id": {"type": "annotation-move-btn", "id": annotation_id},
                    },
                ),
            )
            return start_move(
                _n=[1], annotations_raw=annotations_raw, mode=mode or default_mode()
            )

        return _arm

    @pytest.fixture
    def click(self, monkeypatch):
        def _click(
            mode,
            annotations_raw,
            *,
            x="2024-03-01 10:00:00",
            y=42.0,
            yaxis="y2",
            plot_type="time_series",
            subplots=None,
        ):
            monkeypatch.setattr(
                annotation_callbacks,
                "ctx",
                type("Ctx", (), {"triggered_id": {"type": "graph", "name": plot_type}}),
            )
            return handle_graph_click(
                click_data_list=[{"points": [{"x": x, "y": y, "curveNumber": 0}]}],
                mode=mode,
                subplots_list=[subplots or _subplots_with_axes()],
                trace_map_list=[{"curve_0": {"xaxis": "x", "yaxis": yaxis}}],
                graph_ids=[{"type": "graph", "name": plot_type}],
                annotations_raw=annotations_raw,
                display_timezone="UTC",
            )

        return _click

    # ---------------------------------------------------------------- arming

    def test_arming_names_the_target_and_adopts_its_type(self, arm):
        mode = arm([_stored("time_window")])[0]
        assert mode["moving_id"] == "a1"
        assert mode["active"] is True
        assert mode["type"] == "time_window"

    def test_arming_lights_only_the_targets_type_button(self, arm):
        """The lit style is the one carrying a focus ring; the other two must not have it."""
        _, time_event_style, time_window_style, point_style, _, _ = arm([_stored("time_event")])
        assert "boxShadow" in time_event_style
        assert "boxShadow" not in time_window_style
        assert "boxShadow" not in point_style

    def test_arming_shows_the_target_and_reveals_the_cancel_button(self, arm):
        *_, deactivate_style, display = arm([_stored("time_event")])
        assert "Intubation" in display
        assert deactivate_style["display"] == "inline-block"

    def test_a_window_move_says_it_takes_two_clicks(self, arm):
        assert "then" in arm([_stored("time_window")])[5]

    def test_arming_clears_group_mode(self, arm):
        """One mode at a time: a group survives as its annotations, re-armed by ▶ Continue."""
        group_mode = {
            **default_mode(),
            "active": True,
            "group_id": "g1",
            "group_name": "Suctioning",
            "group_color": "#000000",
            "group_is_global": True,
        }
        mode = arm([_stored("time_event")], mode=group_mode)[0]
        assert mode["group_id"] is None
        assert mode["group_name"] is None
        assert mode["group_color"] is None
        assert mode["group_is_global"] is False

    def test_arming_an_unknown_annotation_does_nothing(self, arm):
        with pytest.raises(PreventUpdate):
            arm([_stored("time_event")], annotation_id="gone")

    # ----------------------------------------------------------------- moving

    def test_a_click_re_places_the_annotation(self, arm, click):
        stored = [_stored("time_event")]
        result = click(arm(stored)[0], stored)
        assert result[self.STORE][0]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_the_moved_annotation_keeps_its_identity(self, arm, click):
        stored = [_stored("time_event")]
        moved = click(arm(stored)[0], stored)[self.STORE][0]
        assert moved["id"] == "a1"
        assert moved["label"] == "Intubation"
        assert moved["color"] == "#3498db"
        assert moved["created_at"] == "2024-01-01T00:00:00+00:00"

    def test_a_move_takes_the_clicked_subplot_and_its_axes(self, arm, click):
        """Otherwise a point's y is read off one scale and drawn against another."""
        stored = [_stored("point", data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0})]
        moved = click(arm(stored)[0], stored)[self.STORE][0]
        assert moved["subplot_name"] == "Flow"
        assert moved["data"]["yaxis"] == "y2"
        assert moved["data"]["y"] == 42.0

    def test_a_global_annotation_stays_global(self, arm, click):
        stored = [_stored("time_event", subplot_name=None)]
        moved = click(arm(stored)[0], stored)[self.STORE][0]
        assert moved["subplot_name"] is None

    def test_a_completed_move_disarms_and_clears_the_toolbar(self, arm, click):
        stored = [_stored("time_event")]
        result = click(arm(stored)[0], stored)
        assert result[self.MODE]["moving_id"] is None
        assert result[self.MODE]["active"] is False
        assert result[self.DISPLAY] == ""

    def test_a_window_move_needs_two_clicks(self, arm, click):
        stored = [_stored("time_window", data={"x0": "a", "x1": "b", "xaxis": "x"})]
        first = click(arm(stored)[0], stored, x="2024-03-01 10:00:00")
        assert first[self.STORE] is no_update
        assert first[self.MODE]["moving_id"] == "a1"
        assert first[self.MODE]["pending_x0"] == "2024-03-01T10:00:00+00:00"

        second = click(first[self.MODE], stored, x="2024-03-01 10:05:00")
        assert second[self.STORE][0]["data"] == {
            "x0": "2024-03-01T10:00:00+00:00",
            "x1": "2024-03-01T10:05:00+00:00",
            "xaxis": "x",
        }
        assert second[self.MODE]["moving_id"] is None

    def test_a_move_onto_a_plot_with_no_time_axis_warns_but_stays_armed(self, arm, click):
        """The user can then click a valid plot instead of re-arming from the list."""
        stored = [_stored("time_event")]
        result = click(arm(stored)[0], stored, x=10.5, subplots=_subplots_data("psd"))
        assert "not supported on psd plots" in result[self.WARNING]
        assert result[self.MODE]["moving_id"] == "a1"
        assert result[self.STORE] is no_update

    def test_a_target_deleted_mid_move_leaves_no_ghost_state(self, arm, click):
        armed = arm([_stored("time_event")])[0]
        result = click(armed, [])
        assert result[self.MODE]["moving_id"] is None
        assert result[self.STORE] is no_update
        assert result[self.DISPLAY] == ""


class TestMovingIdIsClearedByEveryModeWriter:
    """`moving_id` rides on every ``{**mode}`` copy, so each writer must drop it explicitly."""

    @pytest.fixture
    def armed(self) -> dict:
        return {**default_mode(), "active": True, "type": "time_event", "moving_id": "a1"}

    def _with_ctx(self, monkeypatch, triggered_id, triggered=None):
        monkeypatch.setattr(
            annotation_callbacks,
            "ctx",
            type(
                "Ctx",
                (),
                {"triggered": triggered or [{"value": 1}], "triggered_id": triggered_id},
            ),
        )

    def test_the_deactivate_button_cancels_a_pending_move(self, armed, monkeypatch):
        self._with_ctx(monkeypatch, "annotation-mode-deactivate")
        mode = toggle_annotation_mode(0, 0, 0, 1, armed)[0]
        assert mode["moving_id"] is None
        assert mode["active"] is False

    def test_picking_another_type_cancels_a_pending_move(self, armed, monkeypatch):
        self._with_ctx(monkeypatch, "annotation-type-btn-point")
        mode = toggle_annotation_mode(0, 0, 1, 0, armed)[0]
        assert mode["moving_id"] is None
        assert mode["type"] == "point"

    def test_clicking_the_lit_type_button_cancels_a_pending_move(self, armed, monkeypatch):
        self._with_ctx(monkeypatch, "annotation-type-btn-time_event")
        mode = toggle_annotation_mode(1, 0, 0, 0, armed)[0]
        assert mode["moving_id"] is None
        assert mode["active"] is False

    def test_continuing_a_group_cancels_a_pending_move(self, armed, monkeypatch):
        """Reachable in one click: arm a move, then hit ▶ Continue on a group."""
        self._with_ctx(monkeypatch, {"type": "group-continue-btn", "id": "g1"})
        stored = [_stored("time_event", group_id="g1", group_name="Suctioning")]
        mode = activate_group(0, [1], None, None, None, [], stored, armed)[0]
        assert mode["moving_id"] is None
        assert mode["group_id"] == "g1"

    def test_closing_the_creation_modal_clears_it(self, armed):
        assert cancel_annotation(1, 0, armed)[0]["moving_id"] is None

    def test_the_pending_window_state_machine_preserves_it(self, armed):
        """The one writer that must NOT clear it: a window move's first click stays armed."""
        _, _, mode = annotation_callbacks._check_pending_x0(
            armed, "2024-03-01T10:00:00+00:00", "time_series"
        )
        assert mode["moving_id"] == "a1"


# ==================================================================================================
# Whole-annotation visibility
# ==================================================================================================


def _shapes(patch) -> list:
    """The list this patch assigns to layout.shapes, or [] if it assigns none."""
    for operation in patch.to_plotly_json()["operations"]:
        if operation["location"] == ["layout", "shapes"]:
            return operation["params"]["value"]
    return []


def _render(stored: list) -> list:
    """Render one time-series graph whose subplots match `_stored`'s subplot_name."""
    return render_annotations(
        stored, default_mode(), [{"name": "time_series"}], [_subplots_with_axes()], "UTC", {}
    )


def _with_ctx(monkeypatch, triggered_id):
    monkeypatch.setattr(
        annotation_callbacks,
        "ctx",
        type("Ctx", (), {"triggered": [{"value": 1}], "triggered_id": triggered_id}),
    )


class TestHiddenIsNotDrawn:
    """The renderer guard: whatever reaches it, a hidden annotation produces nothing."""

    def test_a_visible_time_window_draws_a_shape(self):
        assert len(_shapes(_render([_stored("time_window", data={
            "x0": "2024-01-01T00:00:00+00:00",
            "x1": "2024-01-01T00:01:00+00:00",
            "xaxis": "x",
        })])[0])) == 1

    def test_a_hidden_time_window_draws_nothing(self):
        stored = _stored(
            "time_window",
            hidden=True,
            data={
                "x0": "2024-01-01T00:00:00+00:00",
                "x1": "2024-01-01T00:01:00+00:00",
                "xaxis": "x",
            },
        )
        assert _shapes(_render([stored])[0]) == []

    def test_a_hidden_time_event_draws_nothing(self):
        assert _shapes(_render([_stored("time_event", hidden=True)])[0]) == []

    def test_hiding_one_of_two_leaves_the_other_drawn(self):
        stored = [
            _stored("time_event", hidden=True),
            {**_stored("time_event"), "id": "a2"},
        ]
        assert len(_shapes(_render(stored)[0])) == 1

    def test_a_hidden_annotation_draws_no_label_either(self):
        """`hidden` dominates: label_hidden=False must not resurrect the text."""
        stored = _stored("time_event", hidden=True, label_hidden=False, label="Intubation")
        operations = _render([stored])[0].to_plotly_json()["operations"]
        drawn = [op for op in operations if op["location"] == ["layout", "annotations"]]
        assert drawn == []


class TestVisibilityToggleCallbacks:
    """The two new buttons flip `hidden` and nothing else."""

    def test_toggling_one_annotation_hides_it(self, monkeypatch):
        _with_ctx(monkeypatch, {"type": "annotation-hidden-toggle-btn", "id": "a1"})
        result = toggle_annotation_hidden(_n=[1], annotations_raw=[_stored("time_event")])
        assert result[0]["hidden"] is True

    def test_toggling_it_again_shows_it(self, monkeypatch):
        _with_ctx(monkeypatch, {"type": "annotation-hidden-toggle-btn", "id": "a1"})
        result = toggle_annotation_hidden(
            _n=[1], annotations_raw=[_stored("time_event", hidden=True)]
        )
        assert result[0]["hidden"] is False

    def test_toggling_leaves_the_label_choice_alone(self, monkeypatch):
        _with_ctx(monkeypatch, {"type": "annotation-hidden-toggle-btn", "id": "a1"})
        result = toggle_annotation_hidden(
            _n=[1], annotations_raw=[_stored("time_event", label_hidden=True)]
        )
        assert result[0]["label_hidden"] is True

    def test_toggling_a_group_hides_every_member(self, monkeypatch):
        _with_ctx(monkeypatch, {"type": "group-hidden-btn", "id": "g1"})
        stored = [
            _stored("time_event", group_id="g1", group_name="Suctioning"),
            {**_stored("time_event", group_id="g1", group_name="Suctioning"), "id": "a2"},
        ]
        result = toggle_group_hidden(_n=[1], annotations_raw=stored)
        assert [item["hidden"] for item in result] == [True, True]

    def test_an_unclicked_button_raises(self, monkeypatch):
        monkeypatch.setattr(
            annotation_callbacks,
            "ctx",
            type("Ctx", (), {"triggered": [{"value": 0}], "triggered_id": None}),
        )
        with pytest.raises(PreventUpdate):
            toggle_annotation_hidden(_n=[0], annotations_raw=[_stored("time_event")])


# ==================================================================================================
# Scale invariants — behaviour that must hold at 1000 annotations, asserted without timing
# ==================================================================================================


def _group_of(count: int, **overrides) -> list[dict]:
    return [
        {
            **_stored("time_event", group_id="g1", group_name="Suctioning", **overrides),
            "id": f"a{index}",
        }
        for index in range(count)
    ]


class TestAnnotationListAtScale:
    """A large group must cost the panel a constant number of rows while collapsed."""

    def test_a_collapsed_group_of_1000_builds_one_row(self):
        """Title div + one group header. A refactor that built rows then filtered would fail."""
        children, _, _ = update_annotation_list(_group_of(1000), [], "UTC")
        assert len(children) == 2

    def test_expanding_it_builds_a_row_per_member(self):
        children, _, _ = update_annotation_list(_group_of(1000), ["g1"], "UTC")
        assert len(children) == 1002

    def test_the_badge_reports_the_hidden_count(self):
        _, _, badge = update_annotation_list(_group_of(1000, hidden=True), [], "UTC")
        assert badge == "1000 annotations · 1000 hidden"

    def test_the_badge_stays_plain_when_nothing_is_hidden(self):
        _, _, badge = update_annotation_list(_group_of(1000), [], "UTC")
        assert badge == "1000 annotations"

    def test_the_callback_returns_no_scrolling_element(self):
        """The scroll box is the layout's own div; rebuilding it here would reset scrollTop."""
        children, _, _ = update_annotation_list(_group_of(20), ["g1"], "UTC")
        assert not any("overflowY" in (child.style or {}) for child in children)

    def test_an_empty_list_collapses_the_panel(self):
        children, style, badge = update_annotation_list([], [], "UTC")
        assert children == []
        assert style["display"] == "none"
        assert badge == ""

    def test_a_populated_list_shows_the_panel(self):
        _, style, _ = update_annotation_list(_group_of(3), [], "UTC")
        assert "display" not in style
        assert style["overflowY"] == "auto"

    def test_1000_hidden_annotations_draw_no_shapes(self):
        assert _shapes(_render(_group_of(1000, hidden=True))[0]) == []

    def test_1000_annotations_round_trip_preserving_order_and_ids(self):
        stored = _group_of(1000)
        restored = AnnotationSet.from_dicts(stored).to_dicts()
        assert [item["id"] for item in restored] == [item["id"] for item in stored]
