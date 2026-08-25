# 11. Datetime bounds are qualified at the boundary

Date: 2026-08-25

## Status

Accepted

## Context

`datetime_start` / `datetime_end` cut the window every pipeline honours. They are strings, and a naive one (`2004-09-15 08:20:00`) is not a moment in time until something says which clock it was read off. Either each consumer answers that from the reader's `display_timezone`, or the boundary that produced the bound answers it once.

The code already did the latter and nowhere said so, while the naming argued for the former: `DISPLAY_TIMEZONE` served as both the default of the `display_timezone` user option and the timezone naive bounds are read in. An architecture review duly read the load path, concluded it was wrongly ignoring the user's setting, and proposed reversing the decision.

What it missed is that the UI qualifies at Submit — `data_callbacks.py` bakes the Settings timezone into both fields before saving, and `rerender_datetime_on_timezone_change` rewrites the visible digits when that setting changes so the stored instant holds. Both load-path sites, `_pushdown_bounds._to_aware` and `filter_data_by_timestamps`, localize only when `tzinfo is None`, so their fallback is unreachable from the app entirely.

It is reachable from the CLI scripts (none pass `user_options`), from `extract_datasource` / `batch_extract`, and from hand-edited files. Resolving a user option there would mean two colleagues running the same script over the same folder get different rows, because one of them once typed a different timezone into a GUI.

## Decision

**A bound is qualified once, at the boundary that produced it. No consumer re-qualifies an already-qualified bound; an unqualified one is read in a fixed constant, never in a user option.**

- The UI is a boundary: naive form text becomes an instant at Submit, in the user's `display_timezone`. **This is what makes the Settings timezone govern the window** — not a load-path lookup.
- Scripts and library callers are boundaries too. One wanting a specific clock passes an aware bound.
- The load path is not a boundary. It localizes naive bounds in `cst.NAIVE_BOUND_TZ`, so `extract_*` output depends only on the folder and option files given to it.

`NAIVE_BOUND_TZ` is a separate literal from `DISPLAY_TIMEZONE`, not an alias, though both are `"Europe/Paris"` — aliasing would let a change to the app's display default silently reinterpret every script's bounds, which is the coupling this ADR forbids.

An explicit timezone argument on the load path was rejected: it buys nothing on the UI path (bounds arrive aware) and nothing on the script path (an aware bound already says it), while widening a signature [ADR-0010](0010-load-transcribes-format-interprets.md) had just narrowed.

## Consequences

- The app behaves as users expect and the library as scripts expect, with no conflict between them — one rule seen from two ends, not a compromise between two rules.
- `filter_data_by_timestamps` takes `naive_bound_tz`, not `display_timezone`; `resolve_display_timezone` gained a `fallback` so the load path's invalid-name branch cannot land on the display default. Load-path tests monkeypatch the new name, which distinguishes the two concepts in tests for free.
- **Accepted cost:** a hand-written naive bound is read as `Europe/Paris`, not its author's setting. The app never writes such a file; the fix is to write an offset.
- Adjacent to [ADR-0005](0005-user-options-are-fallbacks.md) but distinct — that one ranks user options below database options for *display*; this one keeps them off the load path entirely, a question of determinism. A setting changing how rows *render* follows 0005; one changing *which rows return* follows this.
- **Revisit if** a script-facing case genuinely needs per-user interpretation. The answer is then a parameter on the public `extract_*` functions — an explicit boundary — not a load-path lookup.
