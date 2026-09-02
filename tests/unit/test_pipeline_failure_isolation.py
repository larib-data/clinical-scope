"""
Pin the promise that one broken datasource costs only itself, never the whole run.

Every guard here is a bare ``except Exception: log; continue``, so it can break two ways and
both are silent: stop catching, and a single corrupt file takes down a mid-study
visualization; catch too much, and a datasource that loaded nothing is reported as fine.
These tests fail on either.

The fakes are registered into ``DataSource.AVAILABLE`` for one test at a time, the way
``tests/plot_types/test_fake_plot_type.py`` registers a fourth plot type. The registry is
duck-typed -- ``wrapper.main`` reads ``NAME``/``MAIN_MODULE`` and ``wrapper.inspect`` reads
``NAME``/``DATASOURCE_CLASS`` -- so an entry needs no decorator, just those attributes.

Nothing here touches disk: ``ALLOW_QUICK_LOAD = False`` on every fake keeps the parquet cache
out of it, and the patient folder is an empty ``tmp_path`` no fake actually reads.
"""

from pathlib import Path
from typing import NoReturn

import pandas as pd
import pytest

from clinical_scope import wrapper
from clinical_scope.datasource import registry as datasource_registry
from clinical_scope.datasource.base import DataSourceBase

# Carried into the reported error_message, so the text is what proves the real exception
# survived rather than a generic "something failed" placeholder.
LOAD_ERROR_TEXT = "synthetic unreadable file"
FORMAT_ERROR_TEXT = "synthetic unusable timestamps"
INSPECT_ERROR_TEXT = "synthetic inspect override failure"

HEALTHY_SIGNAL = "good_signal"


def _healthy_frame() -> pd.DataFrame:
    """The datetime-indexed frame a working ``_load`` returns."""
    index = pd.date_range("2024-01-01", periods=3, freq="1s", tz="UTC")
    return pd.DataFrame({HEALTHY_SIGNAL: [1.0, 2.0, 3.0]}, index=index)


class _FakeSourceBase(DataSourceBase):
    """Shared plumbing for the fakes: find nothing real, format nothing, cache nothing."""

    ALLOW_QUICK_LOAD = False

    @classmethod
    def _find_folder(cls, folder_path: Path) -> Path:
        return folder_path

    @classmethod
    def _find(cls, folder_path: Path) -> Path:
        return folder_path / "source_file.bin"

    @classmethod
    def _load(cls, file_path: Path | list[Path]) -> pd.DataFrame:
        del file_path
        return _healthy_frame()

    @classmethod
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        # The inherited _format reads the time-shift key off OPTIONS_MODULE, which these
        # module-less fakes do not have; the datetime window is not what this file pins.
        del patient_options, database_options_specific
        return df


class _FailingLoadSource(_FakeSourceBase):
    """A corrupt file: ``_load`` raises, and nothing downstream of it ever runs."""

    DATASOURCE_NAME = "fake_failing"
    FILE_NAME_DATAFRAME_LOADED = "fake_failing_loaded.parquet"

    @classmethod
    def _load(cls, file_path: Path | list[Path]) -> pd.DataFrame:
        del file_path
        raise ValueError(LOAD_ERROR_TEXT)


class _FailingFormatSource(_FakeSourceBase):
    """Reads fine, then falls over interpreting what it read."""

    DATASOURCE_NAME = "fake_bad_format"
    FILE_NAME_DATAFRAME_LOADED = "fake_bad_format_loaded.parquet"

    @classmethod
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        del df, patient_options, database_options_specific
        raise ValueError(FORMAT_ERROR_TEXT)


class _FailingInspectSource(_FakeSourceBase):
    """Overrides ``inspect`` and raises, the way a per-file source could past the base guard."""

    DATASOURCE_NAME = "fake_bad_inspect"
    FILE_NAME_DATAFRAME_LOADED = "fake_bad_inspect_loaded.parquet"

    @classmethod
    def inspect(cls, *args, **kwargs) -> NoReturn:
        del args, kwargs
        raise ValueError(INSPECT_ERROR_TEXT)


class _HealthySource(_FakeSourceBase):
    """The neighbour that must still load while another datasource is failing."""

    DATASOURCE_NAME = "fake_healthy"
    FILE_NAME_DATAFRAME_LOADED = "fake_healthy_loaded.parquet"


class _FailingLoadEntry:
    NAME = _FailingLoadSource.DATASOURCE_NAME
    DESCRIPTION = "Fake - unreadable file"
    MAIN_MODULE = _FailingLoadSource.main
    OPTIONS = None
    DATASOURCE_CLASS = _FailingLoadSource


class _FailingInspectEntry:
    NAME = _FailingInspectSource.DATASOURCE_NAME
    DESCRIPTION = "Fake - inspect raises"
    MAIN_MODULE = _FailingInspectSource.main
    OPTIONS = None
    DATASOURCE_CLASS = _FailingInspectSource


class _HealthyEntry:
    NAME = _HealthySource.DATASOURCE_NAME
    DESCRIPTION = "Fake - loads normally"
    MAIN_MODULE = _HealthySource.main
    OPTIONS = None
    DATASOURCE_CLASS = _HealthySource


