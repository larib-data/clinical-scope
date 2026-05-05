"""Fixtures for per-datasource tests using real example data."""

import pytest

from clinical_data_visualizer.datasource.registry import DataSource

# ---------------------------------------------------------------------------
# Helper to get the DataSourceBase subclass by name
# ---------------------------------------------------------------------------


def _get_datasource_class(name):
    ds = DataSource.get_subclass_by_name(name)
    if ds is None:
        pytest.skip(f"Datasource '{name}' not registered")
    return ds.DATASOURCE_CLASS


# ---------------------------------------------------------------------------
# Per-datasource class fixtures (session-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def philips_waves_cls():
    return _get_datasource_class("philips_waves")


@pytest.fixture(scope="session")
def philips_numerics_cls():
    return _get_datasource_class("philips_numerics")


@pytest.fixture(scope="session")
def mindray_scope_cls():
    return _get_datasource_class("mindray_scope")


@pytest.fixture(scope="session")
def mindray_respi_waves_cls():
    return _get_datasource_class("mindray_respi_waves")


@pytest.fixture(scope="session")
def mindray_respi_numerics_cls():
    return _get_datasource_class("mindray_respi_numerics")


@pytest.fixture(scope="session")
def servo_u_cls():
    return _get_datasource_class("servo_u")


@pytest.fixture(scope="session")
def syringe_cls():
    return _get_datasource_class("syringe")


@pytest.fixture(scope="session")
def eit_cls():
    return _get_datasource_class("eit")


@pytest.fixture(scope="session")
def fluxmed_signals_cls():
    return _get_datasource_class("fluxmed_signals")


@pytest.fixture(scope="session")
def fluxmed_parameters_cls():
    return _get_datasource_class("fluxmed_parameters")


@pytest.fixture(scope="session")
def other_cls():
    return _get_datasource_class("other")
