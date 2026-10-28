"""
What a transform is, independently of any one method.

A transform computes a derived signal from one source signal: a low-pass filter on a pressure
waveform, a moving average on a numeric. This module holds what every method shares -- the
parameter grammar, the spreadsheet cell parser, validation, and the driver that puts a series
on a uniform grid and runs a method on each gap-free stretch. The methods live in
``filters.py`` and register here.

Parameters are physical (``cutoff_hz``, ``window_s``), never sample counts: a method converts
them from the signal's actual sampling, so one config row means the same on a 125 Hz waveform
as on 1 Hz numerics.
"""

import ast
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

import clinical_scope.constants as cst
from clinical_scope.sampling import build_uniform_grid, contiguous_segments
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)

# The parse errors ast and literal_eval raise on malformed or pathological input.
_PARSE_ERRORS = (SyntaxError, ValueError, TypeError, RecursionError)


class SegmentTooShortError(ValueError):
    """A gap-free stretch holds too few samples for the method to run on."""


@dataclass(frozen=True)
class Param:
    """One keyword a method takes: a positive number of *kind*, required unless it has a default."""

    name: str
    kind: type[int] | type[float]  # an int is accepted where a float is expected
    default: float | None = None

    @property
    def required(self) -> bool:
        return self.default is None

    def problem_with(self, value: Any) -> str | None:
        """Why *value* cannot be this parameter, or ``None`` if it can."""
        # bool is an int subclass, so True would otherwise pass as order=1.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"Must be a number, got {value!r}"
        if self.kind is int and not isinstance(value, int):
            return f"Must be a whole number, got {value!r}"
        if not (math.isfinite(value) and value > 0):
            return f"Must be positive, got {value!r}"
        return None


@dataclass(frozen=True)
class TransformDefinition:
    """
    One method: its name, the keywords it takes, and the function that runs it.

    ``needs_uniform_grid`` picks the calling convention. A grid method is called once per
    gap-free stretch of the regularised series, as ``fn(y, dt_s, **params)``, and returns as
    many values as it was given. Any other method gets the samples as recorded, as
    ``fn(x, y, **params)`` with *x* datetime64, and returns y on that same x.
    """

    name: str
    params: tuple[Param, ...]
    needs_uniform_grid: bool
    fn: Callable[..., np.ndarray]
    # A rule across parameters (low_hz < high_hz): why a complete parameter set is invalid.
    check: Callable[[dict[str, Any]], str | None] | None = None

    @property
    def known_keys(self) -> frozenset[str]:
        return frozenset({cst.Transform.METHOD, *(param.name for param in self.params)})


_REGISTRY: dict[str, TransformDefinition] = {}


def register(definition: TransformDefinition) -> TransformDefinition:
    """Make *definition* available to configs under its name."""
    if definition.name in _REGISTRY:
        msg = f"Transform {definition.name!r} is registered twice."
        raise ValueError(msg)
    _REGISTRY[definition.name] = definition
    return definition


def method_names() -> list[str]:
    """Every registered method name, sorted -- for messages listing what a config may say."""
    return sorted(_REGISTRY)


def derived_rows(database_options_specific: dict) -> dict[str, dict]:
    """
    The derived signals a datasource section declares: its ``signals`` rows with a ``source``.

    A non-empty string ``source`` is what makes a row derived. A ``transform`` alone, or a
    source that is not a name, is a config error reported by validation; such a row is read as
    an ordinary signal and never reaches a transform.
    """
    signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS)
    if not isinstance(signals, dict):
        return {}
    source_key = cst.DatabaseOptions.SignalConfig.SOURCE
    return {
        name: row
        for name, row in signals.items()
        if isinstance(row, dict)
        and isinstance(row.get(source_key), str)
        and row[source_key].strip()
    }


def parse_transform_cell(cell: str) -> dict[str, Any] | str:
    """
    Read a spreadsheet ``transform`` cell, e.g. ``lowpass(cutoff_hz=5, order=4)``, as a dict.

    Parsed, never evaluated: only a bare method name, or a call to one with keyword arguments
    whose values are literals, is understood. Anything else comes back as the cell's text, so
    validation reports it alongside the file's other problems instead of the upload failing
    here.
    """
    text = cell.strip()
    try:
        node = ast.parse(text, mode="eval").body
    except _PARSE_ERRORS:
        return text
    if isinstance(node, ast.Name):
        return {cst.Transform.METHOD: node.id}
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)) or node.args:
        return text
    spec: dict[str, Any] = {cst.Transform.METHOD: node.func.id}
    for keyword in node.keywords:
        # **kwargs has no name; a repeated keyword, or one named "method", would overwrite.
        if keyword.arg is None or keyword.arg in spec:
            return text
        try:
            spec[keyword.arg] = ast.literal_eval(keyword.value)
        except _PARSE_ERRORS:
            return text
    return spec


