---
name: new-datasource
description: Add a brand-new data source module to the ClinicalDataVisualizer project. Use this skill whenever the user wants to integrate a new medical device, file format, or signal source into the pipeline — including creating the module folder, options, loading logic, registration, default database_options, tests, and example data. Trigger on phrases like "add a datasource", "new data source", "integrate X device data", "support a new file format", or any request to create a datasource from scratch.
---

# New Datasource Skill

Guide the user through adding a complete, production-ready datasource module to the ClinicalDataVisualizer project. The goal is to produce code that follows the exact same patterns as the existing 11 datasources — consistent style, proper registration, full test coverage.

## Step 0 — Gather context

Ask the user for:

1. **Example data folder** — a folder containing sample files from this datasource.
   Read the files to understand the format (CSV, parquet, XML, custom binary, etc.), column structure, datetime representation, and signal naming.

2. **Starting point** — which of these best describes the situation:
   - **A)** "I already have Python code that loads this data into a DataFrame with a DatetimeIndex" — the user will point you to existing code.
   - **B)** "I have an example of the processed .parquet output" — the user has a parquet file showing the target DataFrame shape.
   - **C)** "I have nothing — figure it out from the raw files" — you need to write the loading logic from scratch.

3. **Datasource identity** (infer from the data when possible — only ask what you can't figure out):
   - A short **snake_case name** for the datasource (e.g., `hamilton_ventilator`). This becomes the module folder name, the registry NAME, and the key in database_options.
   - A human-readable **description** (e.g., `"Hamilton Ventilator"`).
   - **Folder keywords**: words that identify the datasource subfolder inside a patient directory (e.g., `["hamilton", "vent"]`). These are matched case-insensitively.
   - **Expected folder name**: usually same as `DATASOURCE_NAME`, but can differ if the folder on disk has a different convention (e.g., folder is `"hamilton"` but datasource is `"hamilton_ventilator"`).
   - **File keywords**: words to match files within that folder (e.g., `["hamilton", "vent", "hmlt"]`), ordered from most specific to least.
   - **File extensions**: accepted formats ordered by preference (e.g., `[".parquet", ".csv"]`).
   - **Multi-file?**: does the datasource load all matching files (`True`) or pick the best single file (`False`)? Almost all datasources use `False`.

4. **Signal characteristics** (ask if not obvious from the data):
   - Default timezone (e.g., `"Europe/Paris"`)
   - Are there pre-known signal names, labels, units, colors? (becomes `DEFAULT_DATABASE_OPTIONS`)
   - Any grouped_fields or loop definitions?
   - Default trace style: lines, lines+markers, markers? Line width?

If answers are already clear from context, proceed without asking. Be smart about inferring — if you can read the example folder and files, you can often derive the folder keywords, file keywords, extensions, and signal info without asking.

**Environment**: always activate the venv before running any Python or pytest commands:
```bash
source /Users/alexis/Codes/clinical_visu_venv/bin/activate
```

## Step 1 — Understand the raw data

Read the example files. Identify:
- **File format** (CSV delimiter, parquet schema, XML structure, etc.)
- **Datetime column(s)** — name, format, timezone
- **Signal columns** — names, dtypes, units (often encoded in column names like `"Paw(cmH2O)"`)
- **Any special structure** (waveform blocks that need expansion, nested JSON, multi-sheet Excel, etc.)

Print a short summary for the user: file format, N columns found, datetime handling needed, any complexity.

## Step 2 — Create the datasource module

Create three files under `src/clinical_data_visualizer/<datasource_name>/`:

### 2a. `__init__.py`

Empty file (or single-line docstring).

### 2b. `options.py`

Use this template — fill in from the user's answers and data inspection:

```python
import clinical_data_visualizer.constants as cst

DATASOURCE_NAME = "<datasource_name>"
EXPECTED_FOLDER_NAME = "<datasource_name>"
FOLDER_KEYWORDS = [<keywords>]
FILE_KEYWORDS = [<keywords>]
FILE_EXTENSIONS = [<extensions>]
MULTI_FILE = False
FILE_NAME_DATAFRAME_LOADED = "<datasource_name>.parquet"

# Only needed if CSV loading requires datetime column detection
# CANDIDATE_LIST_DATETIME_COLUMN = ["time", "datetime", "date_time", "date"]

DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines",
        "line_width": 1.5,
        "line_dash": "solid",
        "opacity": 1.0,
        "marker_symbol": None,
        "marker_size": None,
        "fill_color": None,
        "fill_pattern": None,
    }
}

DEFAULT_DATABASE_OPTIONS = {}
# If signals are known upfront, populate:
# DEFAULT_DATABASE_OPTIONS = {
#     "field_display": ["signal_a", "signal_b"],
#     "signals": {
#         "signal_a": {"label": "Signal A", "unit": "mL", "color": "blue"},
#     },
#     "grouped_fields": {"Group 1": ["signal_a", "signal_b"]},
# }


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = "timezone"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"

    # Add more patient-specific options here if needed, e.g.:
    # class Day:
    #     NAME = "day"
    #     API_TYPE = cst.ApiType.DAY
    #     DEFAULT = None
    #     MANDATORY = True
    #     DESCRIPTION = "Recording day"
```

Key rules:
- `DATASOURCE_NAME` must equal the registry `NAME` in `datasource/registry.py` (enforced at import time).
- `FILE_KEYWORDS` ordered from most specific to least specific — used for disambiguation tie-breaking.
- `FILE_EXTENSIONS` ordered by preference — first extension wins when multiple formats exist.
- `source_options` controls default Plotly trace styling for all signals of this datasource.

### 2c. `find_load_format.py`

Use this template. The key method is `_load()` — adapt it to the actual file format:

```python
import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.datasource.sources.<datasource_name>.options as options_naming
from clinical_data_visualizer.datasource.base import DataSourceBase
from clinical_data_visualizer.datasource.timing import time_it

logger = logging.getLogger(__name__)


class <ClassName>DataSource(DataSourceBase):
    """<Description> datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:
        # --- Load raw data ---
        # Adapt this section to the actual file format.
        # The result must be a pd.DataFrame with:
        #   - A DatetimeIndex (sorted, no duplicates)
        #   - Numeric signal columns
        #
        # For CSV: detect delimiter, find datetime column, parse it.
        # For parquet: pd.read_parquet(file_path).
        # For custom formats: parse accordingly.

        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path)
        else:
            msg = f"Unsupported file format: {file_path.suffix}"
            raise NotImplementedError(msg)

        # --- Set datetime index ---
        # Example: df["time"] = pd.to_datetime(df["time"])
        #          df = df.set_index("time")

        # --- Clean up ---
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]

        if path_output is not None:
            cls._save_dataframe(df, path_output)

        return df


def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    return <ClassName>DataSource.main(patient_options, database_options_specific)
```

Critical patterns:
- **Only `_load()` is required.** The base class handles `_find()`, `_format()`, and `_extract_signals()` automatically.
- Override `_find()` only if folder/file discovery needs custom logic beyond `FILE_KEYWORDS` + `FILE_EXTENSIONS`.
- Override `_format()` only if post-load transformations are needed beyond timezone/timeshift/datetime-filter (which the base class already does).
- The module-level `main()` function is required — it's the entry point called by the registry.
- For **empty data**, return `pd.DataFrame(index=pd.DatetimeIndex([], tz=<tz>))` — never a plain `pd.DataFrame()`.
- Use `@time_it` decorator on `_load()` for performance logging (import from `clinical_data_visualizer.datasource.timing`).

### Starting-point adaptations

**If the user chose (A) — existing code:**
Read their code, extract the loading logic, and adapt it into the `_load()` method. Preserve their logic but ensure the output contract (DatetimeIndex, sorted, deduplicated) is met.

**If the user chose (B) — example parquet:**
Read the parquet to understand the target schema. Write `_load()` to produce the same structure from the raw files.

**If the user chose (C) — from scratch:**
Inspect the raw files thoroughly. Write `_load()` based on what you find. Print a summary of your parsing decisions for the user to validate.

## Step 3 — Register the datasource

Edit `src/clinical_data_visualizer/datasource/registry.py`:

1. **Add the import** (alphabetical among existing imports):
   ```python
   from clinical_data_visualizer.datasource.sources.<datasource_name> import find_load_format as _<datasource_name>
   ```

2. **Add the inner class** inside `class DataSource:` (place it before `Other`, which should stay last):
   ```python
   @add_main_module(_<datasource_name>)
   class <ClassName>:
       NAME = "<datasource_name>"
       DESCRIPTION = "<Human Readable Description>"
       MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
       OPTIONS: object
   ```

3. **Add to `AVAILABLE` tuple** — insert before `Other` (which must remain last as the catch-all). Choose a logical position among the existing datasources.

## Step 4 — Add example test data

Place truncated sample files in:
```
example/example_patients/Patient_full/<folder_name>/
```

Where `<folder_name>` matches `EXPECTED_FOLDER_NAME` or is discoverable via `FOLDER_KEYWORDS`.

The example data should be:
- **Small** — keep the total under ~2 MB (the whole example directory targets ~16 MB)
- **Representative** — enough rows/columns to exercise the loading logic (at least a few hundred rows)
- **Truncated** — not full-size originals (to keep tests fast and repo lean)

If the user provided a large file, truncate it:
```python
import pandas as pd
df = pd.read_parquet("original.parquet")
df.iloc[:500].to_parquet("truncated.parquet")  # or .to_csv()
```

## Step 5 — Write tests

### 5a. Add fixture to `tests/datasource/conftest.py`

```python
@pytest.fixture(scope="session")
def <datasource_name>_cls():
    return _get_datasource_class("<datasource_name>")
```

### 5b. Create `tests/datasource/test_<datasource_name>.py`

Follow the established pattern — every datasource test file has this structure:

```python
"""Tests for <datasource_name> datasource — <brief description>."""

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, <datasource_name>_cls):
    folder = <datasource_name>_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("<datasource_name> folder not found in Patient_full")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, <datasource_name>_cls):
    file_path = <datasource_name>_cls._find(ds_folder)
    assert file_path is not None
    return <datasource_name>_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_file(self, ds_folder, <datasource_name>_cls):
        result = <datasource_name>_cls._find(ds_folder)
        assert isinstance(result, Path)
        assert result.is_file()

    def test_find_correct_extension(self, ds_folder, <datasource_name>_cls):
        result = <datasource_name>_cls._find(ds_folder)
        assert result.suffix in ("<ext1>", "<ext2>")


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_datetime_index(self, loaded_df):
        assert isinstance(loaded_df.index, pd.DatetimeIndex)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0

    def test_load_has_columns(self, loaded_df):
        assert len(loaded_df.columns) >= 1

    # Add datasource-specific load tests here, e.g.:
    # def test_load_expected_columns(self, loaded_df):
    #     assert "Paw(cmH2O)" in loaded_df.columns


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, <datasource_name>_cls):
    return <datasource_name>_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "<datasource_name>"

    def test_loaded_snapshot(self, loaded_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            loaded_df, SNAPSHOT_DIR / self._DS / "loaded.parquet", update=update_snapshots
        )

    def test_formatted_snapshot(self, formatted_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            formatted_df, SNAPSHOT_DIR / self._DS / "formatted.parquet", update=update_snapshots
        )
```

Add datasource-specific tests when the loading logic has unique behavior (e.g., waveform expansion, multi-column pivot, special datetime parsing).

### 5c. Generate initial snapshots

```bash
pytest tests/datasource/test_<datasource_name>.py --update-snapshots -m snapshot -v
```

This creates the golden parquet files under `tests/expected_results/<datasource_name>/`.

## Step 6 — Verify everything works

Run these checks in order:

### 6a. Import check
```bash
python -c "from clinical_data_visualizer.datasource.registry import DataSource; print([d.NAME for d in DataSource.AVAILABLE])"
```
Confirm the new datasource appears in the list.

### 6b. Run the datasource tests
```bash
pytest tests/datasource/test_<datasource_name>.py -v
```
All tests must pass.

### 6c. Run the full test suite
```bash
pytest tests/datasource/ -m "not snapshot" -v
```
No regressions in other datasources.

### 6d. Lint
```bash
ruff check src/clinical_data_visualizer/datasource/sources/<datasource_name>/
ruff format --check src/clinical_data_visualizer/datasource/sources/<datasource_name>/
```

### 6e. Quick smoke test with the inspect script
```bash
python scripts/inspect_patient_data.py example/example_patients/Patient_full --verbose
```
The new datasource should appear with status "ok" and list its signals.

### 6f. Validate output consistency

If the user provided expected output (option B — a processed parquet), compare:
```python
import pandas as pd
expected = pd.read_parquet("user_provided_output.parquet")
actual = ...  # load via the new datasource
pd.testing.assert_frame_equal(actual, expected, check_like=True, rtol=1e-5)
```

Report any mismatches to the user.

## Step 7 — Update documentation

Once the datasource is fully working and tested, update all relevant documentation:

The canonical location for the datasource list is the tutorial's "Patient Data & Supported
Data Sources" section. Update it plus the short list in `CLAUDE.md`:

### 7a. `docs/user_guide/tutorial.md` → *Patient Data & Supported Data Sources* (canonical)

Add one row to the **Canonical Data Source Table** (module name, folder keywords, accepted
extensions ordered by preference, discovery mode, typical signals). Do **not** duplicate the
row in any other section — other docs link here. Historically a second table existed under
an "Appendix: Supported Data Sources" heading; it has been removed — do not re-introduce it.

### 7b. `CLAUDE.md` (project root)

Add the new datasource to the **Supported Data Sources** bullet list, following the existing
one-line format:
```markdown
- `<datasource_name>` — <Description> (<file formats>); folder keyword: `<keyword>`
```
Keep the list order aligned with `AVAILABLE` in `datasource/registry.py`.

### 7c. `README.md` (currently defers to the tutorial)

The README typically links to the tutorial rather than enumerating datasources. If you see an
inline list of datasource names, update it; otherwise no change is needed.

### 7d. Example option files

If `example/option_files/` contains example `database_options.json` or `.xlsx` files that
enumerate all datasources, add the new datasource entry there too (even if just an empty
`{}` placeholder).

## Checklist — files created/modified

Print this checklist when done so the user can verify:

- [ ] `src/clinical_data_visualizer/datasource/sources/<name>/__init__.py` — created
- [ ] `src/clinical_data_visualizer/datasource/sources/<name>/options.py` — created
- [ ] `src/clinical_data_visualizer/datasource/sources/<name>/find_load_format.py` — created
- [ ] `src/clinical_data_visualizer/datasource/registry.py` — import added, inner class added, AVAILABLE updated
- [ ] `example/example_patients/Patient_full/<folder>/` — example data added
- [ ] `tests/datasource/conftest.py` — fixture added
- [ ] `tests/datasource/test_<name>.py` — created
- [ ] `tests/expected_results/<name>/` — snapshots generated
- [ ] All tests pass
- [ ] Linter passes
- [ ] Inspect script sees the new datasource
- [ ] `docs/user_guide/tutorial.md` — row added to the canonical *Patient Data & Supported Data Sources* table
- [ ] `CLAUDE.md` — Supported Data Sources bullet list updated
- [ ] `README.md` — updated only if it still enumerates datasources inline
- [ ] Example option files — updated if they enumerate all datasources

## Dependencies

If the raw data requires a library that is **not already installed** in the project (e.g., `openpyxl` for `.xlsx`, `xmltodict` for XML, `h5py` for HDF5), **ask the user before adding it**. If they approve, add the dependency to `pyproject.toml` under `[project.dependencies]` and install it in the venv with `pip install -e .`.

## Common pitfalls

- **Forgetting to add to `AVAILABLE` tuple**: the datasource won't be processed even though it imports fine.
- **`DATASOURCE_NAME` mismatch**: the decorator validates `NAME == DATASOURCE_NAME` at import time — a mismatch causes an immediate `ValueError`.
- **`Other` not last in `AVAILABLE`**: `Other` is the catch-all generic datasource and must remain the last entry.
- **Empty DataFrame without proper index**: always use `pd.DataFrame(index=pd.DatetimeIndex([], tz=...))` for empty returns, never plain `pd.DataFrame()`.
- **Missing module-level `main()` function**: the registry calls `module.main`, not the class method directly.
- **Large example data**: keep files small (~500 rows) — full datasets slow down tests and bloat the repo.
