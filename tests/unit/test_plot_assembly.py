"""
Unit tests for plot_assembly.assemble_plot_groups.

Assembly is the last purely-domain step of the visualize pipeline, so these run on in-memory
Signals and literal config dicts -- no patient folder. That is what makes the cross-datasource
name collisions below expressible at all: the single demo patient the integration suite runs
against cannot produce two datasources that share a raw name.
"""

import copy

import numpy as np
import pandas as pd
import pytest

from clinical_scope import constants as cst
from clinical_scope.plot_assembly import assemble_plot_groups
from clinical_scope.signal_container import (
    Data,
    Metadata,
    PlotOptions,
    Signal,
    TraceOptions,
)


def _signal(raw_name: str, name: str | None = None, datasource: str = "icca") -> Signal:
    """A minimal time-series Signal: enough data for a loop to be built from two of them."""
    points = 64
    return Signal(
        raw_name=raw_name,
        name=name or raw_name,
        data=Data(
            x=pd.date_range("2024-01-01", periods=points, freq="s").to_numpy(),
            y=np.linspace(0.0, 1.0, points),
        ),
        trace_options=TraceOptions(plot_options=PlotOptions(plot_type=cst.PlotType.TIME_SERIES)),
        metadata=Metadata(datasource_name=datasource),
    )


def _names(plot_groups) -> list[str]:
    return [plot_group.name for plot_group in plot_groups]


