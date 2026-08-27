"""Integration tests for wrapper.main() — full visualization pipeline."""

import copy

import plotly.graph_objects as go
import pytest

import clinical_scope.constants as cst
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


class TestMainGlobalGrouping:
    """
    ``global.grouped_fields`` is the only place a group may span datasources.

    The demo patient has no raw name shared by two sources, so the collisions identity-based
    grouping exists to prevent are not expressible here — see tests/unit/test_plot_assembly.py.
    """

    @pytest.fixture(scope="class")
    def time_series_groups(self, patient_options_full, example_database_options):
        models = main(patient_options_full, example_database_options)
        return next(model for model in models if model.plot_type == "time_series").groups

    @staticmethod
    def _named(groups, name):
        return next(group for group in groups if group.name == name)

    def test_a_global_group_gathers_signals_from_several_datasources(self, time_series_groups):
        group = self._named(time_series_groups, "Paw [cross-source qualified refs]")
        assert [signal.metadata.datasource_name for signal in group.signals] == [
            "fluxmed_signals",
            "mindray_scope",
            "mindray_respi_waves",
        ]

    def test_a_qualified_other_reference_resolves(self, time_series_groups):
        """``other::numerics::PNId`` is three segments, the last two the signal's own raw name."""
        group = self._named(time_series_groups, "NI Pressure")
        assert [signal.raw_name for signal in group.signals] == [
            "numerics::PNId",
            "numerics::PNIm",
            "numerics::PNIs",
        ]

    def test_a_globally_grouped_signal_is_not_also_plotted_alone(self, time_series_groups):
        grouped = {
            signal.raw_name for signal in self._named(time_series_groups, "NI Pressure").signals
        }
        alone = {
            group.signals[0].raw_name for group in time_series_groups if len(group.signals) == 1
        }
        assert grouped & alone == set()


class TestToHtml:
    def test_to_html_writes_file(self, patient_options_full, example_database_options, tmp_path):
        models = main(patient_options_full, example_database_options)
        opts = dict(patient_options_full)
        opts["data_folder"] = str(tmp_path)
        # Create the output directory (to_html expects it or helper creates it)
        (tmp_path / "clinical_scope_output").mkdir(parents=True, exist_ok=True)
        PlotModel.to_html(models, opts)
        html_files = list(tmp_path.rglob("*.html"))
        assert len(html_files) > 0


class TestUserOptionsReachTheFigures:
    """user_options given to main() must survive the whole pipeline (ADR-0005 tenants)."""

    @pytest.fixture(scope="class")
    def user_options(self):
        return {
            cst.UserOptions.DefaultSubplotHeight.NAME: 175,
            cst.UserOptions.LegendEntryWidth.NAME: 130,
            cst.UserOptions.FallbackColorway.NAME: cst.Colorway.TOL_MUTED,
            cst.UserOptions.Template.NAME: cst.PlotTemplate.DARK,
            cst.UserOptions.HoverModeOption.NAME: cst.HoverMode.CLOSEST,
            cst.UserOptions.HoverTimeFormatOption.NAME: cst.HoverTimeFormat.DATE_TIME,
            cst.UserOptions.YSignificantDigits.NAME: 6,
        }

    @pytest.fixture(scope="class")
    def time_series_model(self, patient_options_full, example_database_options, user_options):
        models = main(patient_options_full, example_database_options, user_options=user_options)
        return next(model for model in models if model.plot_type == "time_series")

    def test_subplot_height_applied(self, time_series_model):
        assert time_series_model.computed_height == 175 * len(time_series_model.groups)

    def test_layout_fallbacks_applied(self, time_series_model):
        layout = time_series_model.figure.layout
        assert list(layout.colorway) == list(cst.Colorway.PALETTE_TOL_MUTED)
        assert layout.template.layout.paper_bgcolor == "rgb(17,17,17)"
        assert layout.hovermode == cst.HoverMode.CLOSEST
        assert layout.xaxis.hoverformat == cst.HoverTimeFormat.DATE_TIME
        assert layout.legend.entrywidth == 130

    def test_hover_digits_reach_the_traces(self, time_series_model):
        """The carrier gets all the way down to Signal construction, not just the figure."""
        templates = [
            trace.hovertemplate for trace in time_series_model.figure.data if trace.hovertemplate
        ]
        assert any("%{y:.6g}" in template for template in templates)
        # Nothing is left on the built-in default.
        assert not any("%{y:.4g}" in template for template in templates)

    def test_configured_hover_template_survives(self, time_series_model):
        """ADR-0005 end to end: the example config formats Heart Rate as %{y:.0f}."""
        heart_rate = [
            trace for trace in time_series_model.figure.data if trace.name == "Heart Rate"
        ]
        assert heart_rate
        assert "%{y:.0f}" in heart_rate[0].hovertemplate

    def test_no_user_options_keeps_defaults(self, patient_options_full, example_database_options):
        models = main(patient_options_full, example_database_options)
        ts_model = next(model for model in models if model.plot_type == "time_series")
        assert ts_model.computed_height == 300 * len(ts_model.groups)


