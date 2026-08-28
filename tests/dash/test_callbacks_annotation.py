"""Tests for annotation_callbacks.py — direct invocation, no browser."""

import pytest

import clinical_scope.constants as cst
from clinical_scope.dash_api.annotations.model import AnnotationType
from clinical_scope.dash_api.callbacks import annotation_callbacks
from clinical_scope.dash_api.callbacks.annotation_callbacks import (
    default_mode,
    handle_graph_click,
    render_annotations,
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
