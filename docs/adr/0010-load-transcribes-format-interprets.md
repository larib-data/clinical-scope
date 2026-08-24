# 10. `_load` transcribes, `_format` interprets

Date: 2026-08-24

## Status

Accepted

## Context

`_load()`'s return value *is* the parquet cache: it is written to `clinical_scope_output/` and read back verbatim whenever `quick_load` is set. So anything `_load` resolves from configuration outlives the setting that produced it. Change the setting, and the next run reads a cache built under the old one.

The failure is silent in the worst way. A timezone baked into the cache is indistinguishable at read time from a timezone the file carried — the index is tz-aware either way, so `apply_timezone_to_dataframe` early-returns and the user's `additional_informations.timezone` override can never reach that data again. The plot is drawn, the numbers are wrong by an offset, and nothing in the output says so. The same shape applies to a `field_display` pre-filter: a signal added to the config after the cache was written is a column the cache never had, and the run reports no error — just a missing trace.

An audit of the nine registered sources found this in three of them, plus two latent copies:

- `fluxmed_parameters` and `fluxmed_signals` stamped `tzinfo=UTC` onto the filename-derived start time inside `_load`.
- `mindray_scope` localized its CSV branch inside `_load`.
- `mindray_respi_numerics` and `mindray_respi_waves` were **data-dependent**: their index was built with `tz=str(base_timezone) if base_timezone is not None else DATA_SOURCE_DEFAULT_TIMEZONE`. The demo file parses tz-aware, so only the compliant branch ever ran; a naive file would have taken the `else` and frozen `Europe/Paris` into the cache. Runtime auditing scored both as clean.
- `eit` violated the rule through a different option entirely, passing `field_display` into its `.asc` parser.

Two sources already obeyed the rule without it being written down: `edf` anchors an undated recording in `_format` (`edf/find_load_format.py:120-121`), and the `eit` cache deliberately carries a **float64 index** of fractional days (`eit/find_load_format.py:348-349`) because the `DatetimeIndex` is built from the `day` patient option, which must not be frozen. The rule generalises an existing practice rather than inventing one.

Three framings were on the table:

1. **"Cached data keeps, but never adds, timezone info."** True and sufficient for every violation found, but it answers only the option that happened to be audited. `recording_start`, `day` and `field_display` are the same bug wearing different clothes, and the next option nobody has thought of yet will be too.
2. **Audit at runtime.** Load the demo data, inspect the frames, score each source. This is what was tried first, and it scored `mindray_respi_*` compliant — it can only ever exercise the branches the fixture data reaches.
3. **A general rule with a mechanical form.**

## Decision

3 — **`_load` transcribes; `_format` interprets. The cache must be reproducible from the source file alone: no option may be resolved inside `_load`.**

The rule binds exactly the sources that cache (`ALLOW_QUICK_LOAD=True`). `other` opts out of caching, so it is out of scope by construction.

Its useful form is mechanical and greppable. Inside any `_load`:

- no reference to `DATA_SOURCE_DEFAULT_TIMEZONE`
- no call to `apply_timezone_to_dataframe`

`DATA_SOURCE_DEFAULT_TIMEZONE` counts as configuration even though it is a constant: it is *the default of an overridable option*, and a default frozen into the cache is indistinguishable at read time from a user's choice frozen into it. Both put the data permanently out of reach of the override. `tz=DATA_SOURCE_DEFAULT_TIMEZONE` in `_load` is the same bug as a hardcoded `tzinfo=UTC`, spelled differently.

`tests/datasource/test_load_config_independence.py` enforces the general property the grep cannot: for each caching source it calls `_load` twice with configs differing in `field_display` and the timezone override and asserts the frames are equal. It catches a future `day` or `time_shift` leak, and unlike a snapshot it works on a *new* source — a new source's golden would simply record its violation as the expected result.

### `mindray_scope`: fail loudly on a mixed folder

`mindray_scope` reads both `.csv` (naive) and `.xml` (offset-bearing, e.g. `Time='2004-09-15T08:12:33.000+01:00'`), and merges them at `pd.concat(df_list, axis=1)`. Localizing the CSV branch inside `_load` is what made a folder holding both work at all — pandas raises `TypeError: Cannot compare tz-naive and tz-aware timestamps` on the mix. That behaviour was never designed; it was a side effect of the violation.

