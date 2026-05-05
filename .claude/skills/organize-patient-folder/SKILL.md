---
name: organize-patient-folder
description: Organize files in a folder into the correct ClinicalScope patient folder structure — one subfolder per datasource. Use this skill whenever the user wants to restructure a patient data folder, prepare a dump of clinical data files for use with the library, sort mixed files into datasource subfolders, or set up a new patient directory. Trigger on phrases like "organize patient folder", "restructure patient data", "prepare folder for ClinicalScope", "sort my clinical files", "set up patient structure", or any request to move clinical data files into proper named subfolders.
---

# Organize Patient Folder Skill

Reorganize files in a user-provided folder into the correct `ClinicalScope` patient structure: one subfolder per datasource, each named so the library can auto-discover it.

The expected structure is:
```
Patient01/
├── philips_waves/          ← one subfolder per active datasource
├── fluxmed_signals/
├── servo_u/
├── other/                  ← catch-all for unclassifiable files
└── clinical_scope_output/               ← cache folder (auto-created by the library, never touch)
```

## Step 0 — Gather context

Ask the user for:
1. **Folder path** — required (may be a single patient folder or a parent folder containing multiple patients)
2. **Move or copy?** — always ask. Moving is clean but destructive; copying is safe but duplicates data.

If both are already clear from context, proceed without asking.

## Step 1 — Load datasource configs from the library

Run this to get the authoritative datasource list (folder keywords, file keywords, extensions):

```bash
source /Users/alexis/Codes/clinical_visu_venv/bin/activate && python3 - <<'EOF'
import json
from clinical_scope.datasource_list import DataSource

result = []
for ds in DataSource.AVAILABLE:
    opts = ds.OPTIONS
    result.append({
        "name": getattr(opts, "DATASOURCE_NAME", ds.NAME),
        "expected_folder": getattr(opts, "EXPECTED_FOLDER_NAME", ds.NAME),
        "folder_keywords": getattr(opts, "FOLDER_KEYWORDS", []),
        "file_keywords": getattr(opts, "FILE_KEYWORDS", []),
        "file_extensions": [e.lstrip(".").lower() for e in getattr(opts, "FILE_EXTENSIONS", [])],
        "multi_file": getattr(opts, "MULTI_FILE", False),
    })
print(json.dumps(result, indent=2))
EOF
```

Save this output — it is the ground truth for all classification decisions. Never hardcode datasource names: always use this live data so newly added datasources are automatically supported.

If the venv import fails (library not installed), fall back to reading each `src/clinical_scope/*/options.py` directly and extracting the constants manually.

## Step 2 — Detect scope and scan files

**Auto-detect single vs. batch mode:**
- **Single patient**: the folder contains data files directly, or its immediate subfolders look like datasource folders (names matching known keywords)
- **Batch**: the folder's immediate subfolders look like distinct patient directories (each containing files or datasource-like subfolders)

Confirm the detected mode with the user before scanning.

**Scan**: For each patient folder (one in single mode, N in batch mode), recursively list all files, building a flat list of absolute paths. Exclude:
- Anything inside `clinical_scope_output/` — this is the library cache, never touch it
- Hidden files and folders (names starting with `.`)

## Step 3 — Classify each file

Apply this decision tree to every file. The goal is to minimise user interruptions by being confident when the evidence is strong and asking only when it is genuinely ambiguous.

### A — Parent folder already implies a datasource

If the file's direct parent folder name contains **all** the keywords of exactly one datasource (case-insensitive substring match), mark the file as **already in place** — report it but don't move it. If it matches multiple datasources, treat as ambiguous (→ D).

### B — Extension uniquely identifies a datasource

Some extensions belong to only one datasource across the whole library (e.g., `.sta` → `servo_u`, `.asc` → `eit`, `.xml` → `mindray_scope`). If the file extension maps to exactly one datasource: **assign with high confidence**.

### C — Extension + filename keywords

Among datasources whose `file_extensions` list includes this file's extension:

1. Score each candidate: count how many of its `file_keywords` appear as substrings in the lowercased file stem — **but only count keywords that are ≥ 5 characters long**. Short generic keywords like `"data"`, `"wave"`, `"num"` exist in the library for same-folder disambiguation and produce false positives when used across datasources.
2. Pick the candidate with the highest score.
3. If the top score > 0 and no other candidate shares that score: **assign with high confidence**.

### D — Ambiguous or no match

If no candidate matches, or two or more candidates tie: **ask the user** (see Step 4).
Files with extensions not found in any datasource's list are treated as "other" — still confirm with the user once in Step 4.

Build a classification table: `file_path → {datasource_name, confidence: "auto" | "ask"}`.

## Step 4 — Resolve ambiguous files interactively

Collect all files marked `confidence: "ask"` and present them together (not one-by-one) so the user can decide in one pass. Show only the datasources whose `file_extensions` include the file's extension, plus `other` and `skip`:

