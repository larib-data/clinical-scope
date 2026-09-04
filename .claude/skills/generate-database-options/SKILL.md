---
name: generate-database-options
description: Bootstrap a database_options workbook for a patient data folder by inspecting its datasources and signals, then proposing a filled, ready-to-prune .xlsx (or .json). Use when the user wants to generate, create or bootstrap a database_options / signal config for a patient folder, or asks what signals a folder holds and how to configure them.
---

Bootstrap a `database_options` config from a patient data folder.

**Transcribe the names, propose the rest.** Signal names must come through the inspection CSV character-exact — a device spells them `MDC_PRESS_AWAY-MDC_DIM_CM_H2O` and a typo is a plot that never appears. Everything else is a guess, and guesses go in the file: deleting a spreadsheet row is trivial, whereas adding one means getting four columns right in a file the user is afraid of breaking. **A sparse workbook is the failure mode, not a full one.**

**XLSX is the authoring format.** Clinicians edit spreadsheets, not JSON. Always build the workbook; convert to JSON only when asked (Step 7).

## Step 0 — Gather context

Ask for, unless already clear:
1. **Patient folder path** (required)
2. **Output path** (default: `<patient_folder>/database_options.xlsx`)
3. **JSON as well?** (default: no)
4. **Existing database_options to filter by?** (optional — restricts inspection to known datasources)

## Step 1 — Inspect the folder

```bash
python scripts/inspect_patient_data.py <patient_folder> \
    [--database-options <existing_path>] \
    --output-csv <scratch>/inspection.csv \
    --verbose
```

Read the CSV. Relevant columns: `datasource`, `status`, `raw_name`, `raw_point_count`.

Skip rows where `status != "ok"` or `raw_name` is empty, and name the skipped datasources to the user — a source that failed to load is a source the config will silently omit.

A signal that loaded with `raw_point_count` 0 is empty in *this* time window, not absent from the file. Keep it, and name it in Step 5 — along with any loop or frequency view built only from such signals, which will render blank until the window widens.

The `datasource` value goes into the workbook verbatim, `other::<stem>` keys included: `OtherDataSource.inspect()` already reports one entry per file.

## Step 2 — Read what each name says

For each `raw_name`, pull out two things and keep them — Step 4 runs on both:

- **The unit.** `"Name(unit)"` → `label = "Name"`, `unit = "unit"` (`"Paw(cmH2O)"`, `"RR(bpm)"`). No match, or several parenthetical groups → leave both cells empty. Leave `label` empty where it would only repeat `raw_name`. A parenthetical placeholder meaning *dimensionless* — `-` above all, as in `"SpO2(-)"` — is not a unit: leave the cell empty, or Step 6 flags it.
- **The quantity the name refers to**, whether or not the name spells a unit. Many devices use no parentheses at all: IEEE-11073 codes (`MDC_PRESS_AWAY-MDC_DIM_CM_H2O`), vendor prefixes (`MNDRY_*`), and bedside abbreviations in any language (`FC`, `PEP`, `débit`). Decoding these is in scope and expected — most of a patient's signals may arrive this way, and Step 4 runs on the quantity, not on the `unit` cell. Say in Step 5 which readings were decoded rather than transcribed.

## Step 3 — Transcribe the `signals` sheet

Read the workbook's shape from the two live sources rather than from memory — a plot type registered since this skill was last touched brings its own sheet:

```bash
# Which sheets exist, and what each one requires
python -c "from clinical_scope.plot_types import registry as r; [print(d.SHEET_NAME, sorted(d.SHEET_REQUIRED_COLUMNS)) for d in r.AVAILABLE if d.SHEET_NAME]"

# Column order of every sheet, from the demo workbook (shape only, not a model config)
python -c "import openpyxl;wb=openpyxl.load_workbook('example/demo_database/database_options.xlsx');[print(w.title,[c.value for c in w[1]]) for w in wb.worksheets]"
```

Write with `openpyxl`, header row bold on a `D9D9D9` fill. One row per signal, in CSV order, `raw_name` copied character-exact. Add a sentinel row (`signal = *`) for a datasource only when it carries something: `timezone`, `priority`, or a trace-style column.

Leave unset cells empty, and write no explanatory rows or hint keys: `_check_unknown_keys` warns on anything the schema does not know.

## Step 4 — Propose, generously