class TestDefaultGroups:
    def test_an_unconfigured_signal_gets_its_own_plot(self):
        groups = assemble_plot_groups([_signal("HR", "Heart Rate")], {})
        assert _names(groups) == ["Heart Rate"]

    def test_defaults_come_before_the_configured_groups_of_the_same_datasource(self):
        signals = [_signal("HR"), _signal("Paw"), _signal("Vol")]
        options = {"icca": {"grouped_fields": {"Ventilation": ["Paw", "Vol"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["HR", "Ventilation"]


class TestLocalSectionsAreFlattened:
    """A per-datasource section is a namespace, and desugars into qualified references."""

    def test_a_local_group_of_two_signals_becomes_one_plot(self):
        signals = [_signal("HR"), _signal("SpO2")]
        options = {"icca": {"grouped_fields": {"Vitals": ["HR", "SpO2"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals"]

    def test_a_local_reference_may_be_a_display_name(self):
        """The local path resolves through the same three-mode chain as the global one."""
        signals = [_signal("HR", "Heart Rate"), _signal("SpO2", "Oxygen Saturation")]
        options = {"icca": {"grouped_fields": {"Vitals": ["Heart Rate", "Oxygen Saturation"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals"]

    def test_an_other_file_reference_keeps_resolving(self):
        """``other`` injects ``<stem>::<column>`` references into its own section during load."""
        signals = [
            _signal("waves::art", "Arterial Pressure", "other"),
            _signal("numerics::FC", "Heart Rate", "other"),
        ]
        options = {"other": {"grouped_fields": {"Vitals": ["waves::art", "numerics::FC"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals"]

    def test_an_unresolvable_local_reference_cannot_reach_another_datasource(self):
        """Qualified even when it matches nothing, so it can never fall through to a namesake."""
        signals = [_signal("HR", "HR", "icca"), _signal("Paw", "Paw", "servo_u")]
        options = {"icca": {"grouped_fields": {"Ventilation": ["Paw", "HR"]}}}
        groups = assemble_plot_groups(signals, options)
        grouped = [signal.metadata.datasource_name for signal in groups[0].signals]
        assert grouped == ["icca"]


class TestGroupsThatResolveToOneSignal:
    def test_a_local_group_of_one_keeps_the_group_name(self):
        signals = [_signal("HR", "Heart Rate")]
        options = {"icca": {"grouped_fields": {"Vitals": ["HR", "SpO2"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals"]

    def test_a_global_group_of_one_keeps_the_group_name(self):
        signals = [_signal("HR", "Heart Rate")]
        options = {"global": {"grouped_fields": {"Vitals": ["icca::HR"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals"]

    def test_the_signal_is_not_also_plotted_on_its_own(self):
        signals = [_signal("HR", "Heart Rate")]
        options = {"global": {"grouped_fields": {"Vitals": ["icca::HR"]}}}
        assert len(assemble_plot_groups(signals, options)) == 1

    def test_a_group_that_resolves_to_nothing_leaves_its_signals_alone(self):
        signals = [_signal("HR", "Heart Rate")]
        options = {"global": {"grouped_fields": {"Vitals": ["icca::SpO2"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Heart Rate"]


class TestCrossDatasourceNameCollisions:
    """``raw_name`` is unique only within a datasource, so grouping must join on identity."""

    def test_a_local_group_does_not_suppress_a_namesake_in_another_datasource(self):
        signals = [
            _signal("HR", "HR", "icca"),
            _signal("SpO2", "SpO2", "icca"),
            _signal("HR", "HR", "mindray_scope"),
        ]
        options = {"icca": {"grouped_fields": {"Vitals": ["HR", "SpO2"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["Vitals", "HR"]

    def test_a_global_group_does_not_suppress_a_namesake_it_did_not_include(self):
        signals = [
            _signal("HR", "HR", "icca"),
            _signal("ABP", "ABP", "icca"),
            _signal("HR", "HR", "mindray_scope"),
        ]
        options = {"global": {"grouped_fields": {"Pressure": ["icca::HR", "icca::ABP"]}}}
        assert _names(assemble_plot_groups(signals, options)) == ["HR", "Pressure"]


class TestDerivedPlots:
    @pytest.fixture
    def ventilator(self) -> list[Signal]:
        """Two signals of one datasource — enough to draw a loop from."""
        return [_signal("Paw", "Airway Pressure", "servo_u"), _signal("Vol", "Volume", "servo_u")]

    def test_a_local_loop_is_built_beside_its_source_signals(self, ventilator):
        """A loop is an extra plot; the signals it is drawn from keep their own."""
        options = {"servo_u": {"loop": {"PV loop": ["Paw", "Vol"]}}}
        groups = assemble_plot_groups(ventilator, options)
        assert _names(groups) == ["Airway Pressure", "Volume", "PV loop"]
        assert groups[-1].plot_options.plot_type == "loop"

    def test_a_local_loop_reference_may_be_a_display_name(self, ventilator):
        options = {"servo_u": {"loop": {"PV loop": ["Airway Pressure", "Volume"]}}}
        assert "PV loop" in _names(assemble_plot_groups(ventilator, options))

    def test_a_global_loop_is_built_the_same_way(self):
        signals = [_signal("Paw", "Airway Pressure", "servo_u"), _signal("Vol", "Vol", "mindray")]
        options = {"global": {"loop": {"PV loop": ["servo_u::Paw", "mindray::Vol"]}}}
        assert "PV loop" in _names(assemble_plot_groups(signals, options))

    def test_a_loop_with_the_wrong_number_of_references_is_refused_not_raised(
        self, ventilator, caplog
    ):
        options = {"servo_u": {"loop": {"PV loop": ["Paw"]}}}
        assert _names(assemble_plot_groups(ventilator, options)) == ["Airway Pressure", "Volume"]
        assert "refused" in caplog.text

    def test_a_derived_plot_survives_a_group_that_shares_its_name(self):
        """A derived signal is a new object, so no string can suppress it."""
        signals = [_signal("HR", "HR", "icca"), _signal("ABP", "ABP", "icca")]
        options = {
            "icca": {"loop": {"HR": ["HR", "ABP"]}},
            "global": {"grouped_fields": {"Pressure": ["icca::HR", "icca::ABP"]}},
        }
        assert _names(assemble_plot_groups(signals, options)) == ["HR", "Pressure"]


class TestAssemblyIsPure:
    def test_the_config_dict_is_not_written_back_to(self):
        signals = [_signal("HR"), _signal("SpO2")]
        options = {
            "icca": {
                "grouped_fields": {"Vitals": ["HR", "SpO2"]},
                "loop": {"PV loop": ["HR", "SpO2"]},
                "psd": {"HR PSD": {"signals": ["HR"], "freq_range": [0.5, 30.0]}},
            },
            "global": {"grouped_fields": {"Pressure": ["icca::HR"]}},
        }
        before = copy.deepcopy(options)
        assemble_plot_groups(signals, options)
        assert options == before


class TestMalformedConfigIsSurvived:
    @pytest.mark.parametrize(
        "options",
        [
            {"icca": "not a section"},
            {"icca": {"grouped_fields": "not a mapping"}},
            {"icca": {"loop": {"PV loop": "not a list"}}},
            {"icca": {"spectrogram": {"S": {}}}},
        ],
    )
    def test_the_rest_of_the_signals_still_get_their_plots(self, options):
        """One bad database_options entry must not blank the screen."""
        groups = assemble_plot_groups([_signal("HR", "Heart Rate")], options)
        assert "Heart Rate" in _names(groups)
