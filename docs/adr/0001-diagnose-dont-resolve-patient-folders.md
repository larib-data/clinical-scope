# 1. Diagnose, don't resolve, unstructured patient folders

Date: 2026-05-31

## Status

Accepted

## Context

A Patient is, by convention, one folder with one subfolder per datasource (see `CONTEXT.md`). When a user points the app at a folder that violates this — files dumped loose in the root, or sitting in a subfolder whose name matches no datasource's `FOLDER_KEYWORDS` — `DataSourceBase._find_folder` finds no match, every datasource returns `[]`, and the run yields **nothing with no error**. First-time users (especially with a single datasource) cannot tell whether the tool is broken or their folder is wrong. This silent emptiness is an adoption barrier.

The tempting fix is to *auto-resolve*: virtually map the loose files to datasources and process them in place. We examined this and found it structurally limited:

- The generic `other` datasource can only load **already-tidy** `.csv`/`.parquet` (in practice: `philips_waves`, `philips_numerics`, `syringe`). Every other source needs its specialized `_load()` — all Mindray sources require **pivoting** (long → wide), and `eit` (`.asc`), `servo_u` (`.sta`), `mindray_scope` (`.xml`), and `fluxmed` (`.txt`) parse non-tidy formats the generic engine cannot read.
- A specialized loader can only be auto-selected safely when the file's **extension is unique** (`.asc`/`.sta`/`.xml`). For ambiguous `.csv`/`.parquet` the correct datasource is genuinely undecidable without human input — the same reason the on-disk `organize-patient-folder` skill asks the user.
- Therefore auto-resolve can never cover the csv-but-needs-pivoting sources, and silently auto-plotting the tidy minority with raw column names and no grouping risks a *worse* first impression than an empty screen.

A clear message, by contrast, needs only to *notice* unplaced files — never to parse or classify them — so it covers 100% of datasources and formats.

## Decision

We will **diagnose, not resolve**. When a run produces zero results, a shared diagnostic helper (alongside `detect_datasource_from_folder` in `datasource/registry.py`, reusable by both the Dash UI and the CLI scripts) will:

- scan the patient root **plus one level** into immediate subfolders, skipping `clinical_scope_output/` and dot-folders;
- report any files matching the union of all datasources' `FILE_EXTENSIONS`, grouped by location;
- explain the expected one-subfolder-per-datasource layout and point to the `organize-patient-folder` helper for moving files;
- do **no** per-file datasource guessing.

The message is rendered in both the Process path (`process-status`) and the Inspect modal. It fires **only on a zero-result run**, which also sidesteps the cache landmine that a naive "folder has no subfolders" trigger would hit (the `clinical_scope_output/` cache appears after the first run).

We will **not** add an in-pipeline auto-resolve layer. Physically moving/copying files remains the job of the separate, human-confirmed `organize-patient-folder` skill.

## Consequences

- **Easier:** first-time users get an actionable explanation instead of silence, for every datasource and format. No third copy of the file-classification logic (it lives only in the Organize skill, where a human confirms). Inform never mutates the user's clinical data, so it carries no data-loss risk.
- **Harder / accepted trade-offs:** a newcomer with a flat folder still has to organize it (or run the helper) before anything plots — we are *not* making the messy folder "just work." Users who want zero-touch loading of loose files are deliberately not served in the app; they must structure the folder first.
- **Revisit if:** the datasource mix shifts heavily toward already-tidy `.csv`/`.parquet`, or per-file metadata makes unambiguous classification reliable — at which point an opt-in "plot loose files generically" escape hatch could be reconsidered as a *secondary* feature, never the default.

## Update — 2026-06-18 (as built)

The *decision* above (diagnose, never resolve) holds unchanged. The *mechanism* settled differently once built, because the two surfaces have different firing moments:

- **Dash (interactive):** validates **at input time**, not on a zero-result run. A live preview under the patient-folder field reflects what the typed/pasted path contains as the user types (`_build_data_folder_preview` in `dash_api/callbacks/data_callbacks.py`, shipped in commit `1ea3f72`). This heads off the wrong folder *before* Process/Inspect runs, so we deliberately do **not** also add a zero-result message to `process-status` or the Inspect modal.
- **CLI (non-interactive):** diagnoses **at outcome time** — on a zero-result run of the inspect / process-patient / visualization scripts, emitted as a `logger.warning` **and** to stderr (regardless of `--verbose`). Batch does not print the full diagnostic per patient.

Both surfaces render from **one shared discovery helper** in `datasource/registry.py`, with two tiers:

- a **cheap core** (safe to call on every keystroke): classify the path, detect device subfolders, name unrecognized subfolders;
- an opt-in **deep mode** (CLI-only): also enumerate loose data files matching the union of `FILE_EXTENSIONS`, grouped by location — the file-reporting this ADR's Decision called for, kept off the Dash hot path for performance.
