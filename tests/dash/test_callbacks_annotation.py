"""Tests for annotation_callbacks.py — direct invocation, no browser."""

import clinical_scope.constants as cst
from clinical_scope.dash_api.callbacks.annotation_callbacks import (
    default_mode,
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
        subplots_list = [_subplots_data(cst.PlotType.TIME_SERIES)]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC")
        assert len(_hovermode_ops(patches[0])) == 1

    def test_loop_gets_no_hovermode(self):
        graph_ids = [{"name": "loop"}]
        subplots_list = [_subplots_data(cst.PlotType.LOOP)]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC")
        assert len(_hovermode_ops(patches[0])) == 0

    def test_spectrogram_gets_no_hovermode(self):
        graph_ids = [{"name": "spectrogram"}]
        subplots_list = [_subplots_data(cst.PlotType.SPECTROGRAM)]
        patches = render_annotations([], default_mode(), graph_ids, subplots_list, "UTC")
        assert len(_hovermode_ops(patches[0])) == 0