Fill the plot-type sheets and the `groups` column now. Do not ask first — an unwanted row costs one delete, a missing one costs the user an edit they may not attempt. Where two readings are plausible, **write both** and let Step 5 settle it.

- **Group by quantity.** Signals measuring the same thing within one datasource belong on one subplot. The quantity is what groups them, not the literal `unit` string: `ml/s` and `l/min` are both flow, and a signal whose unit cell is empty still has a quantity you decoded in Step 2. Reuse the *same group name* under two datasources and the parser lifts it into `global.grouped_fields` by itself — that is how a clinician compares one quantity across two devices, and it is worth proposing wherever a quantity appears in more than one source. Write bare names; the parser adds the `other::<stem>::` prefix itself wherever a bare one would not resolve.
- **Split what the name distinguishes.** Airway and esophageal pressure share `cmH2O` and are clinically distinct; so are a raw channel and its derived percentage. When a name token separates a sub-family, give it its own group rather than merging.
- **A pressure and a volume in one datasource is a loop.** Write the `loops` row. For a loop whose two signals live in different devices, `global` is a legal `datasource` value — name the signals qualified (`servo_u::Airway Press. (cmH2O)`).
- **Electrophysiological channels get a frequency view.** Every EEG/EMG channel earns a `spectrograms` row and a `psds` row, the PSD rows sharing one group name so the channels overlay. Other fast waveforms — ECG, arterial pressure, plethysmography — are a real judgment call: name them in Step 5 as candidates rather than silently deciding either way.
- **Colour by quantity, consistently across devices.** Pressures one colour, volumes another, flows another. This is what makes a cross-device group readable.
- **Range where the quantity is unambiguous.** A y-range that clips is worse than none, so this is the one place to prefer the obvious cases and say in Step 5 that they want checking.

Leave a sheet empty only when nothing in this patient fits it, and say so in Step 5.

## Step 5 — Walk the user through it, then listen

Present the filled draft. Every item must **name signals from this patient** — a question like "any PV loops?" hands the work back and is the thing this step exists to avoid.

- Number the **decisions** — the groups, the loop rows, the frequency views — not the transcribed signal rows, which run to hundreds and carry no judgment. Group them by sheet so the user can answer "drop 3 and 7".
- Say plainly that rejecting a proposal means deleting its row, so they need not reply about everything.
- Flag everything the earlier steps marked as a guess, decoded, empty or left out.

Take the reply, revise the workbook, and report only what changed. Keep going until the user is done — this is a conversation about a draft, not a form submitted once.

## Step 6 — Validate

The workbook is not finished until this reports zero issues:

```python
from pathlib import Path
from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options
from clinical_scope.database_options_parser import validate_database_options

options = xlsx_bytes_to_database_options(Path(output_path).read_bytes())
for issue in validate_database_options(options):
    print(f"[{issue.severity}] {issue.path}: {issue.message}")
```

Use the `_bytes_` variant: `xlsx_to_database_options` drops a stray `<stem>_from_xlsx.json` beside the user's file.

An `info` issue always means a redundant cell — a `label` repeating `raw_name`, a `unit` of `-`. Clear that cell; never drop real configuration to silence one.

Check the parsed result back against the CSV: every group and loop resolved to signals that exist, and nothing was dropped between the two.

## Step 7 — JSON, only if asked

Generate it from the workbook, never by hand — the direction the repo uses for its own example:

```python
import json

Path(json_path).write_text(
    json.dumps(options, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
)
```

## Reference

Every column, its scope and its default: `docs/user_guide/tutorial.md` → *database_options.xlsx*. `example/demo_database/database_options.xlsx` shows all four sheets populated — read it for structure, not as a model of good clinical config.

Not in the tutorial: **a signal reference resolves three ways** (`signal_reference.resolve_signal_references`) — qualified `datasource::raw_name`, then display name, then raw name. Qualify whenever one raw name lives in two datasources.

## Before finishing

- [ ] Every `raw_name` in the workbook is character-exact against the CSV
- [ ] Every plot-type sheet either has rows, or was reported empty with a reason
- [ ] Every signal sharing a quantity with another is in a group, or was reported as deliberately left out
- [ ] `validate_database_options` returns zero issues
- [ ] Report: N datasources, N signals, every datasource whose `status` was not `ok`, and which signals still want a human — the unparsed labels and the guessed ranges
