# 7. Read-time pruning is an optimization, never a filter

Date: 2026-08-13

## Status

Accepted

## Context

Loading dominated run time and memory on large recordings. Two obvious wastes: every column was read off disk even when `field_display` named three of forty, and every row was read even when `datetime_start`/`datetime_end` narrowed the run to ten minutes of an eight-hour recording. Parquet can avoid both at read time.

The tempting version of this is dangerous, because the load path is not a private detail:

- **The window is not known in its final form at read time.** `time_shift` is applied *after* load, and timezone resolution and timestamp validation happen downstream too. A bound computed from the user's window before those steps does not describe the same instants the user asked for.
- **`_load()` output is cached.** Its result is written to `clinical_scope_output/` and reused when `quick_load` is set. Anything run-scoped that reaches a cache-writing `_load()` poisons that cache for every later run with a different window.

So the question was not "can we read less" but "what is allowed to decide which rows exist". Three options were considered:

1. **Exact pushdown** — push the precise datetime window into the parquet reader and treat the result as the data. Fastest, and wrong: because of the shift/timezone ordering above, rows that belong in the window are dropped before anything can notice. The failure is silent, produces a plot that looks perfectly normal, and is invisible in a diff of the output. In a tool clinicians read numbers off, silent row loss is the worst available failure mode.
2. **Column pruning only** — read every row, keep only the named columns. Safe, and leaves most of the win on the table: the row count, not the column count, is what makes a long recording expensive.
3. **Loose pushdown, authoritative filter** — read a deliberately conservative superset of the window, and leave the existing `_filter_by_datetime` as the only thing that decides membership.

A second question rode along: should `inspect()` push down too? Issue #66 argued no, on grounds specific to what inspect is for. Inspect reports *% retained* — how much of the file the configured window keeps. That number is by definition a comparison against the unwindowed file. Push the window into the read and inspect reports 100% every time: not a wrong number so much as a meaningless one, and one a user would reasonably trust.

## Decision

3 **Read-time pruning is an optimization, never a filter. It may make the read cheaper; it may never change which rows the pipeline considers.**

Concretely:

- Pushdown bounds are computed deliberately loose — a buffer either side, `time_shift` inverted — so the read returns a superset (`base.py:140-160`). `_filter_by_datetime` stays the sole authority on membership.
- `inspect()` passes `patient_options=None`, which yields no row filter at all (`base.py:222-236`). Inspect still prunes *columns*, which cannot change a row count and so cannot make its own statistic circular.
- A source opts in by declaring `ALLOW_DATETIME_PUSHDOWN` in its options module (`base.py:93-95`); the gate is centralised rather than repeated per call site.

Two properties made this the choice:

- **Correctness must not depend on arithmetic being exact.** Under option 3 a bounds bug costs speed, never data. Under option 1 the same bug costs data, silently. Given the ordering hazards above, that difference is the whole decision.
- **The cheap 80% is most of the win.** The benchmark (`tests/benchmarks/bench_pushdown.py`) exists to keep this honest: a loose window that reads slightly too much captures nearly all of the saving that an exact one would.

## Consequences

- **Easier:** a new reader can adopt pushdown by declaring one flag, without having to reason about whether its bounds are precisely right. The cache stays run-independent, so `quick_load` remains safe to leave on.
- **Harder / accepted trade-offs:** the window now exists in two forms — loose bounds for the read, the authoritative filter downstream — and they must stay consistent. `tests/benchmarks/bench_pushdown.py` guards the performance half; the correctness half rests on the superset property, so **any change that tightens the bounds must preserve it**.
- **Relationship to [ADR-0004](0004-validate-datetime-column-candidates.md):** that ADR decided a datetime column is only accepted once its *content* parses. Column pruning means the validator may now see a narrower set of candidate columns than the file contains, since a column not named in `field_display` is never read. The rule is unchanged; its input is smaller.
- **Revisit if:** a format arrives whose index guarantees make exact bounds provably safe — then exact pushdown is worth it *for that source*, declared per source, and never as a global default.
