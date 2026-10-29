"""
Transforms: how a derived signal is computed from its source signal.

``base`` is what every method shares; ``filters``, ``elementwise`` and ``normalisation`` hold
the methods, which register themselves when imported -- importing this package is what makes
them available to a config.
"""

from clinical_scope.transforms import (  # noqa: F401 -- registers the methods
    elementwise,
    filters,
    normalisation,
)
from clinical_scope.transforms.base import (
    ChainError,
    Param,
    ResolvedTransform,
    SegmentTooShortError,
    TransformDefinition,
    derived_chain,
    derived_rows,
    derived_unit,
    factor_is_copied,
    method_names,
    own_factor,
    parse_transform_cell,
    register,
    resolve,
    validate_transform,
)

__all__ = [
    "ChainError",
    "Param",
    "ResolvedTransform",
    "SegmentTooShortError",
    "TransformDefinition",
    "derived_chain",
    "derived_rows",
    "derived_unit",
    "factor_is_copied",
    "method_names",
    "own_factor",
    "parse_transform_cell",
    "register",
    "resolve",
    "validate_transform",
]
