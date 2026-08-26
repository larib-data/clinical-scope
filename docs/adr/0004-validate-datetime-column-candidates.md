# 4. Validate and rank datetime-column candidates instead of trusting names alone

Date: 2026-07-02

## Status

Accepted

## Context

Datetime-column discovery had silently drifted into **three separate implementations**:

- `io/file_utils.py`'s `find_datetime_col` / `load_csv_with_datetime_index` — name-only (exact then substring match), no content validation, and silently defaults to `df.columns[0]` when nothing matches.
- `other`'s `_detect_and_set_datetime_index` / `_try_parse_datetime_column` — its own candidate list, does validate (>50% parseable, years in `[2000, 2100]`), but excludes numeric columns outright and returns `None` on total failure.
- `syringe`'s inline detection — yet another candidate list, exact-match only, and a latent bug: on parse failure it falls through to `df.set_index(time_col)` with a comment claiming "fallback: treat as float (seconds)" that the code never actually performs, silently producing a string index.

None of the ~8 `pd.read_parquet(file_path)` call sites across per-datasource loaders check whether the loaded DataFrame already has a `DatetimeIndex` before assuming it does — correct for our own `to_parquet()` cache, but not guaranteed for a user-supplied `.parquet` source file.

Getting this column wrong is a dead end: every downstream step (resampling, timezone handling, datetime filtering, plotting) assumes the index is real time.

A real intraoperative anesthesia record export (Cerner SurgiNet/PowerChart-style schema, bound for the `other` datasource — no registered source recognizes its columns) surfaced a sharper version of this problem: a single file can have **several simultaneously-valid time columns** with genuinely different semantics — `chartTime` (clinician-charted, rounded to the second), `measurementTime` (device measurement, sub-second), `storeTime` (DB-insert time, can lag the real event by irregular minutes) — each with a `utc`-prefixed twin. All of them pass the tiered name search's lowest-confidence "contains `time`" bucket, so name priority alone can't rank them, and even a lenient sortedness gate can't either (over a 140-row single-signal sample, `chartTime` and `measurementTime` tie exactly on duplicate-count — both hit the same real quirk of the monitor reporting two readings per charting cycle — while `storeTime` looks *most* strictly-increasing in a short sample purely from DB-insert jitter, which is misleading over the full run where it turns out to be the *most* duplicated of the three).

## Decision

Consolidate into **one shared, validated detector in `io/file_utils.py`**, used by every datasource (including `other` and `syringe`) for both CSV and parquet:

