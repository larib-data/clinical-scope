"""
Every plot type the app knows, and the capability sets read across the render layer.

Holds the *leaf* half only, so importing it costs nothing and closes no cycle: this is what
``signal_container`` and the config readers import. The builders live next door in
``builders``, which is reachable only from the top of the stack.

Adding a plot type is a package plus a line in ``AVAILABLE`` here and a line in ``builders``.
Forgetting either is an ImportError at start-up -- never a config that validates cleanly and
renders nothing.

That covers how a type *behaves*. A type wanting a user display setting or an axis payload of
its own also pays for the mechanism carrying it -- a ``DisplayFallbacks`` field, a ``Data``
field -- which is shared with every other type and lives outside this package.
"""

from importlib.util import find_spec

from clinical_scope.plot_types.base import CAPABILITIES, PlotTypeSchema, TimeSeries
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

# --- Capability sets, by plot type name -----------------------------------------------------
# Derived from the schemas rather than declared again, so a new type's behaviour is stated in
# exactly one place. An unregistered name is in none of them and gets no capability at all --
# deliberately not "the time_series defaults", which would let a typo render plausibly.
TIME_AXIS = frozenset(schema.NAME for schema in AVAILABLE if schema.TIME_AXIS)
UNIFIED_HOVER = frozenset(schema.NAME for schema in AVAILABLE if schema.UNIFIED_HOVER)
RESAMPLED = frozenset(schema.NAME for schema in AVAILABLE if schema.RESAMPLED)
GRID_LAYOUT = frozenset(schema.NAME for schema in AVAILABLE if schema.GRID_LAYOUT)
HAS_COLORBAR = frozenset(schema.NAME for schema in AVAILABLE if schema.HAS_COLORBAR)
POINT_TIMESTAMPS = frozenset(schema.NAME for schema in AVAILABLE if schema.POINT_TIMESTAMPS)

NAMES = frozenset(schema.NAME for schema in AVAILABLE)


def _check_registry_is_complete() -> None:
    """
    Refuse to import a registry with a half-declared plot type.

    Checks what a forgotten piece actually looks like: a name that doesn't match its package,
    a config section spelled differently from the type, a package whose ``plot`` half was never
    written, or a capability declared on the schema that no set here exposes. The plot module is
    probed rather than imported -- importing it here would pull ``signal_container`` into a leaf
    and close the cycle this split exists to keep open.
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

        if schema.SECTION_KEY is None:
            continue
        if name != schema.SECTION_KEY:
            msg = (
                f"Plot type {name!r} reads its config from section "
                f"{schema.SECTION_KEY!r}; the two must be spelled the same."
            )
            raise NotImplementedError(msg)
        if find_spec(f"{__package__}.{name}.plot") is None:
            msg = f"Plot type {name!r} has a schema but no {name}/plot.py to build it."
            raise NotImplementedError(msg)

    unexposed = sorted(flag for flag in CAPABILITIES if flag not in globals())
    if unexposed:
        msg = (
            f"Capabilities {unexposed} are declared on PlotTypeSchema but no set here exposes "
            f"them, so no render site can read them."
        )
        raise NotImplementedError(msg)


_check_registry_is_complete()
