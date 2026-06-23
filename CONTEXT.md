# ClinicalScope

The domain language of ClinicalScope — a dashboard for visualizing, annotating, and extracting multi-source clinical time-series signals, primarily ICU device recordings. This glossary is the canonical vocabulary: prefer these terms (and avoid the listed aliases) in issues, code, tests, and docs.

## Language

### Core concepts

**Database**:
A group of Patients that share one set of datasource treatment and display options (`database_options`) — physically, a folder whose subfolders are patient folders.
_Avoid_: cohort, dataset, study
- Not a relational/SQL database; ClinicalScope is file-based. `batch_extract` and `load_database_annotations` operate over a Database.

**Patient**:
A single recording within a Database — one folder, with one subfolder per datasource.
_Avoid_: case, admission
- Need not be a clinical patient: any time-series subject (e.g. for machine-learning datasets).

**Datasource**:
A registered source of Signals identified by a folder-naming convention — a (device × data category) unit, not one-per-device.
_Avoid_: device, modality
- A Philips monitor yields two datasources (`philips_waves`, `philips_numerics`); the `_waves`/`_numerics` suffix is only a naming hint (see _Flagged ambiguities_).

**Signal**:
A single measured channel sampled over time from one datasource (e.g. arterial pressure, SpO₂).
_Avoid_: field, parameter, channel, trace, series, variable
- A Signal's **raw name** is its identifier in the source data (the device's original column name); its **Label** is its human-readable display name.
- The `field_display` and `grouped_fields` keys in a `database_options` file reference Signals **by raw name**.

**Loop**:
A plot of one Signal's values against another's (X–Y) rather than against time — e.g. a pressure–volume loop. Configured via the `loop` key (which Signal pairs to pair up).
_Avoid_: cycle, P–V plot

**Grouping**:
The drawing of several Signals on one subplot with shared axes, configured via `grouped_fields` (within a datasource) or `global.grouped_fields` (across datasources).
_Avoid_: merge, combine

**Annotation**:
A user-created mark on a plot, persisted to `annotations.json`.
_Avoid_: label, tag, comment
- **Time event** — a vertical line at a single timestamp.
- **Time window** — a shaded interval between two timestamps.
- **Point** — a labelled marker at an (x, y) location.
- Time event and Time window need a time axis, so **Point is the only type that can be placed on a Loop.**

### Actions

**Inspect**:
The action that lists the Signals available per datasource (columns, point counts, time ranges) without building plots.

**Extract**:
The action that runs `find → load → format` and returns or saves the formatted DataFrame(s), no plots.

**Visualize**:
The action that runs the full pipeline to interactive Plotly figures for viewing and annotating.

_Avoid (for all three)_: process — it is ambiguous (see _Flagged ambiguities_).

### Configuration

**Numerics**:
The `database_options` block of per-datasource defaults — resampling period and plot priority — applied to every Signal of that datasource unless the Signal overrides them.
(Distinct from the `_numerics` datasource suffix — see _Flagged ambiguities_.)

## Relationships

- A **Database** contains one or more **Patients**, which share its `database_options`.
- A **Patient** contains one or more **Datasources** (one subfolder each).
- A **Datasource** produces many **Signals**.
- A **Loop** is derived from two **Signals**.
- A **Grouping** draws several **Signals** on one subplot.
- An **Annotation** is attached to one plot (optionally one subplot) and may carry a **Patient** identifier when loaded across a **Database**.

## Example dialogue

> **Dev:** "For this **Patient**, the Philips monitor gives two **Datasources** — `philips_waves` and `philips_numerics`. To show airway pressure against tidal volume as a **Loop**, both have to be **Signals** first, right?"
>
> **Domain expert:** "Yes — pair the two **Signals** in the `loop` config. Before we **Visualize**, **Inspect** the folder to confirm the raw names are present; if you only need the data for a model, **Extract** is enough."
>
> **Dev:** "Got it. Then a clinician can drop a **Time window** over the recruitment manoeuvre — though on the P–V **Loop** itself they can only place a **Point**."

## Flagged ambiguities

- **"numerics"** names two unrelated things: (a) the `_numerics` suffix in datasource names (e.g. `philips_numerics`), a naming convention hinting at low-frequency data — not load-bearing; and (b) the **Numerics** config block (resampling-period + plot-priority defaults shared across a datasource's Signals). Resolution: keep the word for both; disambiguate by context — "the numerics block" vs "a `_numerics` source". High/low-frequency itself is just a datasource property, not a core distinction.
- **"process"** denotes two different **Actions**: the `process_patient_data.py` script performs **Extract** (no plots), while the UI's "Process visualization" button performs **Visualize**. Resolution: prefer the precise verbs **Inspect / Extract / Visualize**; avoid bare "process".
