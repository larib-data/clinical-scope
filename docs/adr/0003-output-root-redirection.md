# 3. Redirect output to a writable root, keyed by patient name

Date: 2026-06-30

## Status

Accepted

## Context

Every artifact ClinicalScope generates — the parquet quick-load cache, `annotations.json`, the saved `database_options.json` / `patient_options.json`, and `visualization.html` — is written to `<patient_folder>/clinical_scope_output/`. The patient folder is also where the *raw* data lives. When that folder sits on a read-only mount (a shared clinical data store, a read-only export), the first write fails and the patient cannot be visualized, annotated, or cached at all.

The fix is to let output land somewhere writable, outside the data folder. The design question is the *mapping*: given a (possibly read-only) patient folder, how do we compute its writable output location? Three sub-decisions drove the shape:

1. **Literal vs root.** The override could name the output folder *directly* (files land exactly there), or name a *root* under which we derive a per-patient location. Literal is simpler and lowest-surprise for a single patient — but in the UI the natural workflow is "set one scratch dir and open patients into it," and with a literal path, opening a second patient into the same field **silently overwrites the first patient's annotations** — minutes of irrecoverable clinical work lost to a forgotten field edit.

2. **Auto-detection.** A "smart" variant would inspect the supplied path and decide whether it already looks patient-specific. There is no reliable way to tell `/work/patientx/` from `/work/jan2026/`, so this produces unpredictable nesting and was rejected outright.

3. **Nested vs flat leaf.** Given root semantics, the per-patient location could be nested (`<root>/<patient>/clinical_scope_output/`) or a flat suffix (`<root>/<patient>_clinical_scope_output/`).

## Decision

**An optional `output_root` patient option. When set, output goes to `<output_root>/<patient_name>/clinical_scope_output/`, where `patient_name` is the data folder's name. When unset, behaviour is unchanged (`<patient_folder>/clinical_scope_output/`).** No auto-detection: one uniform rule.

`output_root` is a first-class UI field (not only a key in an uploaded `patient_options.json`), because the UI's "reload last" reads the saved options *from inside the output folder* — to find that file under redirection you need the root before you can read it, so the root must be user-supplied up front, exactly like `data_folder`.

The resolution lives in the single existing chokepoint, `_get_output_folder`: the current behaviour falls out as the `output_root is None` branch, and the `clinical_scope_output` leaf is reused verbatim in both modes.

Three properties made this the choice over the alternatives:

- **Safety over ergonomics (root, not literal).** Deriving a per-patient subfolder makes cross-patient overwrite structurally impossible within a Database. A literal path edged out root semantics on single-patient ergonomics, but the silent-data-loss failure mode is not worth that small convenience.
- **Familiarity (nested, not flat).** `<root>/<patient>/clinical_scope_output/` reproduces the exact layout users already know from in-folder mode, rehomed — not a new naming convention to learn. The byte-for-byte identical `clinical_scope_output` leaf also keeps the `assemble_bundle` ignore pattern working for free.
- **Batch and Database-wide reads come free.** Because the per-patient leaf is derived from `data_folder` (which `batch_extract` already overrides per patient) rather than configured, batch extraction needs no collision-handling code. And because the nested layout makes `output_root` *structurally a Database folder*, `load_database_annotations(output_root)` works unchanged — the flat variant would have broken it.

## Consequences

- **Easier:** read-only data mounts are now usable for visualize / extract / inspect / annotate, single-patient and batch alike, by setting one option. Output for many patients collects under one browsable root that mirrors the Database structure.
- **Harder / accepted trade-offs:** output is one directory level deeper than the folder the user named — a one-time "why is it nested?" surprise, accepted as the cost of overwrite safety. The per-patient key is `Path(data_folder).name`, so two *different* Databases each containing e.g. `patient_01` pointed at the **same** `output_root` would still collide; documented as "one `output_root` per Database."
- **Revisit if:** users need to redirect output for Databases with colliding patient-folder names under a shared root — at which point the key would need to incorporate more of the data-folder path, not just its name.
