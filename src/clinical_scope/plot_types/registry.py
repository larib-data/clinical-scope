"""
Every plot type the app knows, and the one place a plot type's *name* becomes its schema.

Holds the config half only -- the schemas -- so importing it never loads numpy or plotly.
The render halves live next door in ``builders``, which only ``plot_assembly`` reads.

Adding a plot type is a package plus a line in ``AVAILABLE`` here and a line in ``builders``.
Forgetting either is an ImportError at start-up, never a config that validates cleanly and
renders nothing.

Nothing here answers "does plot type X do Y?" -- a Signal carries its own schema and every
render site reads the flag off that. ``schema_for`` exists for the single boundary where the
schema could not be carried: a plot type name that has been through a Dash store as JSON.

That covers how a type *behaves*. A type wanting a user display setting or an axis payload of
its own also pays for the mechanism carrying it -- a ``DisplayFallbacks`` field, a ``Data``
field -- which is shared with every other type and lives outside this package.
"""

from clinical_scope.plot_types.base import CAPABILITIES, PlotTypeSchema, TimeSeries, Unknown
from clinical_scope.plot_types.loop.schema import LoopSchema
from clinical_scope.plot_types.psd.schema import PsdSchema
from clinical_scope.plot_types.spectrogram.schema import SpectrogramSchema

# Page order of the plot models, top to bottom -- an ordering across types belongs to the
# collection, the same deviation from "orderings live in constants.py" that DataSource.AVAILABLE
# already makes. time_series first: it is what a clinician came to look at.
AVAILABLE: tuple[type[PlotTypeSchema], ...] = (
    TimeSeries,
    SpectrogramSchema,
    PsdSchema,
    LoopSchema,
)

PAGE_ORDER = tuple(schema.NAME for schema in AVAILABLE)

# The types configured through a database_options section of their own; time_series is not one.
DERIVED = tuple(schema for schema in AVAILABLE if schema.SECTION_KEY)

SECTION_KEYS = frozenset(schema.SECTION_KEY for schema in DERIVED)

NAMES = frozenset(schema.NAME for schema in AVAILABLE)

_BY_NAME = {schema.NAME: schema for schema in AVAILABLE}


def schema_for(name: str | None) -> type[PlotTypeSchema]:
    """
    The schema a plot type *name* stands for, or ``Unknown`` if the app has no such type.

    The inverse of ``schema.NAME``, needed only where a schema could not be carried on the
    object: a plot type that crossed a Dash store, where JSON leaves nothing but the string.
    """
    return _BY_NAME.get(name, Unknown)


def _check_registry_is_complete() -> None:
    """
    Refuse to import a registry with a half-declared plot type.

    Checks what a forgotten piece actually looks like: a duplicate or missing name, a config
    section spelled differently from the type, or a capability that ``Unknown`` does not turn
    off -- which would leave it silently on for a name nothing recognises.
    """
    seen: set[str] = set()
    for schema in AVAILABLE:
        name = getattr(schema, "NAME", None)
        if not name:
            msg = f"Plot type {schema.__name__} declares no NAME."
            raise NotImplementedError(msg)
        if name in seen:
            msg = f"Plot type {name!r} is registered twice."
            raise NotImplementedError(msg)
        seen.add(name)

        if schema.SECTION_KEY is not None and name != schema.SECTION_KEY:
            msg = (
                f"Plot type {name!r} reads its config from section "
                f"{schema.SECTION_KEY!r}; the two must be spelled the same."
            )
            raise NotImplementedError(msg)

    still_on = sorted(flag for flag in CAPABILITIES if getattr(Unknown, flag))
    if still_on:
        msg = (
            f"Capabilities {still_on} are not turned off on Unknown, so an unrecognised plot "
            f"type name would claim them."
        )
        raise NotImplementedError(msg)


_check_registry_is_complete()
