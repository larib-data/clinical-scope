"""
Tests for derived signals: config rows with ``source`` + ``transform``, built at plot time.

Covers each layer a derived row crosses -- the xlsx reader, static validation, the parquet
column selector, the choice of which rows to build, ``Signal.derived_from_dataframe``, and a
datasource's extraction loop with and without the quick-load cache.
"""

import io
import logging
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

import clinical_scope.constants as cst
from clinical_scope.database_options_parser import validate_database_options
from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.io.column_patterns import make_column_selector
from clinical_scope.signal_container import PlotGroup, Signal, derived_signal_names

FS = 125.0
LOWPASS = {"method": "lowpass", "cutoff_hz": 5}


def _waveform_df(columns: dict[str, float] | None = None, n: int = 1250) -> pd.DataFrame:
    """Constant-valued columns sampled at FS, tz-aware like any formatted frame."""
    index = pd.date_range("2024-01-01", periods=n, freq=pd.Timedelta(seconds=1 / FS), tz="UTC")
    columns = columns if columns is not None else {"ABP": 10.0, "HR": 60.0}
    return pd.DataFrame({name: np.full(n, value) for name, value in columns.items()}, index=index)


def _derived(df: pd.DataFrame, signals: dict, name: str = "ABP_lp", **section) -> Signal:
    return Signal.derived_from_dataframe(
        df=df, raw_signal_name=name, database_options_specific={"signals": signals, **section}
    )


def _interior_mean(signal: Signal) -> float:
    return float(np.mean(signal.data.y[100:-100]))


# ---------------------------------------------------------------------------------------------
# Signal.derived_from_dataframe
# ---------------------------------------------------------------------------------------------