```
Ambiguous files — please assign each one:

  1. raw_data_20240101.csv  (200 KB)
     Candidates: philips_waves · philips_numerics · fluxmed_signals · other · skip

  2. unrecognised_format.bin  (4 KB)
     Candidates: other · skip

Enter: 1=philips_waves, 2=other  (or use numbers from the list above)
```

Use `AskUserQuestion` for this — present all ambiguous files in a single question when feasible.
If the user selects `skip`, exclude the file from the plan entirely.

## Step 5 — Show the plan and confirm

Before touching anything, print a full summary grouped by target subfolder:

```
Organization plan for: /path/to/Patient01
Operation: COPY

  philips_waves/
    ├── patient_data_wave.parquet      [auto: unique extension match]
  servo_u/
    ├── recording.sta                  [auto: unique extension match]
  fluxmed_signals/
    ├── signals_2024.txt               [auto: keyword score 2]
  other/
    ├── mystery.csv                    [user: "other"]

  Already in place (not moved):
    └── eit/recording_001.asc
    └── eit/recording_002.asc

  Skipped (user choice):
    └── temp_notes.txt

N files to COPY into M datasource folders.
Proceed? [yes/no]
```

Do not proceed until the user confirms.

## Step 6 — Execute

For each (file → target datasource) pair in the confirmed plan:

1. Create `<patient_root>/<expected_folder_name>/` if it doesn't exist.
2. Copy or move the file. Use `shutil.copy2` (preserves metadata) for copy, `shutil.move` for move. Skip hidden files (names starting with `.`) even if encountered inside source folders.
3. If a file with the same name already exists in the target folder, pause and ask: **overwrite**, **rename** (append `_1`, `_2`, …), or **skip**.

After all files are processed, print:

```
Done. Copied/Moved N files into M datasource folders.
```

## Step 7 — Offer next steps

After organizing, suggest:
- **Inspect signals**: `python scripts/inspect_patient_data.py <patient_folder> --verbose`
- **Generate database options**: use the `generate-database-options` skill
- **Run the app**: `python src/clinical_scope/dash_api/core_api.py` and load the folder

---

## Classification reference (derived from Step 1 — do not hardcode)

The classification logic in Steps 2–4 must always be driven by the live output of Step 1. The table below is for human orientation only and will drift as the library evolves:

| Datasource | Unique extension? | Reliable file keywords (≥5 chars) | Known ambiguities |
|---|---|---|---|
| `philips_waves` | — | `waveform`, `timeseries`, `philips` | Generic names like `data_waves_*.parquet` → ask user |
| `philips_numerics` | — | `philips_numeric`, `philips` | `*numerics.parquet` ties with mindray_respi_numerics → ask user |
| `eit` | `.asc` ✓ | — | Unique extension — always auto |
| `fluxmed_signals` | `.txt` (shared) | `signals`, `signal`, `fluxmed` | `Parameters.txt` disambiguates from fluxmed_signals |
| `fluxmed_parameters` | `.txt` (shared) | `parameters` | `Signals.txt` disambiguates from fluxmed_parameters |
| `servo_u` | `.sta` ✓ | — | Unique extension — always auto |
| `mindray_scope` | `.xml` ✓ for xml; `.csv` ambiguous | — | `.csv` mindray files (e.g., `Art-*.csv`) → always ask user |
| `mindray_respi_waves` | — | `respi_wave`, `resp_wave`, `mndry_wave`, `mndry` | `mndry_waveform*.parquet` → auto |
| `mindray_respi_numerics` | — | `respi_numeric`, `resp_numeric`, `mndry_numeric`, `mndry` | `mndry_numerics*.parquet` → auto |
| `syringe` | — | `syringe`, `seringues` | Reliable if filename contains "syringe" |
| `other` | catch-all | — | — |

## Edge cases

- **Batch mode**: process each patient subfolder independently, showing one confirmation plan per patient.
- **Files already in correctly named subfolders**: report as "already in place", never move them.
- **`clinical_scope_output/`**: always skip, never modify — it is the library's internal cache.
- **No files found**: report and exit gracefully.
- **Permission errors**: report the offending file and skip it; continue with the rest.
- **`.txt` ambiguity between fluxmed_signals and fluxmed_parameters**: use filename keyword scoring (`parameters` vs `signal`/`signals`). If still tied, ask the user.
- **`mindray_scope` `.csv` files**: mindray_scope has no FILE_KEYWORDS, so its `.csv` files (e.g., `Art-*.csv`, `ECG_*.csv`) are always ambiguous — they compete with many other datasources. The skill will ask the user; if mindray_scope files are already in a subdirectory, use folder keywords to classify them instead.
- **Short/generic keywords like `"data"`, `"wave"`, `"num"` are intentionally excluded** from scoring (< 5 characters). They exist in the library's FILE_KEYWORDS for within-folder disambiguation and would cause false positives across datasources.
