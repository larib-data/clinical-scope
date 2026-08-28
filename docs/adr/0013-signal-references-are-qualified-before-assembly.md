# 13. Signal references are qualified before assembly

Date: 2026-08-26

## Status

Accepted — implemented in `plot_assembly.py` ([#89](https://github.com/larib-data/clinical-scope/issues/89)).

## Context

`database_options` lets a plot be configured in two places. A group whose signals come from one datasource is written in that datasource's own section (`icca.grouped_fields`); a group spanning several is written in `global.grouped_fields`. The same split exists for `loop`, and does not exist at all for `spectrogram` and `psd`, which are per-datasource only.

Nobody authors that distinction deliberately. The XLSX derives it — a group lands in `global` iff its signals span more than one datasource — so a spreadsheet author writes a group name in a column and never sees the scope. The two formats do not even agree on what is expressible: the `loops` sheet always writes a per-datasource loop, so a global loop is reachable only from hand-written JSON.

Despite reading as a naming convention, the split carried real semantics. The per-datasource path matched a reference against that datasource's signals by bare `raw_name` equality; the global path resolved through the three-mode chain (qualified name → display name → raw name) against every loaded signal. So the same group, written the two ways, resolved by different rules. And because the third mode of that chain returns **every** raw-name match, a bare reference evaluated globally pulls in a signal of the same name from every datasource — the per-datasource section was silently acting as a namespace qualifier.

Two suppression bugs grew in the gap. Deciding which signals get a default one-signal-per-plot group was done twice, by two mechanisms, both keyed on `raw_name` strings:

- an accumulator that was never reset between datasources, so a raw name appearing in an earlier datasource's `grouped_fields` suppressed an identically-named signal in a later one, with load order fixed by `DataSource.AVAILABLE`;
- a post-hoc filter that removed single-signal groups whose `raw_name` appeared in a global group — again by string, so one datasource's grouped `HR` removed *every* datasource's single `HR`.

`raw_name` is unique only *within* a datasource. Any collection keyed on it across datasources is a namespace collision waiting for the right patient folder, and shared vitals names (`HR`, `SpO2`, `ABP`) make that folder ordinary rather than exotic. The failure mode is a silently missing plot, not an error.

The post-hoc filter also reached across a module boundary to dictate naming: `Signal.psd_from_signal` qualified its `raw_name` as `psd_name::label` explicitly so the filter would not swallow the PSD. A derived plot had to disguise its name to survive a rule in another module.

## Decision

**Config scope is desugared at exactly one point, and downstream of it every signal reference is qualified.**

`assemble_plot_groups` flattens every per-datasource section into qualified global references (`icca.grouped_fields.Vitals: [HR]` becomes `Vitals: [icca::HR]`) as its first step, and builds an internal value rather than writing back. Each reference is *resolved before it is qualified* — through the three-mode chain, against that datasource's own signals — so the section keeps scoping the candidates rather than merely prefixing the string, and `[Heart Rate]` desugars to `[icca::HR]` as readily as `[HR]` does. A reference that resolves to nothing is qualified all the same, so it cannot fall through and match a namesake elsewhere. Nothing after that pass knows local scope exists. There is one resolution path, one suppression rule, and one spelling of a reference — extending [ADR-0009](0009-other-stem-is-a-config-scope.md), which established `::` as the qualified-name separator, into a full internal normal form.

Both config spellings stay valid. The desugaring is a property of the code, not of the file format: no parser changes, no config migration, and the per-datasource section keeps its authoring advantages — locality with the rest of a source's config, and no repetition of the datasource name per signal.

The pass must run at the head of assembly rather than at config-parse time, because the `other` datasource adds a group per file to its own section during load — one it derives from the columns that actually loaded, which no reader of the config file could. By the time assembly runs — once, after every datasource has loaded — that writeback is already present.

An `other::<stem>` section is the same rule one level down, and desugars in the same pass ([#91](https://github.com/larib-data/clinical-scope/issues/91)). One difference: a file stem is prefixed *lexically*, before resolution, where a datasource name is appended after it. An `other` signal's `raw_name` already carries its stem, so `waves` + `art` is the raw name `waves::art`, which the datasource level then resolves and qualifies as any other; resolving the bare name first would depend on whether that column happened to be labelled. The entry's own name keeps its stem too — it is the only thing telling two files' plots apart, where a datasource name is not something a clinician reads.

**Group membership joins on signal identity, not on `raw_name`.**

Memberships are resolved first; the `Signal` objects that land in any group that produces a plot are collected; default single-signal groups are then built only for input signals absent from that set. The join is on identity rather than count: a group that resolved to one signal still takes it, or that signal would be plotted twice — once under the group's name and once under its own. This replaces both string-keyed mechanisms at once. Derived signals — loop, spectrogram, PSD — are newly constructed objects that were never in the input list, so they cannot be identity-matched and are structurally immune to suppression, with no naming disguise required.

## Consequences

- A datasource's `grouped_fields` can no longer suppress a same-named signal belonging to a different datasource. Two independent bugs disappear together, because both were symptoms of the same string join.
- `Signal.psd_from_signal` keeps its `psd_name::label` raw name — it still distinguishes two PSD traces built from one source signal with different parameters — but for that reason alone. The cross-module coupling is gone and the comment citing it no longer applies.
- Per-datasource `grouped_fields`, `loop` and `spectrogram` gain the three-mode resolver, scoped to their own datasource. This is a strict widening: mode three *is* the bare `raw_name` match they did before, so nothing that resolved stops resolving, and a display name now resolves where it silently matched nothing.
- A group resolving to exactly one signal keeps the **group's** name. Both paths previously gave the *signal's* name — per-datasource by rebuilding it through `PlotGroup.from_single_signal`, global by leaving the default plot standing — and the group name is the one that degrades continuously: the same config gives a `Pressure` panel whether the recording has four signals or one, instead of a title that depends on how much data happened to load.
- Grouping and derived-plot construction become reachable with in-memory `Signal` objects and a literal config dict, with no patient folder on disk. That is the point: the cross-datasource collisions above cannot be expressed by the single demo patient the integration suite runs against, so they were untestable where the logic previously lived.
- **Accepted cost:** the desugaring is invisible in the config file. A reader of `database_options.json` sees two spellings and must know they mean the same thing. That is the price of not breaking existing files, and it is recorded rather than hidden — [#88](https://github.com/larib-data/clinical-scope/issues/88) tracks collapsing the surface itself along an ingestion/presentation seam, which this ADR makes safe to do later as a parser-and-docs change with no risk to assembly logic.
- **Deliberately not decided:** whether assembly's log-and-continue failures should become a reported result. Nothing consumes such a list today, and the resilience is intentional — one bad `database_options` entry must not blank a clinician's screen.