class TestUnitConversion:
    """A derived row starts from its source's curve; its own unit_conversion scales its result."""

    def test_absent_on_the_derived_row_the_source_curve_is_transformed_as_drawn(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(20.0)

    def test_equal_to_the_source_factor_it_is_read_as_copied_and_ignored(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS, "unit_conversion": 2.0},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(20.0)

    def test_set_to_one_it_scales_nothing(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS, "unit_conversion": 1},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(20.0)

    def test_its_own_factor_scales_the_result_after_the_transform(self):
        """Scaled before, minmax would undo it; after, 0-1 becomes 0-100."""
        df = _waveform_df()
        df["ABP"] = np.linspace(1.0, 5.0, len(df))
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "pct": {"source": "ABP", "transform": {"method": "minmax"}, "unit_conversion": 100},
        }

        signal = _derived(df, signals, name="pct")

        assert signal.data.y.min() == pytest.approx(0.0)
        assert signal.data.y.max() == pytest.approx(100.0)

    def test_with_no_factor_anywhere_values_are_unscaled(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": LOWPASS}}

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(10.0)


class TestDerivedFromDataframe:
    def test_metadata_records_where_it_came_from(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": LOWPASS}}

        signal = _derived(_waveform_df(), signals)

        assert signal.raw_name == "ABP_lp"
        assert signal.metadata.is_derived is True
        assert signal.metadata.parent_signal_name == "ABP"
        assert signal.metadata.transform == {"method": "lowpass", "cutoff_hz": 5, "order": 4}

    def test_only_unit_conversion_and_unit_are_taken_from_the_source(self):
        """Every other empty cell means the usual default; an empty unit comes from the source."""
        signals = {
            "ABP": {"label": "Arterial", "unit": "mmHg", "color": "red", "range": [0, 200]},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        }

        signal = _derived(_waveform_df(), signals)

        assert signal.name == "ABP_lp"
        assert signal.trace_options.plot_options.y_unit_name == "mmHg"
        assert signal.trace_options.line_color is None
        assert signal.trace_options.plot_options.y_axis_range is None

    def test_its_own_row_label_unit_and_style_apply(self):
        signals = {
            "ABP_lp": {
                "source": "ABP",
                "transform": LOWPASS,
                "label": "ABP smoothed",
                "unit": "mmHg",
                "line_dash": "dot",
            }
        }

        signal = _derived(_waveform_df(), signals)

        assert signal.name == "ABP smoothed"
        assert signal.trace_options.plot_options.y_unit_name == "mmHg"
        assert signal.trace_options.line_dash == "dot"

    @pytest.mark.parametrize(
        "section",
        [
            {"numerics": {"period_resampling": 0.2}},
            {},
        ],
    )
    def test_period_resampling_never_decimates_it(self, section):
        signals = {
            "ABP": {"period_resampling": 0.2},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS, "period_resampling": 0.5},
        }

        signal = _derived(_waveform_df(), signals, **section)

        assert len(signal.data.y) == 1250
        assert signal.metadata.period_resampling is None

    def test_non_finite_source_samples_are_dropped_first(self):
        df = _waveform_df({"HR": 60.0}, n=600)
        df.iloc[::7, 0] = np.nan
        signals = {
            "HR_ma": {"source": "HR", "transform": {"method": "moving_average", "window_s": 2}}
        }

        signal = _derived(df, signals, name="HR_ma")

        assert np.allclose(signal.data.y, 60.0)
        assert len(signal.data.x) == df["HR"].notna().sum()

    def test_a_wildcard_source_resolves_like_any_signal_row(self):
        df = _waveform_df({"ABP (mmHg)": 10.0})
        signals = {"ABP_lp": {"source": "ABP*", "transform": LOWPASS}}

        assert _interior_mean(_derived(df, signals)) == pytest.approx(10.0)

    def test_a_missing_source_column_raises(self):
        signals = {"ABP_lp": {"source": "CVP", "transform": LOWPASS}}

        with pytest.raises(ValueError, match="CVP"):
            _derived(_waveform_df(), signals)


# ---------------------------------------------------------------------------------------------
# Which derived rows get built
# ---------------------------------------------------------------------------------------------


def _unit_of(signals: dict, transform: dict, name: str = "dp") -> str:
    signals = {**signals, name: {"source": "ABP", "transform": transform, **signals.get(name, {})}}
    # Varying data: the normalisations refuse a constant signal.
    df = _waveform_df()
    df["ABP"] = np.linspace(1.0, 100.0, len(df))
    return _derived(df, signals, name=name).trace_options.plot_options.y_unit_name


SOURCE_ROW = {"ABP": {"unit": "mmHg"}}


class TestDerivedUnit:
    """An empty unit is derived from the source's by the method's rule."""

    @pytest.mark.parametrize(
        ("transform", "expected"),
        [
            ({"method": "lowpass", "cutoff_hz": 5}, "mmHg"),
            ({"method": "moving_average", "window_s": 1}, "mmHg"),
            ({"method": "moving_median", "window_s": 1}, "mmHg"),
            ({"method": "savgol", "window_s": 0.2}, "mmHg"),
            ({"method": "abs"}, "mmHg"),
            ({"method": "negate"}, "mmHg"),
            ({"method": "derivative"}, "mmHg/s"),
            ({"method": "log10"}, "log10(mmHg)"),
            ({"method": "ln"}, "ln(mmHg)"),
            ({"method": "exp"}, "exp(mmHg)"),
            ({"method": "zscore"}, "z"),
            ({"method": "minmax"}, "norm"),
        ],
    )
    def test_the_rule_applied_to_the_source_unit(self, transform, expected):
        assert _unit_of(SOURCE_ROW, transform) == expected

    @pytest.mark.parametrize(
        ("transform", "expected"),
        [
            ({"method": "lowpass", "cutoff_hz": 5}, "-"),
            ({"method": "derivative"}, "/s"),
            ({"method": "log10"}, "log10"),
            ({"method": "ln"}, "ln"),
            ({"method": "exp"}, "exp"),
            ({"method": "zscore"}, "z"),
            ({"method": "minmax"}, "norm"),
        ],
    )
    def test_a_source_without_a_unit_drops_it_from_the_rule(self, transform, expected):
        assert _unit_of({"ABP": {"label": "Arterial"}}, transform) == expected

    def test_a_source_with_no_row_has_no_unit(self):
        assert _unit_of({}, {"method": "derivative"}) == "/s"

    def test_an_explicit_different_unit_wins(self):
        signals = {**SOURCE_ROW, "dp": {"unit": "kPa/s"}}

        assert _unit_of(signals, {"method": "derivative"}) == "kPa/s"

    def test_a_copied_unit_on_an_identity_method_is_kept(self):
        signals = {**SOURCE_ROW, "dp": {"unit": "mmHg"}}

        assert _unit_of(signals, LOWPASS) == "mmHg"

    def test_a_copied_unit_on_a_unit_changing_method_is_replaced(self):
        signals = {**SOURCE_ROW, "dp": {"unit": "mmHg"}}

        assert _unit_of(signals, {"method": "derivative"}) == "mmHg/s"

    def test_a_row_with_its_own_unit_conversion_and_no_unit_gets_the_default(self):
        signals = {**SOURCE_ROW, "dp": {"unit_conversion": 60}}

        assert _unit_of(signals, {"method": "derivative"}) == "-"

    def test_a_row_with_its_own_unit_conversion_and_a_unit_uses_it(self):
        signals = {**SOURCE_ROW, "dp": {"unit_conversion": 60, "unit": "mmHg/min"}}

        assert _unit_of(signals, {"method": "derivative"}) == "mmHg/min"

    def test_a_unit_conversion_copied_from_the_source_does_not_count_as_its_own(self):
        signals = {
            "ABP": {"unit": "mmHg", "unit_conversion": 7.5},
            "dp": {"unit_conversion": 7.5},
        }

        assert _unit_of(signals, {"method": "derivative"}) == "mmHg/s"

    def test_the_unit_reaches_the_axis_title(self):
        signals = {**SOURCE_ROW, "dp": {"source": "ABP", "transform": {"method": "derivative"}}}

        signal = _derived(_waveform_df(), signals, name="dp")

        assert "mmHg/s" in signal.trace_options.plot_options.y_axis_title.replace("<br>", "")

    def test_the_config_rows_are_not_modified(self):
        signals = {**SOURCE_ROW, "dp": {"source": "ABP", "transform": {"method": "derivative"}}}

        _derived(_waveform_df(), signals, name="dp")

        assert signals["dp"] == {"source": "ABP", "transform": {"method": "derivative"}}

    def test_a_derivative_overlaid_with_its_source_lands_on_the_second_axis(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "derivative"}},
            "lp": {"source": "ABP", "transform": LOWPASS},
        }
        df = _waveform_df()
        smooth = _derived(df, signals, name="lp")
        rate = _derived(df, signals, name="dp")

        group = PlotGroup(name="ABP", signals=[smooth, rate])

        assert [secondary for _, secondary in group.assign_axes()] == [False, True]
        assert group.plot_options.y_unit_name == "mmHg"
        assert group.plot_options.y2_unit_name == "mmHg/s"


