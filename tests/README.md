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
