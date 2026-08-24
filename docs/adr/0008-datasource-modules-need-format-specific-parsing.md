# 8. A datasource module is justified only by format-specific parsing

Date: 2026-08-13

## Status

Accepted

## Context

The registry had grown to twelve datasources, and three of them — `philips_waves`, `philips_numerics` and `syringe` — did no parsing. Their `_load()` was a `read_csv` or a `read_parquet`. Everything that distinguished them from each other lived in configuration: a `time_shift`, a timezone, a trace style, a grouping.

That was defensible when `other/` was a single undifferentiated bucket: every file in it shared one configuration block, so a file needing its own `time_shift` genuinely had nowhere to go but a module of its own. Per-file configuration (`other::<stem>`, see [ADR-0009](0009-other-stem-is-a-config-scope.md)) removed that constraint. Once each file inside `other/` carries its own scope, a module that only supplies configuration is a module that supplies nothing.

Leaving them cost more than the dead code. A datasource module is the unit contributors copy: the `/new-datasource` skill, the registry ordering rule, the per-source test and snapshot files, the tutorial table. Three modules whose only content was configuration taught every future contributor that "my CSV has a different time offset" is a reason to write one — which is how a registry reaches thirty entries that all call `read_csv`.

Three options were considered:

1. **Keep them.** No migration, no breakage. Accepts permanent drift between what a module means and what these three are, and keeps teaching the wrong lesson by example.
2. **Deprecate without removing** — keep them loading, emit a warning, delete later. Softer, but doubles the surface for a release or more, and in practice "later" is when someone finds the warning annoying.
3. **Remove them, and state the criterion that justifies a module at all.**

The counter-argument, raised directly in issue #74, was per-source `time_shift`: these sources genuinely did need their own offsets, and for a while that was the only mechanism available. It is answered by the same per-file scope that made the removal possible — `other::<stem>` carries `time_shift` itself, so the capability survives the module.

## Decision

3 **A datasource module is justified only by format-specific parsing. Plain CSV or parquet with a datetime column belongs in `other/`, configured per file.**

`philips_waves`, `philips_numerics` and `syringe` are removed. The criterion is stated in `CONTRIBUTING.md` and `CLAUDE.md` so it is applied before a module is written rather than discovered at review.

The test to apply: **strip the configuration away — is there any parsing left?** A vendor header to decode, an XML schema, a binary layout, a channel table, a nonstandard timestamp encoding: that is a module. A `read_csv` and a set of options is not.

Migration is supported rather than assumed. A patient folder still named after a removed source is detected and reported (`RETIRED_DATASOURCE_FOLDERS`, `constants.py:29`) instead of being silently ignored, because the failure it replaces — a folder present, no data plotted, no message — is exactly the one users cannot diagnose.

## Consequences

- **Easier:** the registry only contains modules that earn their place, and `/new-datasource` has a criterion to answer against rather than a judgement call. Three sets of module, test, snapshot and doc entries stop being maintained.
- **Harder / accepted trade-offs:** this is a **breaking change** for existing configurations, and the migration has three traps documented in the changelog — the syringe timezone default moves from `Europe/Paris` to UTC, marker traces must be restored through `trace_options`, and signals gain the qualified `other::<stem>::<column>` form. The retired-folder warning covers the case where the files were never moved, but cannot detect a config that was moved and mis-transcribed.
- **Note on [ADR-0001](0001-diagnose-dont-resolve-patient-folders.md):** its Context describes the datasource set as it was; the diagnose-don't-resolve principle it records is unaffected, and the retired-folder warning above is a direct application of it — report what is wrong, do not silently guess what was meant.
- **Revisit if:** a file format needs parsing that is genuinely trivial but genuinely format-specific. The criterion is about the *presence* of parsing, not its size; a ten-line header decoder is still a module.