class TestDerivativeValues:
    def test_a_ramp_gives_its_slope_and_unit_conversion_60_gives_per_minute(self):
        df = _waveform_df()
        df["ABP"] = 3.0 * (df.index - df.index[0]).total_seconds()
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "derivative"}},
            "dp_min": {
                "source": "ABP",
                "transform": {"method": "derivative"},
                "unit_conversion": 60,
                "unit": "mmHg/min",
            },
        }

        per_second = _derived(df, signals, name="dp")
        per_minute = _derived(df, signals, name="dp_min")

        assert np.allclose(per_second.data.y, 3.0)
        assert np.allclose(per_minute.data.y, 180.0)

    def test_per_minute_is_60_whatever_the_source_factor(self):
        df = _waveform_df()
        df["ABP"] = 3.0 * (df.index - df.index[0]).total_seconds()
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "dp_min": {
                "source": "ABP",
                "transform": {"method": "derivative"},
                "unit_conversion": 60,
            },
        }

        assert np.allclose(_derived(df, signals, name="dp_min").data.y, 360.0)


def _parabola_df() -> pd.DataFrame:
    """ABP = 3 t^2: its derivative is 6 t, its second derivative 6."""
    df = _waveform_df()
    df["ABP"] = 3.0 * (df.index - df.index[0]).total_seconds() ** 2
    return df


