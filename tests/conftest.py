"""Shared fixtures for all tests."""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = PROJECT_ROOT / "example"


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def patient_full_path():
    """Path to Patient_full with all datasources."""
    return EXAMPLE_DIR / "example_patients" / "Patient_full"


@pytest.fixture(scope="session")
def patient_difficult_path():
    """Path to Patient_difficult_format with varied file formats."""
    return EXAMPLE_DIR / "example_patients" / "Patient_difficult_format"


@pytest.fixture(scope="session")
def example_database_options():
    """Parsed example_database_options.json (covers philips_waves, philips_numerics, syringe, eit)."""
    path = EXAMPLE_DIR / "option_files" / "example_database_options.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def default_database_options():
    """Default database options from generate_default_database_options() — all 11 datasources."""
    from clinical_data_visualizer.datasource_list import generate_default_database_options

    return generate_default_database_options()


@pytest.fixture(scope="session")
def patient_options_full(patient_full_path):
    """Patient options pointing to Patient_full."""
    return {
        "data_folder": str(patient_full_path),
        "datetime_start": None,
        "datetime_end": None,
        "quick_load": False,
        "eit": {"day": "2004-09-15"},
    }


@pytest.fixture(scope="session")
def patient_options_difficult(patient_difficult_path):
    """Patient options pointing to Patient_difficult_format."""
    return {
        "data_folder": str(patient_difficult_path),
        "datetime_start": None,
        "datetime_end": None,
        "quick_load": False,
    }


# ---------------------------------------------------------------------------
# Snapshot (golden-file) support
# ---------------------------------------------------------------------------

import pandas as pd  # noqa: E402

SNAPSHOT_DIR = Path(__file__).resolve().parent / "expected_results"


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Write actual results as golden parquet files instead of comparing against them.",
    )


@pytest.fixture(scope="session")
def update_snapshots(request):
    """True when --update-snapshots was passed on the command line."""
    return request.config.getoption("--update-snapshots")


def assert_or_update_snapshot(actual: "pd.DataFrame", snapshot_path: Path, *, update: bool) -> None:
    """Compare actual against the parquet file at snapshot_path, or write it when update=True."""
    if update:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        actual.to_parquet(snapshot_path)
        return
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"Snapshot not found: {snapshot_path}\n"
            "Generate with: pytest tests/datasource/ --update-snapshots"
        )
    expected = pd.read_parquet(snapshot_path)
    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_like=False,  # column+row order is part of the contract
        check_dtype=True,  # dtype regressions must be caught
        check_names=True,  # index name must match
        check_freq=False,  # freq is None after parquet round-trip — always skip
        rtol=1e-5,
        atol=0.0,
    )
