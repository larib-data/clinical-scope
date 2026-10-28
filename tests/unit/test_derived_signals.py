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
from clinical_scope.signal_container import Signal, derived_signal_names

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
    """Only unit_conversion is taken from the source -- and a derived row's own value replaces it."""

    def test_absent_on_the_derived_row_it_inherits_the_source_factor(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(20.0)

    def test_equal_to_the_source_factor_it_is_applied_once_not_squared(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS, "unit_conversion": 2.0},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(20.0)

    def test_set_to_one_it_draws_raw_units(self):
        signals = {
            "ABP": {"unit_conversion": 2.0},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS, "unit_conversion": 1},
        }

        assert _interior_mean(_derived(_waveform_df(), signals)) == pytest.approx(10.0)

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

    def test_only_its_own_row_configures_it(self):
        """No column but unit_conversion is inherited: an empty cell means the usual default."""
        signals = {
            "ABP": {"label": "Arterial", "unit": "mmHg", "color": "red", "range": [0, 200]},
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
        }

        signal = _derived(_waveform_df(), signals)

        assert signal.name == "ABP_lp"
        assert signal.trace_options.plot_options.y_unit_name == "-"
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
        ],
        ids=["source-absent", "cutoff-above-nyquist", "misspelled-parameter"],
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

    def test_a_derived_signal_cannot_be_the_source_of_another(self):
        signals = {
            "ABP_lp": {"source": "ABP", "transform": LOWPASS},
            "ABP_lp2": {"source": "ABP_lp", "transform": LOWPASS},
        }

        assert _validate(signals) == [("error", "servo_u.signals.ABP_lp2.source")]

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

    def test_unit_conversion_of_one_is_not_redundant_on_a_derived_row(self):
        """There it overrides the source's factor, so it is not the default it looks like."""
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

        assert issues == []

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