class TestChain:
    """A derived row whose source is another derived row runs both transforms in turn."""

    # Declared child first: the order of the rows does not matter.
    SIGNALS = {  # noqa: RUF012
        "ABP": {"unit": "mmHg"},
        "d2": {"source": "d1", "transform": {"method": "derivative"}},
        "d1": {"source": "ABP", "transform": {"method": "derivative"}},
    }

    def test_a_derivative_of_a_derivative_is_the_second_derivative(self):
        signal = _derived(_parabola_df(), self.SIGNALS, name="d2")

        assert np.allclose(signal.data.y, 6.0)

    def test_each_link_scales_its_own_result_and_the_next_starts_from_it(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "d1": {"source": "ABP", "transform": {"method": "derivative"}, "unit_conversion": 60},
            "d2": {"source": "d1", "transform": {"method": "derivative"}},
        }

        assert np.allclose(_derived(_parabola_df(), signals, name="d2").data.y, 720.0)

    def test_the_unit_is_worked_out_link_by_link(self):
        signal = _derived(_parabola_df(), self.SIGNALS, name="d2")

        assert signal.trace_options.plot_options.y_unit_name == "mmHg/s/s"

    def test_a_typed_unit_is_compared_with_the_source_s_cell_only(self):
        """d1's cell is empty, so a d2 unit that matches d1's derived one is not a copy."""
        signals = {**self.SIGNALS, "d2": {**self.SIGNALS["d2"], "unit": "mmHg/s"}}

        signal = _derived(_parabola_df(), signals, name="d2")

        assert signal.trace_options.plot_options.y_unit_name == "mmHg/s"

    def test_metadata_names_the_direct_parent(self):
        signal = _derived(_parabola_df(), self.SIGNALS, name="d2")

        assert signal.metadata.parent_signal_name == "d1"
        assert signal.metadata.transform == {"method": "derivative", "window_s": 0}

    def test_a_cycle_raises_instead_of_looping(self):
        signals = {
            "a": {"source": "b", "transform": LOWPASS},
            "b": {"source": "a", "transform": LOWPASS},
        }

        with pytest.raises(ValueError, match="'a' -> 'b' -> 'a'"):
            _derived(_waveform_df(), signals, name="a")

    def test_a_chain_ending_at_no_column_raises_naming_where_it_ends(self):
        signals = {
            "lp": {"source": "CVP", "transform": LOWPASS},
            "norm": {"source": "lp", "transform": {"method": "minmax"}},
        }

        with pytest.raises(ValueError, match="'CVP'"):
            _derived(_waveform_df(), signals, name="norm")

    def test_a_column_named_like_a_link_is_where_the_chain_starts(self, caplog):
        df = _waveform_df({"ABP": 10.0, "ABP_lp": 3.0})
        signals = {
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
            "ABP_ma": {"source": "ABP_lp", "transform": {"method": "moving_average", "window_s": 1}},
        }

        with caplog.at_level(logging.WARNING):
            signal = _derived(df, signals, name="ABP_ma")

        assert np.allclose(signal.data.y, 3.0)
        assert "'ABP_lp'" in caplog.text
        assert "Rename" in caplog.text


class TestUnitWarnings:
    PATH = "servo_u.signals.dp.unit"

    @staticmethod
    def _warnings(signals: dict) -> list[str]:
        issues = validate_database_options({"servo_u": {"signals": signals}})
        return [issue.message for issue in issues if issue.path == TestUnitWarnings.PATH]

    def test_a_copied_unit_on_a_unit_changing_method_warns_and_names_the_replacement(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "derivative"}, "unit": "mmHg"},
        }

        (message,) = self._warnings(signals)

        assert "`derivative` changes the unit" in message
        assert "`mmHg`" in message
        assert "'ABP'" in message
        assert "`mmHg/s`" in message

    def test_a_copied_unit_on_an_identity_method_does_not_warn(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": LOWPASS, "unit": "mmHg"},
        }

        assert self._warnings(signals) == []

    def test_an_empty_unit_with_its_own_unit_conversion_asks_for_a_unit(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "derivative"}, "unit_conversion": 60},
        }

        (message,) = self._warnings(signals)

        assert message.startswith("Set `unit`")
        assert "'ABP'" in message

    def test_a_copied_unit_with_its_own_unit_conversion_says_a_unit_must_be_set(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {
                "source": "ABP",
                "transform": {"method": "derivative"},
                "unit": "mmHg",
                "unit_conversion": 60,
            },
        }

        (message,) = self._warnings(signals)

        assert "changes the unit" in message
        assert "Set `unit`" in message

    def test_an_explicit_different_unit_does_not_warn(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {
                "source": "ABP",
                "transform": {"method": "derivative"},
                "unit": "mmHg/min",
                "unit_conversion": 60,
            },
        }

        assert self._warnings(signals) == []

    def test_an_empty_unit_on_a_row_without_a_unit_conversion_does_not_warn(self):
        signals = {"ABP": {"unit": "mmHg"}, "dp": {"source": "ABP", "transform": LOWPASS}}

        assert self._warnings(signals) == []

    def test_a_source_with_no_row_has_no_unit_to_copy(self):
        signals = {"dp": {"source": "ABP", "transform": {"method": "derivative"}, "unit": "-"}}

        assert self._warnings(signals) == []

    def test_an_invalid_transform_gets_no_unit_warning(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "nope"}, "unit": "mmHg"},
        }

        assert self._warnings(signals) == []

    def test_a_row_computed_from_an_invalid_one_gets_no_unit_warning(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "lp": {"source": "ABP", "transform": {"method": "nope"}},
            "dp": {"source": "lp", "transform": {"method": "derivative"}, "unit": "mmHg"},
        }

        assert self._warnings(signals) == []

    def test_these_are_warnings_never_errors(self):
        signals = {
            "ABP": {"unit": "mmHg"},
            "dp": {"source": "ABP", "transform": {"method": "derivative"}, "unit": "mmHg"},
        }

        issues = validate_database_options({"servo_u": {"signals": signals}})

        assert [issue.severity for issue in issues] == ["warning"]