Mixed folders are not a supported case and never were. Both branches now keep raw fidelity and a folder yielding both raises with a message naming the two files, rather than being silently rescued by a rule violation.

## Consequences

- **Easier:** `quick_load` is safe to leave on. A cache written under one config is valid under every other, so changing a timezone, a `day`, or a signal list needs no cache invalidation and no user to know one exists. Reviewing a new `_load` is two greps.
- **The timezone override is unreachable for genuinely tz-aware sources.** `mindray_respi_numerics`, `mindray_respi_waves` and `mindray_scope`'s XML branch carry real offsets in their raw data, so `apply_timezone_to_dataframe` early-returns and their `DATA_SOURCE_DEFAULT_TIMEZONE` is effectively dead config. This is the "keeps, never adds" half of the rule working as intended: the file's own answer beats the config's. `apply_timezone_to_dataframe` logs a warning when an override is ignored this way.
- **`eit` re-parses all 70 `.asc` columns.** Measured on the demo file (3.29 MB, 11 718 rows): parse 0.38 s instead of 0.08 s, cache 0.881 MB instead of 0.306 MB. Extrapolated to a 5-hour recording the cache is roughly a third of the source `.asc` it derives from, in both the sparse demo regime and a fully dense one. The penalty is paid once, on the fresh load — the run where `quick_load` is not in play.
- **Read-time column pruning cannot recover that on `eit`.** *(No longer true — see the Update below.)* `read_parquet_pruned` resets `columns_to_read` to `None` whenever the cache has no resolvable datetime axis (`io/file_utils.py:568-571`), which is permanently true of EIT's float64 index. Consistent with [ADR-0007](0007-read-time-pruning-is-an-optimization.md) — pruning is an optimization, so declining to prune is always safe — but it means the full cache is also fully read.
- **`base.py`'s `configured_field_display` machinery is now permanently unnecessary.** It exists to stop `inspect(configured_columns_only=True)` narrowing a cache-writing `_load` via EIT's pre-filter. Under this rule no source may pre-filter, so the guard can never fire. Left in place; flagged for removal as a separate change.
- **Revisit if:** a format arrives whose parse genuinely cannot proceed without an option — a binary layout whose channel table is only in the config, say. The answer then is to widen what counts as source-derived, not to let the option into the cache.

## Update — 2026-08-24 (as built)

The rule holds unchanged. Two of the Consequences above have since been acted on.

**Column pruning now reaches `eit`.** The bullet saying it cannot was accurate when written, and is what motivated the follow-up: `read_parquet_pruned` reset `columns_to_read` to `None` for any cache whose index is not a *timestamp*, which EIT's float64 index will never be. The fix infers nothing new about the index — it takes the fact from provenance. `_quick_load` passes `index_is_time_axis=True`, because a cache is a file we wrote and this ADR already guarantees its index is the time axis. Every other caller is unchanged, `other` included: it still reads too many columns when detection declines, because there is a fact to rely on for our own file and none for a user's. The declaration unlocks column pruning only — a non-timestamp axis is not range-comparable, so no row predicate is ever built against it, which makes EIT's `ALLOW_DATETIME_PUSHDOWN = False` structural rather than merely configured.

**Deriving a column is not resolving an option.** EIT's `%Local N = Local N / Global` moved from `_format` into `_load`, so the percentages land in the cache and pruning can select them — a `field_display` naming `%Local 1*` previously matched nothing, the column not existing on disk. This is not a loosening. The test is whether the value could differ between two runs over the same source file: a ratio of two parsed columns could not, so it is transcription, the same category as `time_hours`, which `_parse_asc_table` has always derived inside `_load`. A timezone, a `day`, a `field_display` all could, and stay barred. `_format` no longer calls the helper at all: a cache written before this change has no `%` columns, and pruning would then select nothing for a `%Local N*` pattern — a back-fill there would work only when `Global` happened to be selected alongside. Rather than carry a guarantee that holds by luck, caches are treated as disposable: after an application update, un-tick *Re-use data if already loaded once* once, and the next run writes a complete cache.

**The demo cache trades size for read width.** It grows 0.881 → 1.341 MB (four derived float columns, which compress poorly), while a configured read of it drops from all 71 columns to 9 of 75. The cost is paid once on the fresh load; the saving on every `quick_load` run after it.
