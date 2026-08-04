# 5. User options are fallbacks; database options win

Date: 2026-08-04

## Status

Accepted

## Context

ClinicalScope now has three tiers of options (see `CONTEXT.md`): **database options** (per-Database signal configuration, authored once and shared between users), **patient options** (per-run settings), and **user options** (per-person global preferences, `~/.clinical_scope/user_options.json`).

The third tier shipped with two tenants and no stated rule for what happens when it and the database options both speak — and the two tenants already disagree:

- `default_subplot_height` **overrides** each `PlotGroup`'s own `plot_height` unconditionally in `PlotModel.assign_plot_model`.
- A fallback colorway (the next planned tenant) must **not** override a per-signal `color` set in `database_options` — a personal palette silently repainting a colleague's tuned Database configuration is a bad outcome, and there would be no way to say "just use the config" short of resetting the preference.

Without a rule, every future setting answers this question ad hoc and nobody can predict what a setting does without reading the call site.

Three options were considered:

1. **User options always win** — consistent with the shipped height behaviour, but makes shared Database configuration unreliable: a Database author cannot count on their colors, heights, or formats surviving contact with a colleague's preferences.
2. **Database options always win; user options are pure fallbacks** — a user option applies only where the Database configuration is silent.
3. **Per-setting, declared on the schema class** (e.g. `OVERRIDES_DATABASE = True`) — honest that height and color genuinely feel different, and visible in the schema rather than buried in call sites.

## Decision

2 **User options are fallbacks. Where database options speak, database options win.** A user option applies only where the Database configuration is silent about that property.

Consequently `default_subplot_height` is changed to a fallback: a `PlotGroup` with an explicit `plot_height` from its Database configuration keeps it.

Two properties made this the choice over the alternatives:

- **A one-sentence mental model beats per-setting precision.** *"User options fill gaps, database options decide"* is a rule a contributor can apply to a new setting without consulting anything. Option 3 sounds more flexible but pushes the question onto every future contributor, and gets answered inconsistently.
- **Shared configuration must be trustworthy.** A Database is by definition shared between users; the whole point of `database_options` is that everyone opening that Database sees the same thing. Option 1 makes that guarantee conditional on nobody having touched their settings.

The scope of the tier is fixed at the same time: user options cover **app behaviour** (habits like `save_html_on_process`) and **display fallbacks** (palette, heights, formats). They are explicitly **not** defaults for `patient_options` fields — that is form pre-fill, a different mechanism, and admitting it would force every future setting to first answer "am I a fallback or a default?".

## Consequences

- **Easier:** a new setting needs no precedence design; the rule is already decided. Database authors can rely on their configuration surviving other users' preferences.
- **Harder / accepted trade-offs:** `default_subplot_height` changes behaviour for any Database that sets a per-group `plot_height` — that value now wins where it previously lost. In practice `plot_height` is rarely set per group, so "fallback" and "override" coincide almost everywhere and the visible change is close to nil. Accepted as the cost of one uniform rule.
- **Revisit if:** users ask for an explicit "force my settings over the config" escape hatch — at which point the answer is a single opt-in flag, not a per-setting precedence attribute.