class TestCopiedFactorWarning:
    PATH = "servo_u.signals.dp.unit_conversion"

    @staticmethod
    def _issues(source_factor: float, own_factor: float) -> list:
        signals = {
            "ABP": {"unit": "mmHg", "unit_conversion": source_factor},
            "dp": {
                "source": "ABP",
                "transform": {"method": "derivative"},
                "unit_conversion": own_factor,
            },
        }
        return validate_database_options({"servo_u": {"signals": signals}})

    def test_a_factor_equal_to_the_source_s_warns_it_is_ignored(self):
        issues = self._issues(7.5, 7.5)

        assert [(issue.severity, issue.path) for issue in issues] == [("warning", self.PATH)]
        assert issues[0].message.startswith("Ignored")
        assert "'ABP'" in issues[0].message

    def test_a_different_factor_does_not(self):
        paths = [issue.path for issue in self._issues(7.5, 60)]

        assert self.PATH not in paths

    def test_a_factor_of_one_on_both_is_not_reported_as_copied(self):
        paths = [issue.path for issue in self._issues(1, 1)]

        assert self.PATH not in paths


class TestDerivedSignalNames:
    SIGNALS = {  # noqa: RUF012
        "ABP": {"unit": "mmHg"},
        "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        "HR_ma": {"source": "HR", "transform": {"method": "moving_average", "window_s": 10}},
    }

    def test_with_no_field_display_every_derived_row_is_built(self):
        names = derived_signal_names({"signals": self.SIGNALS}, ["ABP", "HR"])

        assert names == ["ABP_lp", "HR_ma"]

    def test_field_display_picks_which_ones(self):
        section = {"signals": self.SIGNALS, "field_display": ["ABP", "HR_ma"]}

        assert derived_signal_names(section, ["ABP", "HR"]) == ["HR_ma"]

    def test_a_row_without_a_source_is_not_derived(self):
        section = {"signals": {"X": {"transform": LOWPASS}}, "field_display": ["X"]}

        assert derived_signal_names(section, ["ABP"]) == []

    def test_a_real_column_of_the_same_name_wins(self, caplog):
        with caplog.at_level(logging.WARNING):
            names = derived_signal_names({"signals": self.SIGNALS}, ["ABP", "HR", "ABP_lp"])

        assert names == ["HR_ma"]
        assert "ABP_lp" in caplog.text
        assert "Rename" in caplog.text


