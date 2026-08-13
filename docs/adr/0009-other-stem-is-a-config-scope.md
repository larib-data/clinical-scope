# 9. `other::<stem>` is a configuration scope, and `::` is the qualified-name separator

Date: 2026-08-13

## Status

Accepted

## Context

`other/` is the home for files that need no format-specific parsing. Until now every file in it shared a single `other` configuration block: one `time_shift`, one timezone, one trace style, one grouping, for a folder whose defining property is that its contents are *unrelated to each other*. Two CSVs exported from different machines, needing different offsets, could not both be configured — which is how three datasources that did no parsing came to exist ([ADR-0008](0008-datasource-modules-need-format-specific-parsing.md)).

The fix is to give each file its own configuration scope. That requires a name for the scope, and the name has to compose with the existing convention for naming a signal inside a datasource — `<datasource>::<raw_name>` — because `grouped_fields` and `loop` entries have to be able to point at a column of a particular file.

Three options were considered:

1. **Keep one block for `other/`, add a per-file override map** — e.g. an `overrides: {<stem>: {...}}` key inside the existing block. Avoids touching the name grammar, but creates a second, differently-shaped place where per-source settings live, and every reader of the configuration has to know about both.
2. **Generalise per-file scopes to every datasource** — `servo_u::<stem>`, `eit::<stem>`, uniformly. Symmetric and easy to explain. But it is symmetry for its own sake: for every other source the files in a folder are chunks of one recording, split by the exporting device. A per-file `time_shift` there is not a capability, it is an invitation to desynchronise one recording from itself, and it multiplies the configuration surface for a case nobody has.
3. **Per-file scope for `other/` only, reusing `::`.**

## Decision

3 **Each file in `other/` gets its own configuration scope, keyed `other::<stem>`. `::` is the one qualified-name separator, used at both levels.**

So `other::waves` names a configuration scope — one file — carrying its own `time_shift`, timezone, grouping and `trace_options`; and `other::waves::art` names a column inside it. The grammar is the same symbol at both levels, not two conventions that happen to look alike.

The asymmetry with other datasources is deliberate and is the point of recording this: **`other/` is the only source whose files are unrelated by construction.** Everywhere else, a folder is one recording. A contributor who reaches for `edf::<stem>` by analogy is generalising from the exception.

Signal references resolve in three modes, in order — qualified `datasource::raw_name`, then display name, then bare raw name (`_resolve_signal_references`, `wrapper.py`).

## Consequences

- **Easier:** an `other/` folder can hold files from unrelated machines, each configured independently, without any of them earning a module. Cross-source `grouped_fields` and `loop` entries can address a specific file's column unambiguously.
- **Harder / accepted trade-offs:** a file in `other/` named after a registered datasource makes a reference genuinely readable two ways — `other/servo_u.parquet` gives a scope whose qualified names collide with the real `servo_u` source. Both readings are legitimate, so this cannot be resolved by rule alone: the precedence order above decides, and `_warn_if_also_a_raw_name` (`wrapper.py:46-60`) logs the collision naming the losing signal and the spelling that reaches it. Silent shadowing was the alternative and was rejected.
- **Also:** signals inside `other/` are named `<stem>::<column>` rather than bare column names, so configurations written against the old single-block form need their references rewritten. This is part of the [ADR-0008](0008-datasource-modules-need-format-specific-parsing.md) migration.
- **Revisit if:** a second datasource appears whose folder genuinely holds unrelated recordings rather than chunks of one. At that point the scope mechanism generalises — but it should generalise to *that* source explicitly, not to all of them by default.
