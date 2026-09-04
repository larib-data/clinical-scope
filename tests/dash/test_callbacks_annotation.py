"""Tests for annotation_callbacks.py — direct invocation, no browser."""

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

import clinical_scope.constants as cst
from clinical_scope.dash_api.annotations.model import AnnotationSet, AnnotationType
from clinical_scope.dash_api.annotations.renderer import label_owner_ids, shape_owner_ids
from clinical_scope.dash_api.callbacks import annotation_callbacks
from clinical_scope.dash_api.callbacks.annotation_callbacks import (
    activate_group,
    arm_graph_editors,
    cancel_annotation,
    create_annotation,
    default_mode,
    delete_group,
    handle_graph_click,
    handle_shape_drag,
    leave_adjust_when_placing,
    render_annotations,
    start_move,
    toggle_annotation_hidden,
    toggle_adjust_mode,
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
        patches = render_annotations([], default_mode(), False, graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 1

    def test_loop_gets_no_hovermode(self):
        graph_ids = [{"name": "loop"}]
        subplots_list = [_subplots_data("loop")]
        patches = render_annotations([], default_mode(), False, graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_spectrogram_gets_no_hovermode(self):
        graph_ids = [{"name": "spectrogram"}]
        subplots_list = [_subplots_data("spectrogram")]
        patches = render_annotations([], default_mode(), False, graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_psd_gets_no_hovermode(self):
        graph_ids = [{"name": "psd"}]
        subplots_list = [_subplots_data("psd")]
        patches = render_annotations([], default_mode(), False, graph_ids, subplots_list, "UTC", {})
        assert len(_hovermode_ops(patches[0])) == 0

    def test_user_hovermode_survives_an_annotation_redraw(self):
        """This patch runs after to_figure, so a hardcoded value would silently discard it."""
        graph_ids = [{"name": "time_series"}]
        subplots_list = [_subplots_data("time_series")]
        patches = render_annotations(
            [],
            default_mode(),
            False,
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
            False,
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
    TYPE_BUTTONS = slice(6, 9)
    DEACTIVATE = 9
    DISPLAY = 10

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
            return start_move(_n=[1], annotations_raw=annotations_raw, mode=mode or default_mode())

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
        assert result[self.DEACTIVATE]["display"] == "none"

    def test_a_completed_move_unlights_the_type_button(self, arm, click):
        """Arming lit it; a toolbar over a mode that is off must not still advertise one."""
        stored = [_stored("time_event")]
        result = click(arm(stored)[0], stored)
        assert all("boxShadow" not in style for style in result[self.TYPE_BUTTONS])

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


class TestModeTransitionsStartFromTheDefault:
    """
    A transition names the fields it keeps; every other one comes back from ``default_mode``.

    ``moving_id`` is the field these were written for, but the guarantee is the general one:
    a field nobody keeps is cleared, so adding one does not mean revisiting every writer.
    """

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

    def test_creating_an_annotation_clears_it(self, armed):
        """A move never opens the modal, so reaching here means the move is over."""
        modal_data = {
            "type": "time_event",
            "plot_name": "time_series",
            "x": "2024-03-01T10:00:00+00:00",
            "xaxis": "x",
            "subplot_name": "Pressure",
        }
        mode = create_annotation(1, modal_data, "Intubation", "#3498db", [], [], armed)[1]
        assert mode["moving_id"] is None

    def test_starting_a_new_group_cancels_a_pending_move(self, armed, monkeypatch):
        self._with_ctx(monkeypatch, "create-group-btn")
        mode = activate_group(1, [], "Suctioning", "time_event", "#000000", [], [], armed)[0]
        assert mode["moving_id"] is None
        assert mode["group_name"] == "Suctioning"

    def test_deleting_the_active_group_clears_it(self, armed, monkeypatch):
        """Defensive: arming a move clears the group, so this pairing is hand-built."""
        self._with_ctx(monkeypatch, {"type": "group-delete-btn", "id": "g1"})
        stored = [_stored("time_event", group_id="g1", group_name="Suctioning")]
        mode = delete_group([1], stored, [], {**armed, "group_id": "g1"})[2]
        assert mode["moving_id"] is None

    def test_leaving_a_group_clears_its_name_colour_and_scope_too(self, monkeypatch):
        """Only `group_id` used to be cleared, leaving the rest to be read by a later feature."""
        self._with_ctx(monkeypatch, "annotation-mode-deactivate")
        grouped = {
            **default_mode(),
            "active": True,
            "group_id": "g1",
            "group_name": "Suctioning",
            "group_color": "#000000",
            "group_is_global": True,
        }
        mode = toggle_annotation_mode(0, 0, 0, 1, grouped)[0]
        assert mode["group_name"] is None
        assert mode["group_color"] is None
        assert mode["group_is_global"] is False

    def test_a_field_no_writer_keeps_comes_back_from_the_default(self):
        """What makes the table above structural rather than a list somebody must maintain."""
        stale = {
            **default_mode(),
            "moving_id": "a1",
            "group_name": "Suctioning",
            "pending_x0": "2024-03-01T10:00:00+00:00",
        }
        assert annotation_callbacks._mode_reset(stale, "type") == default_mode()


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
        stored,
        default_mode(),
        False,
        [{"name": "time_series"}],
        [_subplots_with_axes()],
        "UTC",
        {},
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
        assert (
            len(
                _shapes(
                    _render(
                        [
                            _stored(
                                "time_window",
                                data={
                                    "x0": "2024-01-01T00:00:00+00:00",
                                    "x1": "2024-01-01T00:01:00+00:00",
                                    "xaxis": "x",
                                },
                            )
                        ]
                    )[0]
                )
            )
            == 1
        )

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


# ==================================================================================================
# Dragging a time shape on the plot
# ==================================================================================================


def _window(annotation_id: str, x0: str, x1: str, **overrides) -> dict:
    return _stored(
        "time_window",
        id=annotation_id,
        data={"x0": x0, "x1": x1, "xaxis": "x"},
        **overrides,
    )


def _drag(relayout: dict, stored: list, monkeypatch, plot_name: str = "time_series") -> list:
    _with_ctx(monkeypatch, {"type": "graph", "name": plot_name})
    return handle_shape_drag(
        relayout_list=[relayout],
        graph_ids=[{"type": "graph", "name": plot_name}],
        subplots_list=[_subplots_with_axes()],
        annotations_raw=stored,
        adjusting=True,
        display_timezone="UTC",
    )


class TestShapeIndexToAnnotationId:
    """`shapes[i]` is a position; only the draw order turns it back into an identity."""

    def test_the_order_is_the_order_shapes_were_drawn_in(self):
        stored = [_stored("time_event", id="a1"), _window("a2", "x0", "x1")]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = shape_owner_ids(annotations, "time_series", _subplots_with_axes()["rows"])
        assert owners == ["a1", "a2"]

    def test_a_hidden_annotation_takes_no_index(self):
        stored = [_stored("time_event", id="a1", hidden=True), _stored("time_event", id="a2")]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = shape_owner_ids(annotations, "time_series", _subplots_with_axes()["rows"])
        assert owners == ["a2"]

    def test_an_annotation_whose_subplot_is_gone_takes_no_index(self):
        stored = [
            _stored("time_event", id="a1", subplot_name="Deleted"),
            _stored("time_event", id="a2"),
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = shape_owner_ids(annotations, "time_series", _subplots_with_axes()["rows"])
        assert owners == ["a2"]

    def test_a_point_takes_no_index(self):
        """Points are layout.annotations, never shapes, so they must not consume an index."""
        stored = [
            _stored("point", id="a1", data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0}),
            _stored("time_event", id="a2"),
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = shape_owner_ids(annotations, "time_series", _subplots_with_axes()["rows"])
        assert owners == ["a2"]

    def test_the_pending_preview_is_owned_by_nobody(self):
        annotations = AnnotationSet.from_dicts([_stored("time_event", id="a1")]).annotations
        owners = shape_owner_ids(
            annotations,
            "time_series",
            _subplots_with_axes()["rows"],
            pending_x0="2024-01-01 00:00:00",
        )
        assert owners == ["a1", None]

    def test_another_plot_s_annotations_take_no_index(self):
        stored = [_stored("time_event", id="a1", plot_name="spectrogram")]
        annotations = AnnotationSet.from_dicts(stored).annotations
        assert shape_owner_ids(annotations, "time_series", []) == []


class TestShapeDrag:
    """The relayout half: a finished drag re-places the annotation the index belongs to."""

    def test_dragging_a_time_event_moves_it(self, monkeypatch):
        stored = [_stored("time_event", id="a1")]
        result = _drag(
            {"shapes[0].x0": "2024-03-01 10:00:00", "shapes[0].x1": "2024-03-01 10:00:00"},
            stored,
            monkeypatch,
        )
        assert result[0]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_dragging_one_window_edge_leaves_the_other_alone(self, monkeypatch):
        stored = [_window("a1", "2024-03-01T10:00:00+00:00", "2024-03-01T10:05:00+00:00")]
        result = _drag({"shapes[0].x0": "2024-03-01 10:02:00"}, stored, monkeypatch)
        assert result[0]["data"] == {
            "x0": "2024-03-01T10:02:00+00:00",
            "x1": "2024-03-01T10:05:00+00:00",
            "xaxis": "x",
        }

    def test_the_second_shape_moves_the_second_annotation(self, monkeypatch):
        stored = [
            _stored("time_event", id="a1"),
            _window("a2", "2024-03-01T10:00:00+00:00", "2024-03-01T10:05:00+00:00"),
        ]
        result = _drag({"shapes[1].x1": "2024-03-01 10:09:00"}, stored, monkeypatch)
        assert result[0]["data"]["x"] == "2024-01-01T00:00:00+00:00"
        assert result[1]["data"]["x1"] == "2024-03-01T10:09:00+00:00"

    def test_a_hidden_annotation_does_not_shift_the_mapping(self, monkeypatch):
        """The drag must land on what is drawn, not on what is stored."""
        stored = [_stored("time_event", id="a1", hidden=True), _stored("time_event", id="a2")]
        result = _drag({"shapes[0].x0": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["data"]["x"] == "2024-01-01T00:00:00+00:00"
        assert result[1]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_the_vertical_half_of_the_drag_is_discarded(self, monkeypatch):
        """A time shape spans its subplot by construction; y is never stored."""
        stored = [_stored("time_event", id="a1")]
        result = _drag(
            {"shapes[0].x0": "2024-03-01 10:00:00", "shapes[0].y0": 0.31, "shapes[0].y1": 1.31},
            stored,
            monkeypatch,
        )
        assert set(result[0]["data"]) == {"x", "xaxis"}

    def test_a_drag_keeps_the_scope_it_had(self, monkeypatch):
        stored = [_stored("time_event", id="a1", subplot_name=None)]
        result = _drag({"shapes[0].x0": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["subplot_name"] is None

    def test_a_drag_keeps_the_label_colour_and_group(self, monkeypatch):
        stored = [_stored("time_event", id="a1", group_id="g1", group_name="Suctioning")]
        result = _drag({"shapes[0].x0": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["label"] == "Intubation"
        assert result[0]["color"] == "#3498db"
        assert result[0]["group_id"] == "g1"

    def test_a_zoom_is_not_a_drag(self, monkeypatch):
        with pytest.raises(PreventUpdate):
            _drag(
                {"xaxis.range[0]": "2024-03-01 10:00:00", "xaxis.range[1]": "2024-03-01 11:00:00"},
                [_stored("time_event", id="a1")],
                monkeypatch,
            )

    def test_an_index_past_the_drawn_shapes_changes_nothing(self, monkeypatch):
        with pytest.raises(PreventUpdate):
            _drag(
                {"shapes[7].x0": "2024-03-01 10:00:00"},
                [_stored("time_event", id="a1")],
                monkeypatch,
            )


# ==================================================================================================
# Adjust mode
# ==================================================================================================


class TestAdjustMode:
    """The toggle that arms plotly's editors, and the config it puts on each graph."""

    def test_the_first_click_arms_it(self):
        assert toggle_adjust_mode(1, False)[0] is True

    def test_a_second_click_disarms_it(self):
        assert toggle_adjust_mode(2, True)[0] is False

    def test_arming_leaves_any_placement_mode(self):
        """Armed annotations swallow clicks, so a half-placed window would never finish."""
        result = toggle_adjust_mode(1, False)
        assert result[2] == default_mode()

    def test_disarming_leaves_the_mode_store_alone(self):
        assert toggle_adjust_mode(2, True)[2] is no_update

    def test_exit_is_offered_while_adjusting(self):
        """Adjust is a mode, so the toolbar must show the same way out as every other one."""
        assert toggle_adjust_mode(1, False)[-2]["display"] == "inline-block"

    def test_exit_is_withdrawn_on_leaving(self):
        assert toggle_adjust_mode(2, True)[-2]["display"] == "none"

    @staticmethod
    def _with_ctx(monkeypatch, triggered_id):
        monkeypatch.setattr(
            annotation_callbacks,
            "ctx",
            type("Ctx", (), {"triggered": [{"value": 1}], "triggered_id": triggered_id}),
        )

    def test_exit_disarms_adjust(self, monkeypatch):
        self._with_ctx(monkeypatch, "annotation-mode-deactivate")
        assert toggle_annotation_mode(0, 0, 0, 1, default_mode())[1] is False

    def test_a_type_button_leaves_adjust_to_its_own_callback(self, monkeypatch):
        """`leave_adjust_when_placing` owns that transition; writing it twice would race."""
        self._with_ctx(monkeypatch, "annotation-type-btn-time_event")
        assert toggle_annotation_mode(1, 0, 0, 0, default_mode())[1] is no_update

    def test_disarmed_graphs_get_the_plain_config(self):
        configs = arm_graph_editors(False, [{"name": "time_series"}])
        assert "edits" not in configs[0]

    def test_an_armed_graph_gets_both_editors(self):
        configs = arm_graph_editors(True, [{"name": "time_series"}])
        assert configs[0]["edits"] == {"shapePosition": True, "annotationPosition": True}

    def test_every_graph_is_armed(self):
        configs = arm_graph_editors(True, [{"name": "time_series"}, {"name": "loop"}])
        assert all("annotationPosition" in config["edits"] for config in configs)

    def test_no_graphs_means_nothing_to_arm(self):
        with pytest.raises(PreventUpdate):
            arm_graph_editors(True, [])

    def test_a_drag_outside_the_mode_is_ignored(self, monkeypatch):
        """The editors cannot emit one, but the store is the single switch for the feature."""
        _with_ctx(monkeypatch, {"type": "graph", "name": "time_series"})
        with pytest.raises(PreventUpdate):
            handle_shape_drag(
                relayout_list=[{"shapes[0].x0": "2024-03-01 10:00:00"}],
                graph_ids=[{"type": "graph", "name": "time_series"}],
                subplots_list=[_subplots_with_axes()],
                annotations_raw=[_stored("time_event")],
                adjusting=False,
                display_timezone="UTC",
            )


class TestLabelAndPointDrag:
    """`layout.annotations` carries subplot titles and ours; only ours are stored."""

    def test_a_subplot_title_drag_is_not_stored(self, monkeypatch):
        titled = {**_subplots_with_axes(), "subplot_annotations": [{"text": "Pressure"}]}
        _with_ctx(monkeypatch, {"type": "graph", "name": "time_series"})
        with pytest.raises(PreventUpdate):
            handle_shape_drag(
                relayout_list=[{"annotations[0].x": 0.5, "annotations[0].y": 0.9}],
                graph_ids=[{"type": "graph", "name": "time_series"}],
                subplots_list=[titled],
                annotations_raw=[_stored("time_event")],
                adjusting=True,
                display_timezone="UTC",
            )

    def test_a_title_does_not_shift_our_own_indices(self, monkeypatch):
        titled = {**_subplots_with_axes(), "subplot_annotations": [{"text": "Pressure"}]}
        _with_ctx(monkeypatch, {"type": "graph", "name": "time_series"})
        result = handle_shape_drag(
            relayout_list=[{"annotations[1].x": "2024-03-01 10:00:00"}],
            graph_ids=[{"type": "graph", "name": "time_series"}],
            subplots_list=[titled],
            annotations_raw=[_stored("time_event")],
            adjusting=True,
            display_timezone="UTC",
        )
        assert result[0]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_dragging_a_point_stores_both_coordinates(self, monkeypatch):
        stored = [
            _stored(
                "point",
                data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0, "xaxis": "x", "yaxis": "y"},
            )
        ]
        result = _drag(
            {"annotations[0].x": "2024-03-01 10:00:00", "annotations[0].y": 7.5},
            stored,
            monkeypatch,
        )
        assert result[0]["data"]["x"] == "2024-03-01T10:00:00+00:00"
        assert result[0]["data"]["y"] == 7.5

    def test_dragging_a_window_label_slides_the_whole_window(self, monkeypatch):
        """Grabbing the label reads as grabbing the window, not as pulling its start off its end."""
        stored = [_window("a1", "2024-03-01T10:00:00+00:00", "2024-03-01T10:05:00+00:00")]
        result = _drag({"annotations[0].x": "2024-03-01 10:10:00"}, stored, monkeypatch)
        assert result[0]["data"]["x0"] == "2024-03-01T10:10:00+00:00"
        assert result[0]["data"]["x1"] == "2024-03-01T10:15:00+00:00"

    def test_dragging_a_time_event_label_moves_the_event(self, monkeypatch):
        result = _drag(
            {"annotations[0].x": "2024-03-01 10:00:00"}, [_stored("time_event")], monkeypatch
        )
        assert result[0]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_a_hidden_label_takes_no_index(self, monkeypatch):
        """The label is not drawn, so index 0 is the next annotation's, not its own."""
        stored = [
            _stored("time_event", id="a1", label_hidden=True),
            _stored("time_event", id="a2"),
        ]
        result = _drag({"annotations[0].x": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["data"]["x"] == "2024-01-01T00:00:00+00:00"
        assert result[1]["data"]["x"] == "2024-03-01T10:00:00+00:00"


class TestOneModeAtATime:
    """Adjust and placement both want the plot's clicks, so arming one leaves the other."""

    def test_arming_a_placement_mode_leaves_adjust(self):
        active = {**default_mode(), "active": True, "type": "time_event"}
        assert leave_adjust_when_placing(active, True)[0] is False

    def test_an_idle_mode_change_does_not_leave_adjust(self):
        with pytest.raises(PreventUpdate):
            leave_adjust_when_placing(default_mode(), True)

    def test_nothing_to_leave_when_adjust_is_off(self):
        active = {**default_mode(), "active": True}
        with pytest.raises(PreventUpdate):
            leave_adjust_when_placing(active, False)

    def test_the_mode_adjust_clears_does_not_bounce_back(self):
        """toggle_adjust_mode writes a fresh mode; that write must not re-trigger arming."""
        cleared = toggle_adjust_mode(1, False)[2]
        with pytest.raises(PreventUpdate):
            leave_adjust_when_placing(cleared, True)


class TestDraggedLoopPointDropsItsTime:
    """A loop point's `t` comes off customdata, which a relayout payload does not carry."""

    @staticmethod
    def _loop_point(**data_overrides) -> dict:
        return _stored(
            "point",
            plot_name="loop",
            subplot_name=None,
            data={
                "x": 12.5,
                "y": 3.0,
                "xaxis": "x",
                "yaxis": "y",
                "t": "2024-01-01T00:00:30+00:00",
                **data_overrides,
            },
        )

    def _drag_on_loop(self, relayout: dict, stored: list, monkeypatch) -> list:
        _with_ctx(monkeypatch, {"type": "graph", "name": "loop"})
        return handle_shape_drag(
            relayout_list=[relayout],
            graph_ids=[{"type": "graph", "name": "loop"}],
            subplots_list=[{**_subplots_data("loop"), "rows": []}],
            annotations_raw=stored,
            adjusting=True,
            display_timezone="UTC",
        )

    def test_a_dragged_loop_point_keeps_its_coordinates(self, monkeypatch):
        result = self._drag_on_loop(
            {"annotations[0].x": 20.0, "annotations[0].y": 4.5},
            [self._loop_point()],
            monkeypatch,
        )
        assert result[0]["data"]["x"] == "20.0"
        assert result[0]["data"]["y"] == 4.5

    def test_a_dragged_loop_point_drops_its_time(self, monkeypatch):
        result = self._drag_on_loop({"annotations[0].x": 20.0}, [self._loop_point()], monkeypatch)
        assert "t" not in result[0]["data"]

    def test_a_time_series_point_has_no_time_to_drop(self, monkeypatch):
        """`t` is absent by construction there — x already is the instant."""
        stored = [_stored("point", data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0, "xaxis": "x"})]
        result = _drag({"annotations[0].x": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["data"]["x"] == "2024-03-01T10:00:00+00:00"
        assert "t" not in result[0]["data"]


# ==================================================================================================
# Dual y-axis subplots
# ==================================================================================================


def _subplots_dual_y() -> dict:
    """
    A two-row layout whose rows carry a secondary y-axis.

    Plotly numbers overlaying axes into the same sequence, so row 2's primary is y3, not y2 —
    the numbering the click path's grid formula has to work around.
    """
    return {
        "plot_type": "time_series",
        "rows": [
            {"row": 1, "col": 1, "name": "Pressure", "yaxis": "y"},
            {"row": 2, "col": 1, "name": "Flow", "yaxis": "y3"},
        ],
        "subplot_annotations": [{"text": "Pressure"}, {"text": "Flow"}],
        "n_cols": 1,
        "yaxis_to_subplot": {
            "y": {"name": "Pressure"},
            "y2": {"name": "Pressure"},
            "y3": {"name": "Flow"},
            "y4": {"name": "Flow"},
        },
    }


def _drag_dual(relayout: dict, stored: list, monkeypatch) -> list:
    _with_ctx(monkeypatch, {"type": "graph", "name": "time_series"})
    return handle_shape_drag(
        relayout_list=[relayout],
        graph_ids=[{"type": "graph", "name": "time_series"}],
        subplots_list=[_subplots_dual_y()],
        annotations_raw=stored,
        adjusting=True,
        display_timezone="UTC",
    )


class TestDualYAxis:
    """A secondary y-axis renumbers the axes; nothing on the drag path reads that numbering."""

    def test_a_shape_spans_the_band_of_its_own_axis(self):
        """`y3 domain` is the same vertical extent as `y3` — an overlay shares its domain."""
        stored = [_stored("time_event", subplot_name="Flow")]
        shapes = _shapes(
            render_annotations(
                stored,
                default_mode(),
                False,
                [{"name": "time_series"}],
                [_subplots_dual_y()],
                "UTC",
                {},
            )[0]
        )
        assert shapes[0]["yref"] == "y3 domain"

    def test_the_owner_mapping_resolves_by_name_not_by_axis_number(self):
        stored = [
            _stored("time_event", id="a1", subplot_name="Pressure"),
            _stored("time_event", id="a2", subplot_name="Flow"),
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = shape_owner_ids(annotations, "time_series", _subplots_dual_y()["rows"])
        assert owners == ["a1", "a2"]

    def test_dragging_a_shape_on_the_second_row_moves_the_right_one(self, monkeypatch):
        stored = [
            _stored("time_event", id="a1", subplot_name="Pressure"),
            _stored("time_event", id="a2", subplot_name="Flow"),
        ]
        result = _drag_dual({"shapes[1].x0": "2024-03-01 10:00:00"}, stored, monkeypatch)
        assert result[0]["data"]["x"] == "2024-01-01T00:00:00+00:00"
        assert result[1]["data"]["x"] == "2024-03-01T10:00:00+00:00"

    def test_a_point_keeps_the_axis_it_was_anchored_to(self, monkeypatch):
        """Plotly converts the drag through the annotation's own yref, so y stays in y2 units."""
        stored = [
            _stored(
                "point",
                subplot_name="Pressure",
                data={
                    "x": "2024-01-01T00:00:00+00:00",
                    "y": 1.0,
                    "xaxis": "x",
                    "yaxis": "y2",
                },
            )
        ]
        # Index 2: the two subplot titles come first, then this point's dot.
        result = _drag_dual({"annotations[2].y": 42.0}, stored, monkeypatch)
        assert result[0]["data"]["yaxis"] == "y2"
        assert result[0]["data"]["y"] == 42.0

    def test_a_point_on_the_secondary_axis_is_drawn_against_it(self):
        stored = [
            _stored(
                "point",
                subplot_name="Pressure",
                data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0, "xaxis": "x", "yaxis": "y2"},
            )
        ]
        patch = render_annotations(
            stored,
            default_mode(),
            False,
            [{"name": "time_series"}],
            [_subplots_dual_y()],
            "UTC",
            {},
        )[0]
        drawn = [
            op["params"]["value"]
            for op in patch.to_plotly_json()["operations"]
            if op["location"] == ["layout", "annotations"]
        ][0]
        assert drawn[2]["yref"] == "y2"


class TestLabelIndexToAnnotationId:
    """The same inverse for `layout.annotations`, which starts with the subplot titles."""

    def test_the_subplot_titles_are_owned_by_nobody(self):
        annotations = AnnotationSet.from_dicts([_stored("time_event", id="a1")]).annotations
        owners = label_owner_ids(annotations, "time_series", 2, _subplots_with_axes()["rows"])
        assert owners == [None, None, "a1"]

    def test_a_hidden_label_takes_no_index(self):
        stored = [
            _stored("time_event", id="a1", label_hidden=True),
            _stored("time_event", id="a2"),
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = label_owner_ids(annotations, "time_series", 0, _subplots_with_axes()["rows"])
        assert owners == ["a2"]

    def test_a_point_owns_both_its_dot_and_its_label(self):
        stored = [
            _stored(
                "point",
                id="a1",
                data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0},
                label_hidden=False,
            )
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = label_owner_ids(annotations, "time_series", 0, _subplots_with_axes()["rows"])
        assert owners == ["a1", "a1"]

    def test_a_point_whose_label_is_hidden_owns_only_its_dot(self):
        """The dot is drawn either way, so hiding the label drops one entry, not both."""
        stored = [
            _stored(
                "point",
                id="a1",
                data={"x": "2024-01-01T00:00:00+00:00", "y": 1.0},
                label_hidden=True,
            )
        ]
        annotations = AnnotationSet.from_dicts(stored).annotations
        owners = label_owner_ids(annotations, "time_series", 0, _subplots_with_axes()["rows"])
        assert owners == ["a1"]