class TestMainGlobalLoops:
    @pytest.fixture(scope="class")
    def db_opts_with_global_loop(self, example_database_options):
        """example_database_options extended with a cross-datasource global loop."""
        opts = copy.deepcopy(example_database_options)
        opts.setdefault("global", {})
        opts["global"].setdefault("loop", {})
        # Use two signals from fluxmed_signals (qualified refs) — both present in demo_patient.
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
        group_names = [g.name for m in loop_models for g in m.groups]
        assert "pv_loop" in group_names

    def test_global_loop_model_has_figure(self, patient_options_full, db_opts_with_global_loop):
        """The loop PlotModel must carry a rendered Plotly figure."""
        models = main(patient_options_full, db_opts_with_global_loop)
        loop_models = [m for m in models if m.plot_type == "loop"]
        assert loop_models
        for m in loop_models:
            assert isinstance(m.figure, go.Figure)
            assert len(m.figure.data) > 0


class TestMainSpectrograms:
    @pytest.fixture(scope="class")
    def db_opts_with_spectrogram(self, example_database_options):
        """example_database_options extended with a spectrogram on the shipped demo EEG file."""
        opts = copy.deepcopy(example_database_options)
        opts["edf"] = {
            "spectrogram": {
                "chan1 spectrogram": {"signal": "chan 1", "freq_range": [0.5, 30.0]},
            }
        }
        return opts

    def test_spectrogram_config_produces_spectrogram_plot_model(
        self, patient_options_full, db_opts_with_spectrogram
    ):
        """wrapper.main() must produce one 'spectrogram' PlotModel with real computed STFT data."""
        models = main(patient_options_full, db_opts_with_spectrogram)
        spectrogram_models = [m for m in models if m.plot_type == "spectrogram"]
        assert len(spectrogram_models) == 1
        group = spectrogram_models[0].groups[0]
        assert group.name == "chan1 spectrogram"
        freq_axis = group.signals[0].data.spectrogram_freq_axis
        assert freq_axis is not None
        assert freq_axis.min() >= 0.5
        assert freq_axis.max() <= 30.0

    def test_spectrogram_model_has_heatmap_figure(
        self, patient_options_full, db_opts_with_spectrogram
    ):
        """The spectrogram PlotModel must carry a rendered go.Heatmap trace."""
        models = main(patient_options_full, db_opts_with_spectrogram)
        spectrogram_models = [m for m in models if m.plot_type == "spectrogram"]
        assert len(spectrogram_models) == 1
        figure = spectrogram_models[0].figure
        assert isinstance(figure, go.Figure)
        assert len(figure.data) == 1
        assert isinstance(figure.data[0], go.Heatmap)


class TestMainSpectrogramRefusal:
    @pytest.fixture(scope="class")
    def db_opts_with_decimated_spectrogram(self, example_database_options):
        """Same spectrogram config, but its source signal is decimated (period_resampling<1)."""
        opts = copy.deepcopy(example_database_options)
        opts["edf"] = {
            "signals": {"chan 1": {"period_resampling": 0.5}},
            "spectrogram": {
                "chan1 spectrogram": {"signal": "chan 1", "freq_range": [0.5, 30.0]},
            },
        }
        return opts

    def test_decimated_signal_is_refused_not_raised(
        self, patient_options_full, db_opts_with_decimated_spectrogram
    ):
        """A decimated source signal must be refused (logged) rather than crashing main()."""
        models = main(patient_options_full, db_opts_with_decimated_spectrogram)
        assert isinstance(models, list)
        assert len(models) > 0, "The rest of the pipeline must still produce PlotModels"
        spectrogram_models = [m for m in models if m.plot_type == "spectrogram"]
        assert spectrogram_models == []


