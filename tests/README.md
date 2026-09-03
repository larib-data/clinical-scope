# Test Suite

Tests across unit, datasource, integration, and Dash callback layers.

## Common Commands

Activate the venv (path in CLAUDE.md) and run from the repository root.

```bash
pytest                                              # everything
pytest -m "not slow and not snapshot"               # fast run
pytest tests/datasource/                            # datasource tests only
pytest tests/unit/                                  # unit tests only
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

## Benchmarks

`tests/benchmarks/` holds performance harnesses, not tests — pytest never collects them (they aren't named `test_*.py`). Invoke one directly:

```bash
python tests/benchmarks/bench_pushdown.py --size-gb 2 --out after.json
python tests/benchmarks/bench_annotations.py --counts 100,1000,5000
```

`bench_pushdown.py` measures parquet read pruning (datetime row pushdown + column pruning) as a before/after A/B; its docstring carries the methodology and the design constraints that keep the comparison valid ([ADR-0007](../docs/adr/0007-read-time-pruning-is-an-optimization.md)). It takes minutes and gigabytes.

`bench_annotations.py` measures what a large annotation set costs to render, across three arms of the same fixture — everything drawn, labels hidden, wholly hidden — so the two visibility controls can be compared. It needs no fixtures on disk and runs in seconds. Both scripts share the same CLI shape (`--out`, `--diff`).