class TestColumnSelector:
    """A displayed derived signal brings its source into a pruned read."""

    def test_the_source_is_read_even_when_not_displayed(self):
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["HR", "ABP_lp"],
        }

        assert make_column_selector(section)(["ABP", "HR", "SpO2"]) == ["HR", "ABP"]

    def test_a_wildcard_source_selects_like_any_pattern(self):
        section = {
            "signals": {"ABP_lp": {"source": "ABP*", "transform": LOWPASS}},
            "field_display": ["ABP_lp"],
        }

        assert make_column_selector(section)(["ABP (mmHg)", "HR"]) == ["ABP (mmHg)"]

    def test_a_real_column_named_like_the_row_is_still_read(self):
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["ABP_lp"],
        }

        assert make_column_selector(section)(["ABP", "ABP_lp"]) == ["ABP_lp", "ABP"]

    def test_no_field_display_still_reads_everything(self):
        section = {"signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}}}

        assert make_column_selector(section)(["ABP", "HR"]) is None

    def test_a_chain_brings_the_column_it_starts_from(self):
        section = {
            "signals": {
                "ABP_lp": {"source": "ABP", "transform": LOWPASS},
                "ABP_norm": {"source": "ABP_lp", "transform": {"method": "minmax"}},
            },
            "field_display": ["HR", "ABP_norm"],
        }

        assert make_column_selector(section)(["ABP", "HR", "SpO2"]) == ["HR", "ABP"]

    def test_a_cycle_brings_nothing(self):
        section = {
            "signals": {
                "a": {"source": "b", "transform": LOWPASS},
                "b": {"source": "a", "transform": LOWPASS},
            },
            "field_display": ["HR", "a"],
        }

        assert make_column_selector(section)(["ABP", "HR"]) == ["HR"]


# ---------------------------------------------------------------------------------------------
# A datasource's extraction loop, fresh and from the quick-load cache
# ---------------------------------------------------------------------------------------------


def _make_fake_source(fresh_df: pd.DataFrame) -> type:
    """A caching datasource whose _load returns *fresh_df* and whose _format is the identity."""

    class _FakeSource(DataSourceBase):
        DATASOURCE_NAME = "fake_source"
        FILE_NAME_DATAFRAME_LOADED = "fake_source.parquet"

        @classmethod
        def _find_folder(cls, folder_path: Path) -> Path:
            return folder_path

        @classmethod
        def _find(cls, folder_path: Path) -> Path:
            return folder_path / "raw_data.bin"

        @classmethod
        def _load(cls, file_path):  # noqa: ARG003
            return fresh_df

        @classmethod
        def _format(cls, df, patient_options, database_options_specific):  # noqa: ARG003
            return df

    return _FakeSource


def _patient_options(folder: Path, *, quick_load: bool) -> dict:
    return {
        cst.PatientOptions.PathDataFolder.NAME: str(folder),
        cst.PatientOptions.QuickLoad.NAME: quick_load,
    }


@pytest.fixture
def patient_folder(tmp_path: Path) -> Path:
    (tmp_path / cst.FOLDER_NAME_OUTPUT).mkdir()
    return tmp_path


class TestExtraction:
    def test_derived_signals_join_the_raw_ones(self, patient_folder):
        source = _make_fake_source(_waveform_df())
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["ABP", "ABP_lp"],
        }

        signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP", "ABP_lp"]
        assert {signal.metadata.datasource_name for signal in signals} == {"fake_source"}

    def test_a_derived_name_is_never_read_as_a_column(self, patient_folder, caplog):
        source = _make_fake_source(_waveform_df())
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["ABP_lp"],
        }

        with caplog.at_level(logging.ERROR):
            signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP_lp"]
        assert not caplog.records

    @pytest.mark.parametrize(
        ("derived_row", "expected_in_log"),
        [
            ({"source": "CVP", "transform": LOWPASS}, "CVP"),
            ({"source": "ABP", "transform": {"method": "lowpass", "cutoff_hz": 80}}, "Nyquist"),
            (
                {"source": "ABP", "transform": {"method": "lowpass", "cutoff_hz": 5, "oder": 2}},
                "oder",
            ),
            ({"source": "ABP", "transform": {"method": "zscore"}}, "zscore"),
        ],
        ids=["source-absent", "cutoff-above-nyquist", "misspelled-parameter", "constant-signal"],
    )
    def test_a_derived_signal_that_cannot_be_built_costs_only_itself(
        self, patient_folder, caplog, derived_row, expected_in_log
    ):
        source = _make_fake_source(_waveform_df())
        section = {
            "signals": {"ABP_bad": derived_row, "HR_lp": {"source": "HR", "transform": LOWPASS}},
            "field_display": ["ABP", "ABP_bad", "HR_lp"],
        }

        with caplog.at_level(logging.ERROR):
            signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP", "HR_lp"]
        assert "ABP_bad" in caplog.text
        assert expected_in_log in caplog.text

    def test_a_log_of_a_signal_with_no_positive_sample_is_skipped_and_logged(
        self, patient_folder, caplog
    ):
        source = _make_fake_source(_waveform_df({"ABP": -1.0, "HR": 60.0}))
        section = {
            "signals": {"ABP_log": {"source": "ABP", "transform": {"method": "log10"}}},
            "field_display": ["ABP", "ABP_log"],
        }

        with caplog.at_level(logging.ERROR):
            signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP"]
        assert "log10 produced no finite value" in caplog.text

    def test_a_malformed_field_display_entry_costs_only_itself(self, patient_folder):
        """Hand-edited JSON may nest a list; that entry fails alone, as it did before."""
        source = _make_fake_source(_waveform_df())
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": [["HR"], "ABP", "ABP_lp"],
        }

        signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP", "ABP_lp"]

    def test_a_real_column_named_like_a_derived_row_is_plotted_instead(self, patient_folder):
        source = _make_fake_source(_waveform_df({"ABP": 10.0, "ABP_lp": 3.0}))
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["ABP_lp"],
        }

        signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert len(signals) == 1
        assert signals[0].metadata.is_derived is False
        assert np.allclose(signals[0].data.y, 3.0)

    def test_quick_load_reads_the_source_of_a_displayed_derived_signal(self, patient_folder):
        """The cache read prunes to field_display; the source must survive it undisplayed."""
        section = {
            "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
            "field_display": ["HR", "ABP_lp"],
        }
        # First run writes the full cache; the second must be served from it.
        _make_fake_source(_waveform_df()).main(
            _patient_options(patient_folder, quick_load=True), section
        )
        cached_only = _make_fake_source(pd.DataFrame())

        signals = cached_only.main(_patient_options(patient_folder, quick_load=True), section)

        assert [signal.raw_name for signal in signals] == ["HR", "ABP_lp"]
        assert _interior_mean(signals[1]) == pytest.approx(10.0)

    def test_quick_load_builds_a_chain_from_its_column_alone(self, patient_folder):
        """Only the end of the chain is displayed: its link is computed, not drawn."""
        section = {
            "signals": {
                "ABP_lp": {"source": "ABP", "transform": LOWPASS},
                "ABP_ma": {
                    "source": "ABP_lp",
                    "transform": {"method": "moving_average", "window_s": 1},
                },
            },
            "field_display": ["HR", "ABP_ma"],
        }
        _make_fake_source(_waveform_df()).main(
            _patient_options(patient_folder, quick_load=True), section
        )
        cached_only = _make_fake_source(pd.DataFrame())

        signals = cached_only.main(_patient_options(patient_folder, quick_load=True), section)

        assert [signal.raw_name for signal in signals] == ["HR", "ABP_ma"]
        assert _interior_mean(signals[1]) == pytest.approx(10.0)

    def test_a_broken_link_costs_every_row_computed_from_it(self, patient_folder, caplog):
        source = _make_fake_source(_waveform_df())
        section = {
            "signals": {
                "ABP_bad": {"source": "ABP", "transform": {"method": "lowpass", "cutoff_hz": 80}},
                "ABP_norm": {"source": "ABP_bad", "transform": {"method": "minmax"}},
                "HR_lp": {"source": "HR", "transform": LOWPASS},
            },
            "field_display": ["ABP", "ABP_norm", "HR_lp"],
        }

        with caplog.at_level(logging.ERROR):
            signals = source.main(_patient_options(patient_folder, quick_load=False), section)

        assert [signal.raw_name for signal in signals] == ["ABP", "HR_lp"]
        assert "ABP_norm" in caplog.text
        assert "'ABP_bad'" in caplog.text
        assert "Nyquist" in caplog.text


