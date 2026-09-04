"""
Home position of a graph's axes, and the repair of the reset gesture that reads it.

plotly.js keeps its own "reset axes" reference (``_rangeInitial``) in private state, and
re-derives it from the current view whenever a ``config`` change forces a full re-plot —
which is what arming and leaving Drag mode does. That reference is unreachable from
Python, so nothing here tries to correct it. Instead the true initial state is captured
at Process time and compared against what a reset proposes: a reset is an ordinary GUI
relayout, so it arrives in ``relayoutData`` and can be overruled like any other.

A reset is recognised by the shape of its payload rather than by a companion key. plotly
replays ``_rangeInitial`` as an *unsplit* ``<axis>.range``; every other gesture that moves
an axis — drag-zoom, pan, the modebar's zoom buttons, the rangeslider — emits split
``range[0]``/``range[1]``. An unsplit range key therefore *is* the stale reference being
replayed, which catches both ways to reset (the modebar button and double-click) and
nothing else. Keying on the ``<axis>.showspikes`` companion instead, the way
plotly-resampler does, caught the button alone and misfired on Toggle Spike Lines.

Only axes plotly actually got wrong are overruled: a reset names every axis on the figure,
and all but one of a time-series figure's x-axes are ``matches``-constrained, so a blanket
correction is both costly and wrong — a matched axis cannot be moved directly.
"""

import re
from datetime import datetime
from typing import Any

# Store id shared by the graph builder and the relayout callback.
STORE_TYPE = "axis-home-store"

_AXES_KEY = "axes"
_MATCHED_KEY = "matched"

_AXIS_NAME = re.compile(r"^[xy]axis\d*$")

# An unsplit range is plotly replaying a stored initial view; a zoom or pan splits it.
_REPLAYED_RANGE = re.compile(r"^([xy]axis\d*)\.range$")

# Dropped from a reset's payload, then re-derived from the stored home.
_VIEW_SUFFIXES = frozenset({"range", "autorange"})


def capture(figure: Any) -> dict[str, Any]:
    """
    Snapshot a figure's initial axis state, for the store that feeds a later reset.

    ``None`` means the axis has no configured range, so its home is plain autorange; only
    ``x_axis_range``/``y_axis_range`` in database_options make it anything else. A matched
    axis is recorded against its master, having no range of its own to restore.
    """
    layout = figure.layout.to_plotly_json()
    axes: dict[str, Any] = {}
    matched: dict[str, str] = {}
    for key, value in layout.items():
        if not _AXIS_NAME.match(key) or not isinstance(value, dict):
            continue
        axis_range = value.get("range")
        axes[key] = list(axis_range) if axis_range else None
        master = value.get("matches")
        if master:
            matched[key] = _layout_name(master)
    return {_AXES_KEY: axes, _MATCHED_KEY: matched}


def rehome(relayout: dict[str, Any], store: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Overrule a reset plotly is replaying from a reference it re-derived while zoomed.

    Returns the relayout to hand the resampler, and the axes to correct on the figure. The
    second is empty when this is not a reset or is one already on its home position, and
    the relayout then comes back untouched — the pass-through every other gesture takes.
    """
    replayed = [match.group(1) for key in relayout if (match := _REPLAYED_RANGE.match(key))]
    if not replayed:
        return relayout, []
    home = store.get(_AXES_KEY) or {}
    matched = store.get(_MATCHED_KEY) or {}
    # A matched axis cannot be moved directly, so it is never corrected: healing its
    # master carries it through plotly's constraint solver.
    off_home = [
        axis
        for axis in replayed
        if axis not in matched and not _is_home(relayout[f"{axis}.range"], home.get(axis))
    ]
    if not off_home:
        return relayout, []
    return _heal(relayout, replayed, home, matched), off_home


def apply_to_patch(patch: Any, axes: list[str], store: dict[str, Any]) -> Any:
    """
    Add the layout ops that put the off-home axes back on their home position.

    ``uirevision`` is deliberately untouched: bumping it would drop the GUI zoom this reset
    undoes, but ``editrevision`` falls back to it and the user's annotation shape edits
    would go with it. An explicit ``autorange`` wins over a re-applied range anyway.
    """
    home = store.get(_AXES_KEY) or {}
    for axis in axes:
        axis_range = home.get(axis)
        patch["layout"][axis]["autorange"] = axis_range is None
        patch["layout"][axis]["range"] = list(axis_range) if axis_range else None
    return patch


def _heal(
    relayout: dict[str, Any],
    axes: list[str],
    home: dict[str, Any],
    matched: dict[str, str],
) -> dict[str, Any]:
    """
    Rewrite a reset's proposed view as the stored home, for the resampler to aggregate.

    Every replayed axis is rewritten, matched ones included: plotly-resampler selects the
    traces to re-aggregate by their own x-axis, so dropping an axis here would leave that
    subplot showing data for the wrong window.

    The ``showspikes`` companion is stated rather than merely preserved. plotly-resampler
    reads a reset off that key, and re-aggregates to the whole recording only when it is
    there; a double-click reset carries none, so a healed one that stayed silent would
    move the axes and leave the traces on the aggregation for the abandoned window.
    """
    healed = {key: value for key, value in relayout.items() if not _is_view_key(key, axes)}
    for axis in axes:
        axis_range = home.get(matched.get(axis, axis))
        if axis_range is None:
            healed[f"{axis}.autorange"] = True
        else:
            healed[f"{axis}.range[0]"], healed[f"{axis}.range[1]"] = axis_range
        healed.setdefault(f"{axis}.showspikes", False)
    return healed


def _layout_name(axis_id: str) -> str:
    """Turn a plotly axis reference (``x``, ``x2``) into its layout key (``xaxis2``)."""
    return f"{axis_id[0]}axis{axis_id[1:]}"


def _is_view_key(key: str, axes: list[str]) -> bool:
    """Whether a relayout key states the view of one of ``axes``."""
    axis, _, suffix = key.partition(".")
    return axis in axes and suffix in _VIEW_SUFFIXES


def _is_home(proposed: list, home_range: list | None) -> bool:
    """Whether a replayed range is the axis's home; never, when home is plain autorange."""
    if home_range is None or len(proposed) != len(home_range):
        return False
    return all(_is_same_bound(*pair) for pair in zip(proposed, home_range, strict=True))


def _is_same_bound(proposed: Any, home_bound: Any) -> bool:
    """
    Compare one range bound.

    A date reaches the store as a ``datetime`` and comes back from it as ISO-8601 text,
    while plotly sends the same instant space-separated, so the two never compare equal
    as strings and a healthy reset would look off-home.
    """
    if proposed == home_bound:
        return True
    instant = _as_instant(proposed)
    return instant is not None and instant == _as_instant(home_bound)


def _as_instant(value: Any) -> datetime | None:
    """A range bound as a datetime, or None when it does not state one."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
