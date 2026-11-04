"""
The normalisation transform methods: ``zscore`` and ``minmax``.

They re-express a signal on a scale of its own so that signals of different units can be drawn
on one axis. The statistics come from every finite sample the method receives -- the loaded
time window -- so the same row draws a different curve when the window changes.

Neither clips: a value far from the bulk stays far from it. The percentiles of ``minmax`` only
choose which samples set the scale.
"""

from typing import Any

import numpy as np

import clinical_scope.constants as cst
from clinical_scope.transforms.base import Param, TransformDefinition, register

# --- Parameter names ---
LOW_PCT = "low_pct"
HIGH_PCT = "high_pct"

DEFAULT_LOW_PCT = 0
DEFAULT_HIGH_PCT = 100
MAX_PCT = 100

# --- Units of the normalised curves ---
ZSCORE_UNIT = "z"
MINMAX_UNIT = "norm"


def zscore(x: np.ndarray, y: np.ndarray) -> np.ndarray:  # noqa: ARG001
    """Standard score over every sample: mean 0, population standard deviation 1."""
    std = np.std(y)
    # `not >` also catches NaN, which an empty input gives.
    if not std > 0:
        msg = (
            f"{cst.Transform.ZSCORE} needs a signal that varies, this one's standard deviation is 0"
        )
        raise ValueError(msg)
    return (y - np.mean(y)) / std


def minmax(x: np.ndarray, y: np.ndarray, low_pct: float, high_pct: float) -> np.ndarray:  # noqa: ARG001
    """Rescale so the *low_pct* percentile is 0 and the *high_pct* one is 1, without clipping."""
    low, high = np.percentile(y, [low_pct, high_pct]) if y.size else (np.nan, np.nan)
    if not high > low:
        msg = (
            f"{cst.Transform.MINMAX} needs a signal that varies between its {low_pct:g}th and "
            f"{high_pct:g}th percentile, this one is constant there"
        )
        raise ValueError(msg)
    return (y - low) / (high - low)


def _percentiles_are_ordered(params: dict[str, Any]) -> str | None:
    if params[LOW_PCT] >= params[HIGH_PCT]:
        return f"low_pct ({params[LOW_PCT]}) must be below high_pct ({params[HIGH_PCT]})"
    return None


register(
    TransformDefinition(
        name=cst.Transform.ZSCORE,
        params=(),
        needs_uniform_grid=False,
        fn=zscore,
        unit_rule=lambda unit: ZSCORE_UNIT,  # noqa: ARG005
    )
)
register(
    TransformDefinition(
        name=cst.Transform.MINMAX,
        params=(
            Param(LOW_PCT, float, DEFAULT_LOW_PCT, allow_zero=True, maximum=MAX_PCT),
            Param(HIGH_PCT, float, DEFAULT_HIGH_PCT, allow_zero=True, maximum=MAX_PCT),
        ),
        needs_uniform_grid=False,
        fn=minmax,
        unit_rule=lambda unit: MINMAX_UNIT,  # noqa: ARG005
        check=_percentiles_are_ordered,
    )
)
