"""`_load` must transcribe the source file only — no option may reach the parquet cache.

See ADR-0010: whatever `_load` resolves is frozen into `clinical_scope_output/`, so a
later run with a different setting silently reads a cache built under the old one.
"""

import pandas as pd
import pytest

from clinical_scope.datasource.registry import DataSource

# Sources that write a parquet cache; the rule binds exactly these.
CACHING_SOURCE_NAMES = [
    entry.NAME for entry in DataSource.AVAILABLE if entry.DATASOURCE_CLASS.ALLOW_QUICK_LOAD
]

# A timezone no source defaults to, so an override that leaks is unmistakable.
OVERRIDE_TIMEZONE = "America/New_York"


@pytest.fixture(scope="module")
def source_files(patient_full_path):
    """{name: (cls, found_files)} for every caching source present in demo_patient."""
    found = {}
    for name in CACHING_SOURCE_NAMES:
        cls = DataSource.get_subclass_by_name(name).DATASOURCE_CLASS
        folder = cls._find_folder(patient_full_path)
        if folder is None:
            continue
        files = cls._find(folder)
        if files is None:
            continue
        found[name] = (cls, files)
    return found


@pytest.mark.parametrize("source_name", CACHING_SOURCE_NAMES)
def test_load_output_is_config_independent(
    source_name, source_files, example_database_options
):
    """Two configs, one file: `_load` must return the same frame from both."""
    if source_name not in source_files:
        pytest.skip(f"'{source_name}' folder not found in demo_patient")
    cls, files = source_files[source_name]

    bare_options = {}
    configured_options = {
        **example_database_options.get(source_name, {}),
        "additional_informations": {"timezone": OVERRIDE_TIMEZONE},
    }

    df_bare = cls._load(files, None, database_options_specific=bare_options)
    df_configured = cls._load(files, None, database_options_specific=configured_options)

    pd.testing.assert_frame_equal(df_bare, df_configured)
