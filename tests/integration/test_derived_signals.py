"""
Derived signals through the whole visualize pipeline, from a config to PlotModels.

A synthetic ``other`` patient keeps the data known: a 125 Hz waveform holding a 1 Hz and a
20 Hz tone, and a 1 Hz heart rate in a second file. A derived signal can then be overlaid on
its source, grouped across files, and drawn as a loop, a PSD and a spectrogram -- each reached
by the same references any signal answers to.
"""

import numpy as np
import pandas as pd
import pytest

from clinical_scope.wrapper import main

FS = 125.0
DURATION_S = 60
LOWPASS = {"method": "lowpass", "cutoff_hz": 5}


@pytest.fixture(scope="module")
def patient_folder(tmp_path_factory):
    root = tmp_path_factory.mktemp("patient")
    folder = root / "other"
    folder.mkdir()

    index = pd.date_range(
        "2024-01-01 08:00",
        periods=int(FS * DURATION_S),
        freq=pd.Timedelta(seconds=1 / FS),
        name="datetime_index",
    )
    seconds = (index - index[0]).total_seconds().to_numpy()
    art = 80 + 20 * np.sin(2 * np.pi * seconds) + 5 * np.sin(2 * np.pi * 20 * seconds)
    pd.DataFrame({"art": art, "pleth": np.cos(2 * np.pi * seconds)}, index=index).to_parquet(
        folder / "waves.parquet"
    )

    hr_index = pd.date_range(
        "2024-01-01 08:00", periods=DURATION_S, freq="1s", name="datetime_index"
    )
    hr = 60 + np.random.default_rng(0).normal(0, 2, DURATION_S)
    pd.DataFrame({"HR": hr}, index=hr_index).to_parquet(folder / "numerics.parquet")
    return root


def _patient_options(patient_folder) -> dict:
    return {
        "data_folder": str(patient_folder),
        "datetime_start": None,
        "datetime_end": None,
        "quick_load": False,
    }


def _model(models, plot_type):
    return next(model for model in models if model.plot_type == plot_type)


def _group(model, name):
    """A plot by name -- one configured in an ``other::<stem>`` section is scoped to the file."""
    return next(group for group in model.groups if group.name == name)


@pytest.fixture(scope="module")
def every_reference_models(patient_folder):
    config = {
        "other::waves": {
            "signals": {
                "art": {"unit": "mmHg"},
                "art_lp": {"source": "art", "transform": LOWPASS, "unit": "mmHg"},
            },
            "field_display": ["art", "art_lp"],
            "grouped_fields": {"ART overlay": ["art", "art_lp"]},
            "loop": {"ART against its low-pass": ["art", "art_lp"]},
            "psd": {"ART PSD": {"signals": ["art", "art_lp"], "freq_range": [0.5, 40]}},
            "spectrogram": {"Low-pass spectrogram": {"signal": "art_lp", "freq_range": [0.5, 40]}},
        },
        "other::numerics": {
            "signals": {
                "HR_ma": {"source": "HR", "transform": {"method": "moving_average", "window_s": 10}}
            },
            "field_display": ["HR", "HR_ma"],
        },
        "global": {
            "grouped_fields": {"Across files": ["other::waves::art_lp", "other::numerics::HR_ma"]}
        },
    }
    return main(_patient_options(patient_folder), config)


class TestEveryReferenceReachesADerivedSignal:
    def test_overlaid_on_its_source_through_grouped_fields(self, every_reference_models):
        group = _group(_model(every_reference_models, "time_series"), "waves::ART overlay")

        assert [signal.raw_name for signal in group.signals] == ["waves::art", "waves::art_lp"]
        derived = group.signals[1]
        assert derived.metadata.is_derived is True
        assert derived.metadata.parent_signal_name == "waves::art"
        assert derived.metadata.datasource_name == "other"

    def test_grouped_across_files_through_global_grouped_fields(self, every_reference_models):
        group = _group(_model(every_reference_models, "time_series"), "Across files")

        assert [signal.raw_name for signal in group.signals] == [
            "waves::art_lp",
            "numerics::HR_ma",
        ]

    def test_drawn_as_a_loop(self, every_reference_models):
        group = _group(_model(every_reference_models, "loop"), "waves::ART against its low-pass")

        assert len(group.signals) == 1

    def test_drawn_as_a_psd_with_the_filtered_band_gone(self, every_reference_models):
        art, art_lp = _group(_model(every_reference_models, "psd"), "waves::ART PSD").signals
        at_20_hz = np.argmin(np.abs(art.data.x - 20.0))

        assert art_lp.data.y[at_20_hz] < art.data.y[at_20_hz] - 40, "20 Hz is attenuated (dB)"

    def test_drawn_as_a_spectrogram(self, every_reference_models):
        model = _model(every_reference_models, "spectrogram")
        group = _group(model, "waves::Low-pass spectrogram")

        assert len(group.signals) == 1


@pytest.fixture(scope="module")
def file_scope_models(patient_folder):
    config = {
        "other::waves": {
            "signals": {"art_lp": {"source": "art", "transform": LOWPASS}},
            # The source is not displayed: the parquet read must still fetch it.
            "field_display": ["art_lp"],
        },
    }
    return main(_patient_options(patient_folder), config)


class TestOtherFileScope:
    """In an ``other::<stem>`` section a derived signal is qualified like any column."""

    def test_its_raw_name_is_scoped_to_the_file(self, file_scope_models):
        groups = _model(file_scope_models, "time_series").groups
        raw_names = [signal.raw_name for group in groups for signal in group.signals]

        assert "waves::art_lp" in raw_names
        assert "waves::art" not in raw_names, "an undisplayed source is read, not drawn"

    def test_it_joins_the_file_s_own_group(self, file_scope_models):
        group = _group(_model(file_scope_models, "time_series"), "waves")

        assert [signal.raw_name for signal in group.signals] == ["waves::art_lp"]