class TestVisualizeOnly:
    """Extract and Inspect stop at the formatted frame, so a derived signal never reaches them."""

    SECTION = {  # noqa: RUF012
        "signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}},
        "field_display": ["HR", "ABP_lp"],
    }

    @pytest.fixture
    def cached_source(self, patient_folder):
        """A source whose only data is the cache a first quick-load run wrote."""
        _make_fake_source(_waveform_df()).main(
            _patient_options(patient_folder, quick_load=True), self.SECTION
        )
        return _make_fake_source(pd.DataFrame())

    def test_extract_holds_no_derived_column(self, cached_source, patient_folder):
        df = cached_source.extract(_patient_options(patient_folder, quick_load=True), self.SECTION)

        assert "ABP_lp" not in df.columns

    @pytest.mark.parametrize("configured_columns_only", [False, True])
    def test_inspect_reports_no_derived_name(
        self, cached_source, patient_folder, configured_columns_only
    ):
        inspection = cached_source.inspect(
            _patient_options(patient_folder, quick_load=True),
            self.SECTION,
            configured_columns_only=configured_columns_only,
        )

        reported = [column.raw_name for column in inspection.columns]
        assert "ABP_lp" not in reported
        assert "HR" in reported


# ---------------------------------------------------------------------------------------------
# Static validation of the signal rows
# ---------------------------------------------------------------------------------------------


def _validate(signals: dict) -> list[tuple[str, str]]:
    issues = validate_database_options({"servo_u": {"signals": signals}})
    return [(issue.severity, issue.path) for issue in issues if issue.severity != "info"]


