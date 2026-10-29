"""
The elementwise transform methods: logarithms, exponential, absolute value and sign flip.

Each maps one sample to one sample, on the samples as recorded, so the timestamps are the
source's own. A sample the function cannot represent (``log10`` of zero or a negative, an
``exp`` overflow) comes out non-finite and is dropped by the driver: it shows as a gap, never
as an invented value.
"""

from collections.abc import Callable

import numpy as np

import clinical_scope.constants as cst
from clinical_scope.transforms.base import TransformDefinition, register, unchanged


def _elementwise(function: Callable[[np.ndarray], np.ndarray]) -> Callable[..., np.ndarray]:
    def method(x: np.ndarray, y: np.ndarray) -> np.ndarray:  # noqa: ARG001
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            return function(y)

    return method


def _function_of_unit(name: str) -> Callable[[str], str]:
    """Unit rule for a function of the signal: ``log10(mmHg)``, or just ``log10`` for ``-``."""

    def rule(unit: str) -> str:
        return name if unit == cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT else f"{name}({unit})"

    return rule


# Native-irregular: no grid is needed, and the timestamps stay as recorded.
for _name, _function, _rule in (
    (cst.Transform.LOG10, np.log10, _function_of_unit("log10")),
    (cst.Transform.LN, np.log, _function_of_unit("ln")),
    (cst.Transform.EXP, np.exp, _function_of_unit("exp")),
    (cst.Transform.ABS, np.abs, unchanged),
    (cst.Transform.NEGATE, np.negative, unchanged),
):
    register(
        TransformDefinition(
            name=_name,
            params=(),
            needs_uniform_grid=False,
            fn=_elementwise(_function),
            unit_rule=_rule,
        )
    )
