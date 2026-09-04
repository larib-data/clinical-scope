"""
Home position of a graph's axes, and the repair of the modebar reset that reads it.

plotly.js keeps its own "reset axes" reference (``_rangeInitial``) in private state, and
re-derives it from the current view whenever a ``config`` change forces a full re-plot —
which is what arming and leaving Drag mode does. That reference is unreachable from
Python, so nothing here tries to correct it. Instead the true initial state is captured
at Process time and compared against what a reset proposes: a reset is an ordinary GUI
relayout, so it arrives in ``relayoutData`` and can be overruled like any other.

Only axes plotly actually got wrong are overruled: a reset names every axis on the figure,
and all but one of a time-series figure's x-axes are ``matches``-constrained, so a blanket
correction is both costly and wrong — a matched axis cannot be moved directly.
"""

import re
from typing import Any

# Store id shared by the graph builder and the relayout callback.
STORE_TYPE = "axis-home-store"
AXES_KEY = "axes"
MATCHED_KEY = "matched"

_AXIS_NAME = re.compile(r"^[xy]axis\d*$")

# plotly emits this on a reset and on nothing else; plotly-resampler bets on it too.
_RESET_MARKER = re.compile(r"^([xy]axis\d*)\.showspikes$")

# Dropped from a reset's payload, then re-derived from the stored home.
_VIEW_SUFFIXES = frozenset({"range", "range[0]", "range[1]", "autorange"})


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
    return {AXES_KEY: axes, MATCHED_KEY: matched}


def reset_axes(relayout: dict[str, Any]) -> list[str]:
    """
    Names of the axes a reset-axes click touched; empty for a zoom, pan or autoscale.

    Detection is on key presence, never on the value: the replayed spike setting is
    normally ``False``.
    """
    return [match.group(1) for key in relayout if (match := _RESET_MARKER.match(key))]


def corrupted_axes(relayout: dict[str, Any], axes: list[str], store: dict[str, Any]) -> list[str]:
    """
    Of the axes a reset touched, those whose proposed view is not their home.

    A healthy reset yields none, so it is passed through unaltered. An axis constrained by
    ``matches`` is never listed: it cannot be moved directly, and healing its master
    carries it along.
    """
    home = store.get(AXES_KEY) or {}
    matched = store.get(MATCHED_KEY) or {}
    return [
        axis
        for axis in axes
        if axis not in matched and not _is_home(_proposed_range(relayout, axis), home.get(axis))
    ]


def heal_relayout(
    relayout: dict[str, Any], axes: list[str], store: dict[str, Any]
) -> dict[str, Any]:
    """
    Rewrite a reset's proposed view as the stored home, for the resampler to aggregate.

    Every axis the reset named is rewritten, matched ones included: plotly-resampler
    selects the traces to re-aggregate by their own x-axis, so dropping an axis here
    would leave that subplot showing data for the wrong window.
    """
    home = store.get(AXES_KEY) or {}
    matched = store.get(MATCHED_KEY) or {}
    healed = {key: value for key, value in relayout.items() if not _is_view_key(key, axes)}
    for axis in axes:
        axis_range = home.get(matched.get(axis, axis))
        if axis_range is None:
            healed[f"{axis}.autorange"] = True
        else:
            healed[f"{axis}.range[0]"], healed[f"{axis}.range[1]"] = axis_range
    return healed


def apply_to_patch(patch: Any, axes: list[str], store: dict[str, Any]) -> Any:
    """
    Add the layout ops that put the corrupted axes back on their home position.

    ``uirevision`` is deliberately untouched: bumping it would drop the GUI zoom this reset
    undoes, but ``editrevision`` falls back to it and the user's annotation shape edits
    would go with it. An explicit ``autorange`` wins over a re-applied range anyway.
    """
    home = store.get(AXES_KEY) or {}
    for axis in axes:
        axis_range = home.get(axis)
        patch["layout"][axis]["autorange"] = axis_range is None
        patch["layout"][axis]["range"] = list(axis_range) if axis_range else None
    return patch


def _layout_name(axis_id: str) -> str:
    """Turn a plotly axis reference (``x``, ``x2``) into its layout key (``xaxis2``)."""
    return f"{axis_id[0]}axis{axis_id[1:]}"


def _is_view_key(key: str, axes: list[str]) -> bool:
    """Whether a relayout key states the view of one of ``axes``."""
    axis, _, suffix = key.partition(".")
    return axis in axes and suffix in _VIEW_SUFFIXES


def _proposed_range(relayout: dict[str, Any], axis: str) -> list | None:
    """The range a reset proposes for one axis; None when it proposes autorange."""
    if f"{axis}.range" in relayout:
        return list(relayout[f"{axis}.range"])
    low, high = f"{axis}.range[0]", f"{axis}.range[1]"
    if low in relayout and high in relayout:
        return [relayout[low], relayout[high]]
    return None


def _is_home(proposed: list | None, home_range: list | None) -> bool:
    """Whether a proposed range is the axis's home. Dates compare as text, not floats."""
    if proposed is None or home_range is None:
        return proposed is home_range is None
    return proposed == home_range or _as_text(proposed) == _as_text(home_range)


def _as_text(values: list) -> list[str]:
    return [str(value) for value in values]