class TestValidation:
    PATH = "servo_u.signals.ABP_lp"

    def test_a_well_formed_derived_row_validates_cleanly(self):
        issues = validate_database_options(
            {"servo_u": {"signals": {"ABP_lp": {"source": "ABP", "transform": LOWPASS}}}}
        )

        assert issues == []

    def test_transform_without_source_is_an_error(self):
        assert _validate({"ABP_lp": {"transform": LOWPASS}}) == [("error", self.PATH)]

    def test_source_without_transform_is_an_error(self):
        assert _validate({"ABP_lp": {"source": "ABP"}}) == [("error", self.PATH)]

    @pytest.mark.parametrize("source", ["", 3, None])
    def test_a_source_that_is_not_a_name_is_an_error(self, source):
        signals = {"ABP_lp": {"source": source, "transform": LOWPASS}}

        assert _validate(signals) == [("error", f"{self.PATH}.source")]

    def test_a_derived_signal_can_be_the_source_of_another(self):
        signals = {
            "ABP_lp2": {"source": "ABP_lp", "transform": LOWPASS},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        }

        assert _validate(signals) == []

    def test_a_cycle_is_an_error_on_each_row_naming_them(self):
        signals = {
            "a": {"source": "b", "transform": LOWPASS},
            "b": {"source": "a", "transform": LOWPASS},
        }

        issues = validate_database_options({"servo_u": {"signals": signals}})

        assert [(issue.severity, issue.path) for issue in issues] == [
            ("error", "servo_u.signals.a.source"),
            ("error", "servo_u.signals.b.source"),
        ]
        assert "'a' -> 'b' -> 'a'" in issues[0].message

    def test_the_transform_itself_is_validated(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": {"method": "lowpass"}}}

        assert _validate(signals) == [("error", f"{self.PATH}.transform.cutoff_hz")]

    def test_a_misspelled_parameter_is_an_error(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": {**LOWPASS, "oder": 2}}}

        assert _validate(signals) == [("error", f"{self.PATH}.transform")]

    def test_an_unreadable_transform_cell_is_an_error_not_an_exception(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": "lowpass(5)"}}

        assert _validate(signals) == [("error", f"{self.PATH}.transform")]

    def test_period_resampling_on_a_derived_row_warns_it_is_ignored(self):
        signals = {"ABP_lp": {"source": "ABP", "transform": LOWPASS, "period_resampling": 0.2}}

        assert _validate(signals) == [("warning", f"{self.PATH}.period_resampling")]

    def test_unit_conversion_of_one_is_redundant_on_a_derived_row_too(self):
        """It scales the row's own result, so 1 is the default it looks like."""
        issues = validate_database_options(
            {
                "servo_u": {
                    "signals": {
                        "ABP": {"unit_conversion": 2.0},
                        "ABP_lp": {"source": "ABP", "transform": LOWPASS, "unit_conversion": 1},
                    }
                }
            }
        )

        assert [(issue.severity, issue.path) for issue in issues] == [("info", self.PATH)]

    def test_works_in_an_other_file_scope(self):
        issues = validate_database_options(
            {"other::waves": {"signals": {"art_lp": {"source": "art", "transform": {}}}}}
        )

        assert [(issue.severity, issue.path) for issue in issues] == [
            ("error", "other.files.waves.signals.art_lp.transform.method")
        ]


# ---------------------------------------------------------------------------------------------
# The xlsx reader
# ---------------------------------------------------------------------------------------------


def _xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "signals"
    sheet.append(
        ["datasource", "signal", "unit", "unit_conversion", "groups", "source", "transform"]
    )
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestXlsx:
    def test_a_transform_cell_becomes_the_canonical_dict(self):
        config = xlsx_bytes_to_database_options(
            _xlsx(
                [
                    ["servo_u", "ABP", "mmHg", 2, "Pressure", None, None],
                    ["servo_u", "ABP_lp", "mmHg", None, "Pressure", "ABP", "lowpass(cutoff_hz=5)"],
                ]
            )
        )

        section = config["servo_u"]
        assert section["signals"]["ABP_lp"] == {
            "unit": "mmHg",
            "source": "ABP",
            "transform": {"method": "lowpass", "cutoff_hz": 5},
        }
        assert section["field_display"] == ["ABP", "ABP_lp"]
        assert section["grouped_fields"] == {"Pressure": ["ABP", "ABP_lp"]}

    def test_an_unreadable_cell_reaches_validation_as_text(self):
        config = xlsx_bytes_to_database_options(
            _xlsx([["servo_u", "ABP_lp", None, None, None, "ABP", "lowpass(5"]])
        )

        assert config["servo_u"]["signals"]["ABP_lp"]["transform"] == "lowpass(5"
        issues = validate_database_options(config)
        assert [(issue.severity, issue.path) for issue in issues] == [
            ("error", "servo_u.signals.ABP_lp.transform")
        ]
