---
name: new-datasource
description: Add a brand-new data source module to the ClinicalScope project. Use this skill whenever the user wants to integrate a new medical device, file format, or signal source into the pipeline. Trigger on phrases like "add a datasource", "new data source", "integrate X device data", "support a new file format", or any request to support a new datasource.
---

# New Datasource Skill

Add a complete, production-ready datasource module by **mirroring the closest existing source**. The 11 existing datasources already encode every pattern this skill needs to cover — the skill's job is to route correctly and remind you of the cross-cutting concerns (registration, tests, snapshots, docs).

## Step 0 — Gather materials and identity

**Materials.** Ask the user what they have. **At least one of (1) or (2) is required**; (3) is optional but valuable. Warn user about PHI exposure.

1. **Raw example data folder** — sample files from this datasource.
2. **Existing parsing code** — a script or notebook that already reads this format into a DataFrame. Faithful spec of the file format; sometimes richer than a sample because it encodes edge cases.
3. **Expected processed output** (optional) — a parquet/CSV of what the data should look like after loading. Used in Step 8 to show the user a summary of what the new code produced on it.

**Identity.** Then ask once, proposing defaults from the materials when possible:

- `DATASOURCE_NAME` (snake_case) — also the registry `NAME` and the `database_options` key.
- Human-readable description (e.g., `"Hamilton Ventilator"`).
- `FOLDER_KEYWORDS` (case-insensitive substrings matched against the per-source subfolder name).
- `EXPECTED_FOLDER_NAME` (usually same as `DATASOURCE_NAME`).
- `FILE_KEYWORDS` (most-specific first) and `FILE_EXTENSIONS` (preferred format first).

If a required library is missing (e.g., `xmltodict`, `h5py`), ask the user before adding it to `pyproject.toml`.

## Step 1 — Inspect the materials

Read whichever materials the user provided (raw files, parsing script, or both). Identify:
- File format (CSV delimiter, parquet schema, XML structure, binary layout).
- Datetime column(s) — name, format, timezone — or note its absence.
- Signal columns — names, dtypes, units (often embedded, e.g. `"Paw(cmH2O)"`).
- Any special structure (waveform expansion, long-format pivot, header blocks).

If only a script was provided, derive the schema from how the script reads and shapes the data; flag any field whose dtype or semantics is ambiguous from code alone.

## Step 2 — Classify and validate

Summarise the data across these five axes in plain user-facing language:

1. **File multiplicity** — single file picked, or all matching files loaded and concatenated?
2. **Raw format** — clean tabular (loads with a single `read_csv` / `read_parquet`) or custom parser needed?
3. **Reshape** — already 1 column per signal, or needs pivot/melt from long to wide?
4. **Datetime handling** — column already present, reconstructed from a reference + offset, or absent (user supplies it via `patient_options`)?
5. **Complexity** — minimal `_load`, or also need to override `_find` / `_format`?

Ask the user to confirm or correct line-by-line. Natural conversational correction is fine — no verbatim form needed.

**Do not proceed until the user has validated this classification.** Wrong classification here cascades into wrong reference code in Step 3 and is expensive to undo later.

## Step 3 — Pick the reference module(s)

Internal — **do not show this table to the user**. Use it to choose which existing module(s) to read before writing code.

