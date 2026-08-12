# Test Suite

Tests across unit, datasource, integration, and Dash callback layers.

## Common Commands

```bash
# Activate venv first (see CLAUDE.md for the venv path)
source <venv_path>/bin/activate
```

```bash
# Set working directory
cd ~/Codes/ClinicalScope
```

### Run everything
```bash
pytest
```

### Fast run (skip slow & snapshot tests)
```bash
pytest -m "not slow and not snapshot"
```

### Datasource tests only
```bash
pytest tests/datasource/
```

### Unit tests only
```bash
pytest tests/unit/
```

### With coverage
```bash
pytest --cov=clinical_scope --cov-report=term-missing
```

## Where Fixture Data Lives

| Path | Holds |
|---|---|
| `tests/data/patients/` | Test-only patient folders (`Patient_difficult_format` — varied/awkward file formats) |
| `tests/data/option_files/` | Test-only configs (`example_database_options.json` / `.xlsx`) |
| `tests/expected_results/` | Golden `.parquet` outputs, one folder per datasource |
| `example/demo_database/demo_patient/` | The **shipped demo**, reused as the `patient_full_path` fixture |

The last row is the one deliberate reach out of `tests/` — exercising the demo users actually receive means the suite fails if that demo ever breaks. Everything else under `example/` is user-facing only and no test should depend on it.

Running the suite writes a `clinical_scope_output/` parquet cache inside the patient folders it reads. That directory is gitignored and excluded from release bundles, so it is safe to delete at any time.

## Snapshot (Golden-File) Tests

Snapshot tests compare `_load` and `_format` output against committed `.parquet` reference files in `tests/expected_results/`.

```bash
# Run snapshot tests only
pytest -m snapshot

# Regenerate golden files after an intentional data/logic change
pytest tests/datasource/ --update-snapshots -m snapshot
```

> After regenerating, review the diff with `git diff tests/expected_results/` (binary files — use parquet tooling) and commit the updated files if the change is intentional.

## Markers

| Marker | Meaning |
|--------|---------|
| `slow` | Long-running tests (full pipeline, batch extract) |
| `snapshot` | Golden-file content regression tests |

Deselect example: `pytest -m "not slow and not snapshot"`
