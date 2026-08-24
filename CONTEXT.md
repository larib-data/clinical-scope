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
- A FluxMed device yields two datasources (`fluxmed_signals`, `fluxmed_parameters`); the waveform/parameter split is a data-category distinction, not a device one (see _Flagged ambiguities_).

**Signal**:
A single measured channel sampled over time from one datasource (e.g. arterial pressure, SpO₂).
_Avoid_: field, parameter, channel, trace, series, variable
- A Signal's **raw name** is its identifier in the source data (the device's original column name); its **Label** is its human-readable display name.
- The `field_display` and `grouped_fields` keys in a `database_options` file reference Signals **by raw name**.

**Loop**:
A plot of one Signal's values against another's (X–Y) rather than against time — e.g. a pressure–volume loop. Configured via the `loop` key (which Signal pairs to pair up).
_Avoid_: cycle, P–V plot

**Spectrogram**:
A time-vs-frequency-vs-power plot of one Signal — time on x, frequency on y, power as colour (what bedside monitors call a Density Spectral Array). Configured via the `spectrogram` key (one Signal, a frequency band, and an optional colour range). EEG is the driving use case, but the plot type takes any sufficiently sampled Signal.
_Avoid_: DSA, CSA, compressed spectral array, spectral analysis (the category containing both this and the PSD, so it can't name one member)

**PSD**:
A power-vs-frequency plot of one or more Signals — frequency on x, power in dB on y, averaged over the loaded time range. Configured via the `psd` key (a list of Signals, a frequency band, and an optional dB range). Where a Spectrogram shows how rhythm evolves, a PSD shows the shape of the spectrum at rest; unlike a Spectrogram, several Signals may legitimately share one PSD subplot.
_Avoid_: power spectrum, periodogram, Welch plot, spectral analysis (see above)

**Grouping**:
The drawing of several Signals on one subplot with shared axes, configured via `grouped_fields` (within a datasource) or `global.grouped_fields` (across datasources).
_Avoid_: merge, combine

**Annotation**:
A user-created mark on a plot, persisted to `annotations.json`.
_Avoid_: label, tag, comment
- **Time event** — a vertical line at a single timestamp.
- **Time window** — a shaded interval between two timestamps.
- **Point** — a labelled marker at an (x, y) location.
- Time event and Time window need a time axis, so **Point is the only type that can be placed on a plot whose x-axis is not time** — a **Loop** or a **PSD**. This follows from the x-axis, not from being derived: a **Spectrogram**'s x-axis is still time, so it takes all three types like a plain time-series plot.

### Actions

**Inspect**:
The action that lists the Signals available per datasource (columns, point counts, time ranges) without building plots.

**Extract**:
The action that runs `find → load → format` and returns or saves the formatted DataFrame(s), no plots.

**Visualize**:
The action that runs the full pipeline to interactive Plotly figures for viewing and annotating.

_Avoid (for all three)_: process — it is ambiguous (see _Flagged ambiguities_).

### Configuration

Three tiers of options, distinguished by *what they are scoped to* — a Database, a run, or the person at the keyboard.

**Database options**:
The signal configuration shared by every Patient of a Database — labels, units, colors, Groupings, Loops. Authored once per Database and shared between users.
_Avoid_: config, settings

**Patient options**:
The per-run settings for a single Visualize/Extract/Inspect: which Patient folder, which time range, and per-datasource treatment — or, for a Source file, treatment scoped to it standalone rather than to all of `other`.
_Avoid_: run config, parameters

**User options**:
The global preferences of one person, independent of any Database or Patient — display defaults and app behavior. They are **fallbacks**: where Database options speak, Database options win.
_Avoid_: preferences, user settings, user config

**Settings**:
The UI surface that edits User options — the term for the *modal*, never for the options themselves.

**Numerics**:
The `database_options` block of per-datasource defaults — resampling period and plot priority — applied to every Signal of that datasource unless the Signal overrides them.
(Distinct from the `_numerics` datasource suffix — see _Flagged ambiguities_.)

## Relationships

- A **Database** contains one or more **Patients**, which share its `database_options`.
- A **Patient** contains one or more **Datasources** (one subfolder each).
- A **Datasource** produces many **Signals**.
- A **Loop** is derived from two **Signals**.
- A **Spectrogram** is derived from one **Signal**.
- A **PSD** is derived from one or more **Signals**, overlaid on one subplot.
- A **Grouping** draws several **Signals** on one subplot.
- An **Annotation** is attached to one plot (optionally one subplot) and may carry a **Patient** identifier when loaded across a **Database**.

## Example dialogue

> **Dev:** "For this **Patient**, the FluxMed device gives two **Datasources** — `fluxmed_signals` and `fluxmed_parameters`. To show airway pressure against tidal volume as a **Loop**, both have to be **Signals** first, right?"
>
> **Domain expert:** "Yes — pair the two **Signals** in the `loop` config. Before we **Visualize**, **Inspect** the folder to confirm the raw names are present; if you only need the data for a model, **Extract** is enough."
>
> **Dev:** "Got it. Then a clinician can drop a **Time window** over the recruitment manoeuvre — though on the P–V **Loop** itself they can only place a **Point**."

## Flagged ambiguities

- **"numerics"** names two unrelated things: (a) the `_numerics` suffix in datasource names (e.g. `mindray_respi_numerics`), a naming convention hinting at low-frequency data — not load-bearing; and (b) the **Numerics** config block (resampling-period + plot-priority defaults shared across a datasource's Signals). Resolution: keep the word for both; disambiguate by context — "the numerics block" vs "a `_numerics` source". High/low-frequency itself is just a datasource property, not a core distinction.
- **"process"** denotes two different **Actions**: the `process_patient_data.py` script performs **Extract** (no plots), while the UI's "Process visualization" button performs **Visualize**. Resolution: prefer the precise verbs **Inspect / Extract / Visualize**; avoid bare "process".
