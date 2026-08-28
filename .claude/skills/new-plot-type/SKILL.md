---
name: new-plot-type
description: Add a new kind of plot to ClinicalScope — a way of drawing signals that is not a line against time. Use when the user wants to add a plot type or asks for a "new kind of plot", when they describe a drawing the app cannot make yet ("plot X against Y", "against frequency", "as a heatmap"), or to decide whether a proposed drawing is a plot type at all.
---

# New Plot Type

`plot_types/` already makes the classic failure impossible: a type missing half its code is an
ImportError at start-up, never a config that validates cleanly and renders nothing. So this
skill is not a checklist against that. Its job is the two things the code cannot decide — **is
this a plot type at all**, and **what maths does it draw** — plus the periphery a package lands
in but does not contain.

Two words carry the skill. A **delta** is what a type declares differently from a line against
time; every default in `PlotTypeSchema` is `time_series`, so a derived type states only its
deltas. A **contract** is what a half of the package owes the rest of the app, and each half
owes something different because of who may import it.

## Step 1 — Find the delta

This both decides whether to build anything and configures what gets built. Four flags
discriminate. Answer each for the drawing the user described, proposing your own answer, and
put the set to them:

| Flag | The question it answers | `time_series` |
|---|---|---|
| `TIME_AXIS` | Is x an instant in time? | `True` |
| `GRID_LAYOUT` | Do its subplots pack side by side in a square grid, rather than one per row? | `False` |
| `HAS_COLORBAR` | Does a trace carry a colour scale? | `False` |
| `POINT_TIMESTAMPS` | Does every point still know when it was recorded, though x is not time? | `False` |

`RESAMPLED` and `UNIFIED_HOVER` are `False` on all three existing types, so they say "I am
derived" rather than what makes this one different. Set them; never gate on them.

**Four answers matching the `time_series` column is no delta, and no plot type.** Then say
this, and stop:

> What you want is new maths on a signal, still drawn against time and sharing a zoom with the
> signal it came from — a compliance curve, a moving average. There is no home for that today:
> every builder sets its own `schema=`, and nothing builds a derived Signal that renders
> *as* a time-series. Making it a plot type would park it on a page section of its own, away
> from its source. This is a gap worth an issue, not a package.

When the answers will not resolve — the user is describing a drawing you cannot picture —
invoke `/grilling` before going further.

**Done when:** four answers, at least one of them a delta, confirmed by the user.

## Step 2 — Route to the closest package

Internal — do not show this table. Read both halves of the package it names before writing.

| Its delta | Read |
|---|---|
| x is another signal's values; points keep their timestamps | `loop` |
| time on x, but colour carries a third dimension | `spectrogram` |
| x is a derived axis, several signals overlaid on one subplot | `psd` |

Read `tests/plot_types/fake/` as well. It is the smallest complete type — two short files, a
config entry that is a bare string — and `tests/plot_types/test_fake_plot_type.py` drives it
through all six paths a real one takes.

## Step 3 — Write the leaf (`schema.py`)

The leaf's **contract**: it imports nothing above `constants`. `signal_container` reads the
capability flags and may never import a `plot.py`, so a flag must be readable without one.

- `NAME` and `SECTION_KEY`, the same string — the registry refuses them spelled differently.
- The deltas from Step 1. Leave every flag that matches `time_series` unwritten.
- `Config` — the keys one entry may set, each with the comment saying why it is optional or
  required. Omit it entirely when an entry is not a dict of options at all: a `loop` entry is
  a bare `[x_signal, y_signal]`.
- `KNOWN_KEYS` — those keys as a frozenset; empty when there is no `Config`.
- `validate_entry()` — returns `ValidationIssue`s and never raises. `error` for a shape that
  cannot build, `warning` for an unknown key.
- `map_refs()` — the config with every signal reference rewritten through `map_ref`. One walk
  per config shape; a malformed config is returned untouched for validation to report.
- `SHEET_NAME`, `SHEET_REQUIRED_COLUMNS`, `read_sheet()` — only if the type is authorable in
  the xlsx. The sheet columns and the JSON keys are one schema in two spellings, which is why
  they are declared in the same file.

**Done when:** `validate_entry` and `map_refs` each handle the malformed config as well as
the good one.

## Step 4 — The maths — STOP HERE

`plot.py` is an **adapter**, not a maths module. `spectrogram_from_signal` calls
`spectral.spectrogram()` and spends its whole body wrapping the result into `Data` →
`PlotOptions` → `TraceOptions` → `Signal` → `RenderSpec`. **Scaffold the adapter; never invent
the maths.** A plot type is a way of drawing; what it computes is a clinical claim, and that
is the user's to make.

Put both of these to the user before writing anything in Step 5:

1. **The maths function.** They supply it, name an existing one, or dictate it. Either home
   works and neither is preferred: a leaf module of its own beside `spectral.py` when it is
   substantial and testable on plain arrays, or inline in `plot.py` when it is a handful of
   lines — `loop_from_signals` interpolates two signals onto a common time base in ten.
2. **Its refusal.** The exception it raises to mean a deliberate, reportable "no" rather than
   a bug — `spectral.SpectralRefusalError` for a grid too short or decimated,
   `PlotTypeArityError` for the wrong number of references. `plot_assembly` grades an
   *undeclared* exception as a crash with a full traceback, so an undeclared refusal is logged
   as a bug the first day a clinician meets it.

Invoke `/grilling` here when the maths has real choices to settle — parameters a user would
tune, whether the source signal has to be regridded, or a condition it can refuse on. Skip it
when there are none.

**Done when:** the maths function exists — written, named, or pointed at — and its refusal
exception type is declared.

## Step 5 — Write the top (`plot.py`)

The top's **contract**, which is where the import cycle shows through:

- `build(all_signals, name, config) -> Signal` (or a list, to overlay one subplot): resolve
  the references, call the Step 4 maths, wrap what comes back.
- Resolve with `resolve_one` rather than a lookup of your own. Its `SourceSignalNotFoundError`
  is already graded as a warning, so a config naming a signal that never loaded reports as the
  config problem it is.
- Guard the source with `require_time_series()` — a derived plot derives from a raw signal.
- Set `PlotOptions(schema=<Schema>, …)` — the class, not its name. This is what puts the plot
  on its own page section, and it is also how every capability question about it gets answered
  downstream: the render layer reads `schema.GRID_LAYOUT`, never a name.
- **Push** the rendering with `RenderSpec`: a `hover_template` when the trace is a Scatter, a
  `trace_factory` when it is not one at all (a spectrogram is a `go.Heatmap`).
  `to_plotly_trace` cannot reach into the package to pull it.
- `BUILDER = PlotBuilder(build=build, refusals=(<the Step 4 exception>,))`.

Two things cost more than a package, because they are shared mechanism rather than plot type.
An axis payload that is neither x nor y is a field on `Data` (`point_time_axis` and
`spectrogram_freq_axis` are the two). A user-tunable display default is a `UserOptions` class
in `constants.py` plus a `DisplayFallbacks` field. Raise either with the user before adding it.

## Step 6 — Register

- `plot_types/registry.py` — import the schema, insert it into `AVAILABLE` at the position it
  should hold on the page, top to bottom.
- `plot_types/builders.py` — import the plot half, add `Schema: plot.BUILDER` to `BUILDERS`.

Nothing else in `src/` changes. `tests/plot_types/test_boundaries.py` fails if a shared module
learns the new type's name, which is the signal that something belongs in the package instead.

## Step 7 — Land the periphery

The package is guarded by the registry; what surrounds it is not. Three of these go red on a
type that exists only in code:

- `example/demo_database/database_options.xlsx` — configure one plot of the new type over demo
  signals, then **regenerate the json from it**; `tests/unit/test_example_assets.py` prints the
  one-liner. Pick signals the plot is honest on, not merely present.
- `docs/user_guide/tutorial.md` — a heading naming the type, under *Configuration File
  Reference*. The `` `spectrogram` Block `` and `` `spectrograms` sheet `` sections are the
  shape: the keys, a JSON example, and what each field does, in clinician-facing language.
- `CONTEXT.md` — a `**Name**:` entry under *Core concepts*, with the `_Avoid_` line naming
  what it should not be called.

The last two answer to nothing but this skill, which is what makes them the ones that rot:

- `tests/plot_types/test_<name>.py` — mirror the Step 2 reference package's test file.
- `CLAUDE.md` — the derived-type list in *Config files*.

## Files changed checklist

- [ ] `src/clinical_scope/plot_types/<name>/__init__.py`
- [ ] `src/clinical_scope/plot_types/<name>/schema.py` — the leaf, deltas only
- [ ] `src/clinical_scope/plot_types/<name>/plot.py` — the adapter, plus its `BUILDER`
- [ ] the maths — its own leaf module, or inline in `plot.py`
- [ ] `src/clinical_scope/plot_types/registry.py` — import + `AVAILABLE`
- [ ] `src/clinical_scope/plot_types/builders.py` — import + `BUILDERS`
- [ ] `example/demo_database/database_options.{xlsx,json}` — configured, json regenerated
- [ ] `docs/user_guide/tutorial.md` — a heading and its section
- [ ] `CONTEXT.md` — glossary entry
- [ ] `CLAUDE.md` — derived-type list
- [ ] `tests/plot_types/test_<name>.py`