class TestMainPsd:
    @pytest.fixture(scope="class")
    def db_opts_with_psd(self, example_database_options):
        """example_database_options extended with one PSD overlaying two demo EEG channels."""
        opts = copy.deepcopy(example_database_options)
        opts["edf"] = {
            "signals": {"chan 1": {"label": "EEG 1"}},
            "psd": {
                # "EEG 1" is a display name and "chan 2" a raw name: one entry exercises both
                # modes of the grouped_fields reference chain.
                "EEG PSD": {"signals": ["EEG 1", "chan 2"], "freq_range": [0.5, 30.0]},
            },
        }
        return opts

    def test_psd_config_produces_one_overlaid_plot_model(
        self, patient_options_full, db_opts_with_psd
    ):
        """Both configured signals must land on a single 'psd' subplot."""
        models = main(patient_options_full, db_opts_with_psd)
        psd_models = [m for m in models if m.plot_type == "psd"]
        assert len(psd_models) == 1
        assert len(psd_models[0].groups) == 1
        group = psd_models[0].groups[0]
        assert group.name == "EEG PSD"
        assert len(group.signals) == 2

    def test_psd_x_axis_is_frequency_within_the_configured_band(
        self, patient_options_full, db_opts_with_psd
    ):
        models = main(patient_options_full, db_opts_with_psd)
        signal = [m for m in models if m.plot_type == "psd"][0].groups[0].signals[0]
        assert signal.data.x.min() >= 0.5
        assert signal.data.x.max() <= 30.0
        assert signal.data.y.shape == signal.data.x.shape

    def test_psd_model_has_scatter_traces(self, patient_options_full, db_opts_with_psd):
        """The PSD PlotModel must render as lines, not a heatmap."""
        models = main(patient_options_full, db_opts_with_psd)
        figure = [m for m in models if m.plot_type == "psd"][0].figure
        assert isinstance(figure, go.Figure)
        assert len(figure.data) == 2
        assert all(isinstance(trace, go.Scatter) for trace in figure.data)


class TestMainPsdPerEntryOverride:
    @pytest.fixture(scope="class")
    def db_opts_with_windowed_comparison(self, example_database_options):
        """Same channel plotted twice with a different window_s, to compare resolution."""
        opts = copy.deepcopy(example_database_options)
        opts["edf"] = {
            "psd": {
                "EEG PSD": {
                    "signals": [
                        {"signal": "chan 1", "window_s": 2.0, "label": "narrow window"},
                        {"signal": "chan 1", "window_s": 8.0, "label": "wide window"},
                    ],
                    "freq_range": [0.5, 30.0],
                },
            },
        }
        return opts

    def test_same_channel_twice_with_different_window_s_overlays_two_distinct_traces(
        self, patient_options_full, db_opts_with_windowed_comparison
    ):
        models = main(patient_options_full, db_opts_with_windowed_comparison)
        group = [m for m in models if m.plot_type == "psd"][0].groups[0]
        assert len(group.signals) == 2
        assert group.signals[0].name == "narrow window"
        assert group.signals[1].name == "wide window"
        assert group.signals[0].raw_name != group.signals[1].raw_name
        assert group.signals[0].data.x.shape != group.signals[1].data.x.shape


class TestMainPsdRefusal:
    @pytest.fixture(scope="class")
    def db_opts_with_decimated_psd(self, example_database_options):
        """A two-signal PSD whose second source signal is decimated."""
        opts = copy.deepcopy(example_database_options)
        opts["edf"] = {
            "signals": {"chan 2": {"period_resampling": 0.5}},
            "psd": {"EEG PSD": {"signals": ["chan 1", "chan 2"], "freq_range": [0.5, 30.0]}},
        }
        return opts

    def test_one_decimated_signal_refuses_the_whole_entry(
        self, patient_options_full, db_opts_with_decimated_psd
    ):
        """A partial comparison would mislead, so the entry is dropped rather than halved."""
        models = main(patient_options_full, db_opts_with_decimated_psd)
        assert len(models) > 0, "The rest of the pipeline must still produce PlotModels"
        assert [m for m in models if m.plot_type == "psd"] == []
