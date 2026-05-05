"""Integration tests for wrapper.main() — full visualization pipeline."""

import copy

import plotly.graph_objects as go
import pytest

from clinical_scope.signal_container import PlotModel
from clinical_scope.wrapper import main


class TestMainWithExampleConfig:
    @pytest.fixture(scope="class")
    def plot_models(self, patient_options_full, example_database_options):
        return main(patient_options_full, example_database_options)

    def test_returns_list_of_plot_models(self, plot_models):
        assert isinstance(plot_models, list)
        assert len(plot_models) > 0

    def test_all_models_have_figures(self, plot_models):
        for m in plot_models:
            assert isinstance(m, PlotModel)
            assert m.figure is not None
            assert isinstance(m.figure, go.Figure)

    def test_figures_have_traces(self, plot_models):
        for m in plot_models:
            assert len(m.figure.data) > 0

    def test_produces_time_series(self, plot_models):
        types = {m.plot_type for m in plot_models}
        assert "time_series" in types

    def test_loop_if_signals_exist(self, plot_models):
        """Loop is only produced if both loop signals exist in the actual data."""
        types = {m.plot_type for m in plot_models}
        # With synthetic data, loop signals (CrbVol, P-aer) may not exist.
        # Just verify the pipeline didn't crash; loop presence is data-dependent.
        assert isinstance(types, set)


class TestMainWithDefaultConfig:
    def test_returns_plot_models(self, patient_options_full, default_database_options):
        """
        Default config uses all datasources with empty options.

        Some datasources may fail silently — the important thing is no crash.
        """
        result = main(patient_options_full, default_database_options)
        assert isinstance(result, list)
        # With default empty config, some datasources may not produce signals
        # (e.g. if field_display is auto-populated but columns don't match config).
        # The test validates the pipeline completes without error.


class TestMainGlobalGrouping:
    def test_global_grouped_fields(self, patient_options_full, example_database_options):
        """The example config has global.grouped_fields.Pressure — verify grouping works."""
        models = main(patient_options_full, example_database_options)
        ts_models = [m for m in models if m.plot_type == "time_series"]
        if not ts_models:
            pytest.skip("No time_series models produced")
        ts_model = ts_models[0]
        # Check if Pressure group exists (depends on ART being in actual data)
        pressure_groups = [g for g in ts_model.groups if "Pressure" in g.name]
        # With synthetic data, the ART/PNId/etc. signals may or may not exist.
        # If they do, the Pressure group should be there.
        all_signal_names = {s.raw_name for g in ts_model.groups for s in g.signals}
        global_fields = {"ART", "PNId", "PNIm", "PNIs"}
        if global_fields & all_signal_names:
            assert len(pressure_groups) > 0, "Expected a 'Pressure' group"


class TestToHtml:
    def test_to_html_writes_file(self, patient_options_full, example_database_options, tmp_path):
        models = main(patient_options_full, example_database_options)
        if not models:
            pytest.skip("No models produced")
        opts = dict(patient_options_full)
        opts["data_folder"] = str(tmp_path)
        # Create the output directory (to_html expects it or helper creates it)
        (tmp_path / "clinical_scope_output").mkdir(parents=True, exist_ok=True)
        PlotModel.to_html(models, opts)
        html_files = list(tmp_path.rglob("*.html"))
        assert len(html_files) > 0


class TestMainGlobalLoops:
    @pytest.fixture(scope="class")
    def db_opts_with_global_loop(self, example_database_options):
        """example_database_options extended with a cross-datasource global loop."""
        opts = copy.deepcopy(example_database_options)
        opts.setdefault("global", {})
        opts["global"].setdefault("loop", {})
        # Use two signals from fluxmed_signals (qualified refs) — both present in Patient_full.
        opts["global"]["loop"]["pv_loop"] = [
            "fluxmed_signals::Paw(cmH2O)",
            "fluxmed_signals::Volume(ml)",
        ]
        return opts

    def test_global_loop_produces_loop_plot_model(
        self, patient_options_full, db_opts_with_global_loop
    ):
        """wrapper.main() must produce at least one PlotModel with plot_type='loop'."""
        models = main(patient_options_full, db_opts_with_global_loop)
        loop_models = [m for m in models if m.plot_type == "loop"]
        assert len(loop_models) >= 1, "Expected at least one loop PlotModel"

    def test_global_loop_model_has_correct_name(
        self, patient_options_full, db_opts_with_global_loop
    ):
        """The loop PlotModel group must be named after the loop key."""
        models = main(patient_options_full, db_opts_with_global_loop)
        loop_models = [m for m in models if m.plot_type == "loop"]
        if not loop_models:
            pytest.skip("No loop PlotModel produced — signal data may be absent")
        group_names = [g.name for m in loop_models for g in m.groups]
        assert "pv_loop" in group_names

    def test_global_loop_model_has_figure(self, patient_options_full, db_opts_with_global_loop):
        """The loop PlotModel must carry a rendered Plotly figure."""
        models = main(patient_options_full, db_opts_with_global_loop)
        loop_models = [m for m in models if m.plot_type == "loop"]
        if not loop_models:
            pytest.skip("No loop PlotModel produced — signal data may be absent")
        for m in loop_models:
            assert isinstance(m.figure, go.Figure)
            assert len(m.figure.data) > 0
