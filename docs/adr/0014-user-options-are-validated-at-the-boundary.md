# 14. User options are validated at the boundary, never read ambiently

Date: 2026-08-26

## Status

Accepted

## Context

`~/.clinical_scope/user_options.json` is hand-editable and machine-written. Its schema rules (MIN/MAX, CHOICES, valid IANA name) were walked in two places — the settings modal on the way in, the `DisplayFallbacks` projection on the way out — and in neither case on load, so a hand-edited file reached the store raw. Two copies of one rule set, and the path that most needed them had none.

Who *may* read the file is a separate question with the same answer shape. [ADR-0011](0011-datetime-bounds-are-qualified-at-the-boundary.md) already forbids the load path resolving a user option, for determinism; nothing structurally stopped the core from reading the file directly.

## Decision

**One implementation of the schema rules, run at every boundary that accepts a value; and only boundary code may read the file.**

- `user_options.validate(raw) -> (clean, list[Correction])` is the single implementation. It is **pure** — no `Path.home()`, no file reads — which is what keeps the core structurally unable to pick up an ambient settings file.
- Corrections are returned as data, not logged, because the right reaction depends on the boundary: the settings modal discards silently (its widget re-renders showing the corrected value), `helper_api.load_user_options` logs (nobody is watching a widget).
- `DisplayFallbacks.from_user_options` converts, it does not check. The one exception is `display_timezone`, whose bad value raises inside pandas/zoneinfo rather than merely rendering oddly.
- An unknown key is **warned about and dropped**. Deliberately opposite to [ADR-0012](0012-annotation-dicts-are-an-open-schema.md)'s `extra` passthrough: the discriminator is provenance. Annotations are human-authored and get shared, so unknown keys are someone's data; user options are per-person state this app writes, so an unknown key is a value stranded under a name the schema no longer has.
- Scripts do not read the file. A setting a script needs is re-offered as an explicit flag — `inspect_patient_data.py --configured-columns-only` is the precedent.

## Consequences

- Adding a setting still costs one schema class; validation follows from its `API_TYPE`.
- The modal now refuses an inverted `spectrogram_db_min`/`max` pair on save rather than leaving the render layer to fix it, since the cross-field rule moved into `validate` with the rest.
- Corrections are testable as values instead of log prose, which no longer breaks on a reworded message.
- Distinct from [ADR-0005](0005-user-options-are-fallbacks.md): that one ranks user options *below* database options. This one is about which values are trusted, and where they may be read.
