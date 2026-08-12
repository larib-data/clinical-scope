# Contributing to Clinical Scope

Thank you for your interest in contributing! This guide covers everything you need to go from zero to a merged PR.

## Scope: what belongs in this library

**ClinicalScope derives for display; it does not interpret.**

A computation belongs here only when it is a deterministic function of signals already in the pipeline, *and* its output is something to look at rather than a conclusion to act on. The test to apply: **would this output need clinical validation before someone could trust it?** If yes, it belongs in your own analysis code, not in ClinicalScope. Even though ClinicalScope can help you through formating the data.

Inside the line: loops, unit conversion, resampling, spectrograms — re-renderings of the same samples, from which a reader draws their own conclusions. Outside it: seizure or burst-suppression detection, arrhythmia classification, automated artefact rejection, depth-of-sedation or severity indices, and any alerting.

Note that "how much maths" is not the criterion — an FFT is no more suspect than a subtraction. What matters is whether the output is a picture or a verdict.

Full reasoning, including the alternatives considered, in [ADR-0006](docs/adr/0006-no-clinical-analysis.md).

## Dev Environment Setup

1. Clone the repository:
   ```bash
   git clone git@github.com:larib-data/clinical-scope.git
   cd clinical-scope
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

3. Install the package in editable mode with dev dependencies:
   ```bash
   pip install -e .[dev]
   ```

## Running Tests

```bash
pytest                                                        # full suite
pytest tests/datasource/ -m "not snapshot"                   # fast, no golden files
pytest tests/datasource/ --update-snapshots -m snapshot      # regenerate golden files
```

See [`tests/README.md`](tests/README.md) for the full command reference.

## Linting and Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) (line length 100, double quotes):

```bash
ruff check src/     # lint
ruff format src/    # format
```

CI runs both checks — make sure they pass before opening a PR.

## Adding a New Data Source

Use the `/new-datasource` skill from within Claude Code — it walks through every step
(module skeleton, options, loader, registration, example data, tests, snapshots, docs).
For background reading, see the
[tutorial](docs/user_guide/tutorial.md) → *Patient Data & Supported Data Sources*.

## PR Process

**Branch naming:** `<type>/<short-description>` — e.g. `feat/mindray-ecg`, `fix/eit-timezone`, `docs/contributing`.

**Before opening a PR:**
- All tests pass (`pytest`)
- Linting is clean (`ruff check src/` and `ruff format --check src/`)
- New datasources include example data and snapshot tests

**PR description should include:**
- *Why* this change is needed (link the issue: `Fixes #<number>`)
- *What* changed at a high level
- *How to test* — steps a reviewer can follow to verify the behaviour