1. **Short-circuit** if the DataFrame's index is already a `DatetimeIndex` (covers our own cache and pre-indexed files).
2. **Tiered name search** — one tier per exact name, in priority order, then one tier per substring pattern (also priority order) — rather than one flat "exact then substring" pass. No per-datasource override (rejected: `syringe`'s current "check `time` first" tuning is one line of evidence, not enough to justify per-source config for something content validation increasingly makes moot). The candidate set includes non-English "time" tokens (`tiempo`, `tempo`, `temps`, `zeit`), mirroring `fluxmed`'s existing `TIME_HEADER_PREFIXES` multilingual convention rather than inventing a new one.

   Bare `time` (and its translations) is deliberately excluded from the exact-name tiers, kept only in a low-priority substring tier: real device exports use it for both absolute timestamps *and* relative elapsed-seconds offsets — `fluxmed`'s own raw-format parser treats a `Time`/`Tiempo`/`Tempo`/`Temps`/`Zeit` header as elapsed seconds, added to a filename-derived `start_time` (`_load` in `datasource/sources/fluxmed_signals/find_load_format.py`). Demoting it means a more explicit name (`datetime_utc`) wins first when both are present, instead of the generic name winning purely because "exact match" outranks "substring match" as a class.

   `utc` similarly gets its own dedicated substring tier (ahead of generic `time`, behind `date`) rather than being purely a same-tier tiebreak: a `utc`-named column shouldn't have to win a uniqueness contest against a non-`utc` sibling to be picked, it should structurally outrank it. The tiebreak logic in point 4 below still matters when *multiple* `utc`-named columns land in that tier together (as in the anesthesia fixture).
3. **Content validation gates every tier**, including exact-name matches:
   - ≥90% of values parse via `pd.to_datetime(errors="coerce")` into a year within `[1990, 2100]` (widened from an initial `[2000, 2100]` to admit older device dumps).
   - ≥90% of consecutive values are non-decreasing (lenient enough to tolerate real device buffering jitter).
4. **Within-tier tiebreak, when several same-tier candidates all pass validation**: prefer higher uniqueness ratio (fewer duplicate values over the whole column — penalizes batchy/DB-artifact columns like `storeTime`), then prefer `utc`-named columns (unambiguous vs. DST-prone naive-local timestamps — mostly relevant pre-tier-4 now, e.g. disambiguating a tied `utc_datetime` vs `local_datetime` inside the `datetime` tier). Deliberately *not* implemented: a "has any sub-second variation" signal, which would correctly rule out `chartTime` (always `.000000`) — it was worth exactly as much as the uniqueness-ratio check on the real fixture (`chartTime` and `measurementTime` tied on uniqueness; only the sub-second-variation check separated them), but stacking a second heuristic to resolve a ~6-second ambiguity between two low-stakes candidates wasn't judged worth the added complexity, given `storeTime`'s multi-minute drift is the error that actually matters. If ties remain after uniqueness + `utc`-preference, first-in-column-order wins — accepted as "good enough," not "provably optimal." A winning `utc`-named column that parses tz-naive is localized to UTC on the spot (rather than left naive for a caller to guess) — cheap and unambiguous given the name already asserted it.
5. **Widen to every remaining column** (ignoring name) if all named candidates fail validation.
6. **Numeric-epoch tier, tried last**: `pd.to_datetime(col, unit="ns")` on numeric columns, gated by the same year-range + sortedness checks. Chosen over excluding numeric columns entirely because `other` (arbitrary user files) is exactly the case where a raw epoch column could show up; nanosecond-only for now since no current datasource demonstrates a need for second/millisecond/microsecond epochs, and ns magnitudes (~1.6e18) are unambiguous against real measurement data.
7. **Fail loudly** when nothing passes — raise instead of silently defaulting to `df.columns[0]`, consistent with [0001](0001-diagnose-dont-resolve-patient-folders.md)'s "diagnose, don't resolve" stance. This surfaces as a per-datasource load failure: caught by `wrapper.main`'s existing per-datasource `try/except` (skips just that datasource) and by `extract()`/`inspect()`'s own error handling — never a silent wrong time axis.

Migrated to the shared detector: `load_csv_with_datetime_index`, the new `load_parquet_with_datetime_index`, all per-datasource `pd.read_parquet(file_path)` call sites, `other`'s file-by-file loader, and `syringe`'s inline logic (fixing its latent bug as a side effect). `DataSourceBase._quick_load` (reads our own always-correctly-indexed cache) is deliberately left untouched — the short-circuit would make routing it through the shared function nearly free, but it's the hottest, most-trusted read path in the app and doesn't need the extra surface.

## Consequences

- **Easier:** one implementation to test and reason about; a wrong-column guess now fails clearly instead of silently corrupting a time axis.
- **Harder / accepted trade-offs:** raising the parse threshold from `other`'s previous 50% to 90% means some previously-tolerated messy files (mostly-garbage timestamp column) now fail outright instead of loading with a partially-broken time axis — intentional, since that was never actually useful data. Per-datasource candidate-name priority is gone; if a real device's column repeatedly loses to a wrong candidate under the universal list, revisit.
- **Explicitly deferred:** combining separate date + time columns into one datetime (no current datasource needs it). Epoch detection beyond nanoseconds (s/ms/µs) — revisit if a real datasource surfaces raw second/millisecond epoch timestamps.
- **Not fully resolved, by design:** a file with several genuinely-plausible time columns (like the anesthesia record above) may land on any of the ones that survive validation + the uniqueness/`utc` tiebreak, not necessarily the single "best" one a human would pick. Per [0001](0001-diagnose-dont-resolve-patient-folders.md)'s precedent, deep disambiguation of a badly-overloaded file is left to the user (e.g. pre-pruning columns before use), not solved inside the detector.

## Update — 2026-08-26

The detector now has a file of its own, `io/time_axis.py`, holding this rule and nothing else. It exposes two adapters over the same tiers — `detect_time_axis_in_frame` for a loaded frame, `detect_time_axis_in_parquet` for a file read only by schema and bounded sample. They must pick the same column, so they stay in one module; `_is_numeric_pa_type`'s agreement with `pd.api.types.is_numeric_dtype` is the tripwire for that.