class _UnregisteredClassEntry:
    """A registry row whose implementation never resolved -- the ``None`` class branch."""

    NAME = "fake_no_class"
    DESCRIPTION = "Fake - no DataSourceBase subclass"
    MAIN_MODULE = None
    OPTIONS = None
    DATASOURCE_CLASS = None


@pytest.fixture
def register_fakes(monkeypatch):
    """
    Append fake datasources to the registry for the duration of one test.

    Function-scoped and via ``monkeypatch`` on purpose: ``AVAILABLE`` is read by
    ``generate_default_database_options``, which a session-scoped fixture also calls, so a
    leak here would be a leak into the rest of the suite.
    """

    def _register(*entries: type) -> None:
        monkeypatch.setattr(
            datasource_registry.DataSource,
            "AVAILABLE",
            (*datasource_registry.DataSource.AVAILABLE, *entries),
        )

    return _register


def _patient_options(data_folder: Path) -> dict:
    """A run over an empty real folder: the fakes never read it, but the pipeline stats it."""
    return {"data_folder": str(data_folder), "quick_load": False}


def _database_options() -> dict:
    """Name only the fakes, so no shipped datasource is visited by these runs."""
    return {
        _FailingLoadEntry.NAME: {},
        _HealthyEntry.NAME: {
            "field_display": [HEALTHY_SIGNAL],
            "signals": {HEALTHY_SIGNAL: {"label": "Good signal", "unit": "cmH2O"}},
        },
    }


class TestWrapperKeepsGoing:
    def test_a_failing_datasource_does_not_abort_the_visualization(self, register_fakes, tmp_path):
        """The raising source is skipped and its healthy neighbour still reaches a model."""
        register_fakes(_FailingLoadEntry, _HealthyEntry)

        models = wrapper.main(_patient_options(tmp_path), _database_options())

        loaded = {
            signal.raw_name
            for model in models
            for group in model.groups
            for signal in group.signals
        }
        assert loaded == {HEALTHY_SIGNAL}

    def test_a_failing_datasource_is_inspected_as_a_load_error(self, register_fakes, tmp_path):
        """
        The failure is reported per datasource, carrying the real exception text.

        Double-guarded: ``DataSourceBase.inspect`` catches the load failure and
        ``wrapper.inspect`` catches whatever gets past it, both landing on the same status.
        Neutering either one alone leaves this green -- the two tests below it are what pin
        each layer on its own.
        """
        register_fakes(_FailingLoadEntry, _HealthyEntry)

        results = {
            result.datasource_name: result
            for result in wrapper.inspect(_patient_options(tmp_path), _database_options())
        }

        assert results[_FailingLoadEntry.NAME].status == "load_error"
        assert LOAD_ERROR_TEXT in results[_FailingLoadEntry.NAME].error_message
        assert results[_HealthyEntry.NAME].status == "ok"

    def test_a_registry_row_without_a_class_is_reported_not_skipped(self, register_fakes, tmp_path):
        """A row whose implementation never resolved must still produce a visible result."""
        register_fakes(_UnregisteredClassEntry, _HealthyEntry)
        database_options = {**_database_options(), _UnregisteredClassEntry.NAME: {}}

        results = {
            result.datasource_name: result
            for result in wrapper.inspect(_patient_options(tmp_path), database_options)
        }

        assert results[_UnregisteredClassEntry.NAME].status == "load_error"
        assert "DataSource class" in results[_UnregisteredClassEntry.NAME].error_message
        assert results[_HealthyEntry.NAME].status == "ok"

    def test_an_inspect_override_that_raises_is_caught_by_the_wrapper(
        self, register_fakes, tmp_path
    ):
        """A source may override inspect(); the wrapper's own guard is what covers that."""
        register_fakes(_FailingInspectEntry, _HealthyEntry)
        database_options = {**_database_options(), _FailingInspectEntry.NAME: {}}

        results = {
            result.datasource_name: result
            for result in wrapper.inspect(_patient_options(tmp_path), database_options)
        }

        assert results[_FailingInspectEntry.NAME].status == "load_error"
        assert INSPECT_ERROR_TEXT in results[_FailingInspectEntry.NAME].error_message
        assert results[_HealthyEntry.NAME].status == "ok"


class TestDataSourceBaseDegrades:
    def test_extract_returns_none_when_the_load_raises(self, tmp_path):
        """extract() answers None rather than propagating, so batch runs continue."""
        assert _FailingLoadSource.extract(_patient_options(tmp_path), {}) is None

    def test_a_load_failure_and_a_format_failure_keep_distinct_statuses(self, tmp_path):
        """
        Both statuses in one run, so collapsing the two is what fails.

        A caller reads these to tell "the file could not be opened" from "the file opened and
        its contents made no sense" -- one status for both would hide half the diagnosis.
        """
        patient_options = _patient_options(tmp_path)

        load_result = _FailingLoadSource.inspect(patient_options, {})
        format_result = _FailingFormatSource.inspect(patient_options, {})

        assert load_result.status == "load_error"
        assert LOAD_ERROR_TEXT in load_result.error_message
        assert format_result.status == "format_error"
        assert FORMAT_ERROR_TEXT in format_result.error_message
