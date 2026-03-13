"""
Custom hover formatters for signal display.

Use a magic keyword in ``hover_template`` (database_options / xlsx) to activate
a formatter.  Any other string is forwarded as-is to Plotly as a hovertemplate.

Supported keywords
------------------
``"fraction"``
    Values in (0, 1) are shown as ``1/n`` where ``n = round(1/value)``.
    Zero shows ``"0"``.  Values ≥ 1 or < 0 fall back to ``:.4g`` decimal.

``"percentage"``
    Values are multiplied by 100 and shown with one decimal place, e.g.
    ``0.333 → "33.3%"``.

Adding a new formatter
----------------------
1. Add a module-level constant (e.g. ``MY_KEYWORD = "my_keyword"``).
2. Write a ``_my_keyword_str(value: float) -> str`` function.
3. Register it in ``_FORMATTERS``.
That's it — signal_container.py picks it up automatically.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Keyword constants
# ---------------------------------------------------------------------------

FRACTION = "fraction"
PERCENTAGE = "percentage"


# ---------------------------------------------------------------------------
# Per-value formatter functions
# ---------------------------------------------------------------------------


def _fraction_str(value: float) -> str:
    if not np.isfinite(value):
        return ""
    if value == 0:
        return "0"
    if value >= 1 or value < 0:
        return f"{value:.4g}"
    n = round(1.0 / value)
    return f"1/{n}" if n > 0 else ""


def _percentage_str(value: float) -> str:
    if not np.isfinite(value):
        return ""
    return f"{value * 100:.1f}%"


# ---------------------------------------------------------------------------
# Registry  {keyword → formatter}
# ---------------------------------------------------------------------------

_FORMATTERS: dict[str, callable] = {
    FRACTION: _fraction_str,
    PERCENTAGE: _percentage_str,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_keyword(template: str | None) -> bool:
    """Return True when *template* is a recognised magic keyword."""
    return template is not None and template.strip().lower() in _FORMATTERS


def compute_customdata(y: np.ndarray, keyword: str) -> np.ndarray:
    """
    Build a string array for use as Plotly ``customdata``.

    Parameters
    ----------
    y:
        Raw y values of the trace.
    keyword:
        One of the magic keyword constants (case-insensitive).

    Returns
    -------
    np.ndarray of str, same length as *y*.

    """
    fmt = _FORMATTERS.get(keyword.strip().lower())
    if fmt is None:
        return np.full(len(y), "")
    return np.array([fmt(v) for v in y])