def validate_transform(spec: Any, path: str) -> list[ValidationIssue]:
    """
    Check one ``transform`` without running it: method known, parameters present and valid.

    Only what the config alone can tell. Whether a cutoff sits below a recording's Nyquist
    frequency depends on the data, so it is checked when the signal is built, and failing it
    skips that one signal.
    """
    if isinstance(spec, str):
        return [
            ValidationIssue(
                severity="error",
                path=path,
                message=(
                    f"Cannot read {spec!r}. Write the method name, then its parameters by "
                    f"name, e.g. lowpass(cutoff_hz=5, order=4)"
                ),
            )
        ]
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                severity="error",
                path=path,
                message=f"Must be a dict with a 'method' key, got {type(spec).__name__}",
            )
        ]
    method = spec.get(cst.Transform.METHOD)
    definition = _REGISTRY.get(method) if isinstance(method, str) else None
    if definition is None:
        return [
            ValidationIssue(
                severity="error",
                path=f"{path}.{cst.Transform.METHOD}",
                message=f"Unknown method {method!r}. Expected one of {method_names()}",
            )
        ]

    issues: list[ValidationIssue] = []
    unknown = set(spec) - definition.known_keys
    if unknown:
        # An error, unlike an unknown key elsewhere: ignoring a misspelled parameter would run
        # the method on its default, and nothing on the plot would show the value went unused.
        issues.append(
            ValidationIssue(
                severity="error",
                path=path,
                message=(
                    f"Unknown parameter(s) {sorted(unknown)} for {definition.name}. "
                    f"Expected: {sorted(param.name for param in definition.params)}"
                ),
            )
        )
    for param in definition.params:
        if param.name not in spec:
            if param.required:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        path=f"{path}.{param.name}",
                        message=f"Required by {definition.name}",
                    )
                )
            continue
        problem = param.problem_with(spec[param.name])
        if problem:
            issues.append(
                ValidationIssue(severity="error", path=f"{path}.{param.name}", message=problem)
            )

    # A cross-parameter rule reads every value, so it is only meaningful once each one is.
    if definition.check is not None and not any(issue.severity == "error" for issue in issues):
        problem = definition.check(_with_defaults(definition, spec))
        if problem:
            issues.append(ValidationIssue(severity="error", path=path, message=problem))
    return issues


def _with_defaults(definition: TransformDefinition, spec: dict[str, Any]) -> dict[str, Any]:
    """The parameters *definition* runs with: each one given in *spec*, else its default."""
    return {param.name: spec.get(param.name, param.default) for param in definition.params}


@dataclass(frozen=True)
class ResolvedTransform:
    """A method bound to its parameters, every default filled in: ready to run."""

    definition: TransformDefinition
    params: dict[str, Any]

    @property
    def spec(self) -> dict[str, Any]:
        """The canonical dict this transform runs as -- what a derived Signal records."""
        return {cst.Transform.METHOD: self.definition.name, **self.params}

    def apply(self, x: np.ndarray, y: np.ndarray, name: str = "") -> tuple[np.ndarray, np.ndarray]:
        """
        Run on finite, time-sorted samples and return the derived ``(x, y)``, finite only.

        A grid method runs on each gap-free stretch of the regularised series in turn, so no
        output exists inside a recording gap and nothing on one side of a gap shapes the
        other. A stretch too short for the method is left out and logged; if every stretch
        is, this raises. *name* only labels that log line.
        """
        method = self.definition
        if not method.needs_uniform_grid:
            y_out = method.fn(x, y, **self.params)
            keep = np.isfinite(y_out)
            return x[keep], y_out[keep]

        x_grid, y_grid, dt_s = build_uniform_grid(x, y)
        y_out = np.full(len(y_grid), np.nan)
        left_out: list[str] = []
        for segment in contiguous_segments(y_grid):
            try:
                y_out[segment] = method.fn(y_grid[segment], dt_s, **self.params)
            except SegmentTooShortError as exc:
                left_out.append(str(exc))

        keep = np.isfinite(y_out)
        if not keep.any():
            msg = f"every gap-free stretch is too short for {method.name} ({left_out[0]})"
            raise ValueError(msg)
        if left_out:
            logger.warning(
                "Derived signal '%s': %d gap-free stretch(es) left out, too short for %s (%s).",
                name,
                len(left_out),
                method.name,
                left_out[0],
            )
        return x_grid[keep], y_out[keep]


def resolve(spec: Any) -> ResolvedTransform:
    """
    The method *spec* names, bound to its parameters with defaults filled in.

    Raises ValueError on anything :func:`validate_transform` reports as an error: a config is
    validated when it is loaded, but errors there do not block loading, and a library caller
    can hand one over unchecked.
    """
    errors = [
        issue
        for issue in validate_transform(spec, cst.DatabaseOptions.SignalConfig.TRANSFORM)
        if issue.severity == "error"
    ]
    if errors:
        msg = "; ".join(f"{issue.path}: {issue.message}" for issue in errors)
        raise ValueError(msg)
    definition = _REGISTRY[spec[cst.Transform.METHOD]]
    return ResolvedTransform(definition, _with_defaults(definition, spec))