**Primary** (structural backbone — copy this module's `options.py` layout and `_load` skeleton):

| Raw format / complexity | Primary |
|---|---|
| Plain CSV/parquet, datetime column present, one signal per column | `philips_waves` |
| Long-format, needs pivot to wide | `mindray_respi_numerics` |
| Custom text parser (header blocks, metadata sections) | `servo_u` |
| Custom binary/XML/less-structured | `eit` |

**Secondaries** (consult only for the specific pattern; max 2):

| If your data also needs... | Add |
|---|---|
| Multi-file load + concat | `servo_u` |
| Pivot from long to wide (primary doesn't pivot) | `mindray_respi_numerics` |
| Datetime reconstructed from a reference time + relative offset | `servo_u` |
| Custom `_find` (folder/file discovery beyond keywords) | `eit` |
| No datetime in raw data — user supplies it via `patient_options` | `eit` |

Read the relevant datasource `options.py` and `find_load_format.py` in full.

## Step 4 — Implement

Create three files under `src/clinical_scope/datasource/sources/<datasource_name>/`:

- `__init__.py` — empty (or single-line docstring).
- `options.py` — copy the constants layout from the primary; change `DATASOURCE_NAME`, `EXPECTED_FOLDER_NAME`, `FOLDER_KEYWORDS`, `FILE_KEYWORDS`, `FILE_EXTENSIONS`, `MULTI_FILE`, `FILE_NAME_DATAFRAME_LOADED`, default timezone, and `DEFAULT_DATABASE_OPTIONS`. Keep `source_options`, `DatabaseOptionsAdditionalInformations`, and `PatientOptionsDataSourceRelative` only if your primary has them.
- `find_load_format.py` — copy the primary's class skeleton; adapt `_load` to your file format. Override `_find` / `_format` only if Step 2's classification flagged the need.

Critical contracts:
- `_load` returns a `pd.DataFrame` with a sorted, deduplicated `DatetimeIndex` and numeric signal columns.
- `_load` signature: `(cls, file_path: Path, path_output, **kwargs)` when `MULTI_FILE=False`, `(cls, file_path_list: list[Path], path_output, **kwargs)` when `MULTI_FILE=True`. The base class dispatches based on the option.
- Empty data: return `pd.DataFrame(index=pd.DatetimeIndex([], tz=<tz>))` — never plain `pd.DataFrame()`.
- A module-level `main(patient_options, database_options_specific)` is required — the registry calls it, not the class method.
- Decorate `_load` with `@time_it` from `clinical_scope.datasource.timing`.

## Step 5 — Wire it in (other files to touch)

Beyond the three new files in `src/clinical_scope/datasource/sources/<name>/`, edit these existing files. The pattern for each is obvious from inspection — mirror existing entries.

- **`src/clinical_scope/datasource/registry.py`** — import the new module, add an inner class to `DataSource`, append it to `AVAILABLE` **before `Other`** (`Other` must stay last). `NAME` must equal `DATASOURCE_NAME` — the decorator raises at import time if not.
- **`tests/datasource/conftest.py`** — add a session-scoped `<datasource_name>_cls` fixture.
- **`docs/user_guide/tutorial.md`** → *Patient Data & Supported Data Sources* canonical table — add a row.
- **`CLAUDE.md`** → *Supported Data Sources* bullet list — add a bullet, list order aligned with `AVAILABLE`.

Conditional — update only if the file currently enumerates all datasources:
- `README.md`, `example/option_files/*`.

## Step 6 — Example data

A small example in `example/demo_database/demo_patient/<folder_name>/` is required before merging the PR — deferrable to a follow-up commit, but blocks merge until present. `<folder_name>` must match `EXPECTED_FOLDER_NAME` or be discoverable via `FOLDER_KEYWORDS`.

**Always ask the user explicitly:** *"Can the raw data be committed as an example, or do we need to anonymize / synthesize?"* Never assume PHI status from filenames or folder names alone. (Note: Step 1 inspection can read sensitive raw data freely — only the committed example needs to be clean.)

Three paths depending on the answer:

- **Shareable raw data** — truncate to ~500 rows / under 2 MB and drop into the folder.
- **Identifiable data (PHI)** — de-identify first (the `/anonymize-timeseries` skill handles this), then truncate.
- **No raw data, or user defers PHI handling** — synthesize a minimal sample from Step 1's schema knowledge (column names, dtypes, datetime cadence, value ranges). Ask the user to confirm the synthetic file matches their format before committing it.

**Never replace the example with full-size originals.** The test fixture `patient_full_path` (defined in `tests/conftest.py`) points at `demo_patient`.

If no example exists at all, Step 7's snapshot regen and Step 8's inspect smoke test will report the new source as "file not found" — acceptable for a draft PR, blocks merge.

## Step 7 — Tests

Copy `tests/datasource/test_<primary>.py` to `tests/datasource/test_<datasource_name>.py` and rename every `<primary>` reference. Add datasource-specific tests only where the loading logic has unique behavior. Then generate snapshots:

```bash
pytest tests/datasource/test_<datasource_name>.py --update-snapshots -m snapshot -v
```

## Step 8 — Verify

```bash
python -c "from clinical_scope.datasource.registry import DataSource; print([d.NAME for d in DataSource.AVAILABLE])"
pytest tests/datasource/test_<datasource_name>.py -v
pytest tests/datasource/ -m "not snapshot" -v
ruff check src/clinical_scope/datasource/sources/<datasource_name>/
python scripts/inspect_patient_data.py example/demo_database/demo_patient --verbose
```

If the user provided an example of the expected processed output, also load it via the new datasource and **show the user a short summary of what the code produced on it** (column names, row count, head, time range). Do not assert formally — let the user judge.

## Step 9 — Tell the user which reference was used

Once everything is in place, mention the primary for transparency:
> "Modeled on `<primary>`. To compare, see `src/clinical_scope/datasource/sources/<primary>/`."

## Common pitfalls

- **Missing from `AVAILABLE`** — datasource is invisible even though it imports cleanly.
- **`DATASOURCE_NAME` ≠ registry `NAME`** — the decorator raises `ValueError` at import time.
- **`Other` not last in `AVAILABLE`** — it's the catch-all and must remain final.
- **No module-level `main()`** — the registry calls `module.main`, not the class method.
- **Empty DataFrame without a `DatetimeIndex`** — always `pd.DataFrame(index=pd.DatetimeIndex([], tz=...))`.
- **Oversized example data** — keep files ~500 rows; full datasets slow tests and bloat the repo.

## Files changed checklist

- [ ] `src/clinical_scope/datasource/sources/<name>/__init__.py`
- [ ] `src/clinical_scope/datasource/sources/<name>/options.py`
- [ ] `src/clinical_scope/datasource/sources/<name>/find_load_format.py`
- [ ] `src/clinical_scope/datasource/registry.py` (import, inner class, `AVAILABLE`)
- [ ] `example/demo_database/demo_patient/<folder>/` — example data
- [ ] `tests/datasource/conftest.py` — fixture added
- [ ] `tests/datasource/test_<name>.py` — copied from primary and adapted
- [ ] `tests/expected_results/<name>/` — snapshots generated
- [ ] `docs/user_guide/tutorial.md` — table row added
- [ ] `CLAUDE.md` — Supported Data Sources bullet updated
- [ ] `README.md`, `example/option_files/*` — updated only if they enumerate sources
- [ ] All tests pass, `ruff check` clean, smoke test sees the new datasource
