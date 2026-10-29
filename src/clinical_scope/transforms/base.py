"""
What a transform is, independently of any one method.

A transform computes a derived signal from one source signal: a low-pass filter on a pressure
waveform, a moving average on a numeric. The source may itself be derived, and
:func:`derived_chain` follows such a chain up to the column it starts from. This module holds
what every method shares -- the parameter grammar, the spreadsheet cell parser, validation,
and the driver that puts a series on a uniform grid and runs a method on each gap-free
stretch. The methods live in ``filters.py``, ``elementwise.py`` and ``normalisation.py`` and
register here.

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
from clinical_scope.sampling import (
    TooFewSamplesError,
    build_uniform_grid,
    contiguous_segments,
    gap_free_runs,
)
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)

# The parse errors ast and literal_eval raise on malformed or pathological input.
_PARSE_ERRORS = (SyntaxError, ValueError, TypeError, RecursionError)


class SegmentTooShortError(ValueError):
    """A gap-free stretch holds too few samples for the method to run on."""


@dataclass(frozen=True)
class Param:
    """
    One keyword a method takes: a number of *kind*, required unless it has a default.

    Positive unless ``allow_zero`` admits zero too; ``maximum`` bounds it from above.
    """

    name: str
    kind: type[int] | type[float]  # an int is accepted where a float is expected
    default: float | None = None
    allow_zero: bool = False
    maximum: float | None = None

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
        if self.allow_zero:
            if not (math.isfinite(value) and value >= 0):
                return f"Must be zero or positive, got {value!r}"
        elif not (math.isfinite(value) and value > 0):
            return f"Must be positive, got {value!r}"
        if self.maximum is not None and value > self.maximum:
            return f"Must be at most {self.maximum:g}, got {value!r}"
        return None


def unchanged(unit: str) -> str:
    """The unit rule of a method that leaves the unit as it is."""
    return unit


@dataclass(frozen=True)
class TransformDefinition:
    """
    One method: its name, the keywords it takes, and the function that runs it.

    ``needs_uniform_grid`` picks the calling convention. A grid method is called once per
    gap-free stretch of the regularised series, as ``fn(y, dt_s, **params)``, and returns as
    many values as it was given. Any other method gets the samples as recorded, as
    ``fn(x, y, **params)`` with *x* datetime64, and returns y on that same x.

    ``unit_rule`` maps the source's unit to the derived one (``mmHg`` -> ``mmHg/s``). It has no
    default so a new method has to say whether it changes the unit; :func:`unchanged` says not.
    It is given the source's unit, ``-`` when the source has none, and decides what that means.
    """

    name: str
    params: tuple[Param, ...]
    needs_uniform_grid: bool
    fn: Callable[..., np.ndarray]
    unit_rule: Callable[[str], str]
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


class ChainError(ValueError):
    """Derived rows whose ``source`` names loop back on themselves, so none reaches a column."""


def derived_chain(
    name: str,
    database_options_specific: dict,
    is_column: Callable[[str], bool] = lambda _name: False,
) -> tuple[str, list[str]]:
    """
    Follow the derived row *name* up its ``source`` names to the column it is computed from.

    Returns that column's name, then the derived rows on the way, root first and *name* last:
    running their transforms in that order builds *name*. The walk stops at the first name that
    is not a derived row, or that *is_column* says is a column of the data -- a column wins
    over a derived row of its name, so a chain through it starts from the curve plotted under
    it. Whether the name it stops at is a column at all is for the caller to check: validation
    has no data, and pruning and building have different ones.

    Raises ChainError on a cycle, which a config that skipped validation can still hold.
    """
    rows = derived_rows(database_options_specific)
    source_key = cst.DatabaseOptions.SignalConfig.SOURCE
    links = [name]
    current = rows[name][source_key]
    while current in rows and not is_column(current):
        if current in links:
            cycle = " -> ".join(f"'{link}'" for link in [*links[links.index(current) :], current])
            msg = (
                f"The sources loop: {cycle}. Each of these derived signals is computed from the "
                f"next, so none reaches a signal of the data."
            )
            raise ChainError(msg)
        links.append(current)
        current = rows[current][source_key]
    return current, links[::-1]


def factor_is_copied(row: dict, source_row: Any) -> bool:
    """
    Whether a derived row's ``unit_conversion`` merely repeats its source row's own.

    Duplicating the source's row is how a derived row is made, and it carries the factor over;
    applying it again would scale the source's curve, already scaled by it, a second time. A
    factor of 1 changes nothing either way, so it is never reported as copied.
    """
    signal_config = cst.DatabaseOptions.SignalConfig
    factor = row.get(signal_config.UNIT_CONVERSION)
    source_factor = (
        source_row.get(signal_config.UNIT_CONVERSION) if isinstance(source_row, dict) else None
    )
    return (
        factor is not None
        and factor != signal_config.DEFAULT_UNIT_CONVERSION
        and factor == source_factor
    )


def own_factor(row: dict, source_row: Any) -> float | None:
    """
    The factor a derived row scales its own result by, or ``None`` when it sets none.

    An empty cell, a 1 and a factor copied from the source row (:func:`factor_is_copied`) all
    mean the row's result is drawn as its transform returns it.
    """
    factor = row.get(cst.DatabaseOptions.SignalConfig.UNIT_CONVERSION)
    if (
        factor is None
        or factor == cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT_CONVERSION
        or factor_is_copied(row, source_row)
    ):
        return None
    return factor


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
            value = ast.literal_eval(keyword.value)
        except _PARSE_ERRORS:
            return text
        # Only what a JSON config could hold: the upload keeps this dict in a JSON store, so a
        # set or a complex literal would fail the whole upload rather than one validation line.
        if not isinstance(value, (bool, int, float, str)):
            return text
        spec[keyword.arg] = value
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


def _unit_of(row: Any) -> str | None:
    """The ``unit`` a signal row sets, or ``None`` when it sets none."""
    unit = row.get(cst.DatabaseOptions.SignalConfig.UNIT) if isinstance(row, dict) else None
    return unit if isinstance(unit, str) and unit.strip() else None


def derived_unit(
    column: str, links: list[str], database_options_specific: dict
) -> tuple[str, str | None]:
    """
    The unit the last of *links* is drawn in, and a warning when its ``unit`` cannot be honoured.

    *column* and *links* are a chain as :func:`derived_chain` returns it. The unit is worked
    out link by link from the column's own ``unit``, so a derivative of a derivative of mmHg is
    ``mmHg/s/s``. Shared by the signal builder and by validation so the two cannot disagree.
    Raises ValueError when a link's transform cannot be resolved.
    """
    signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS)
    signals = signals if isinstance(signals, dict) else {}
    unit = _unit_of(signals.get(column))
    warning = None
    source_name = column
    for link in links:
        row = signals[link]
        definition = resolve(row.get(cst.DatabaseOptions.SignalConfig.TRANSFORM)).definition
        unit, warning = _link_unit(row, source_name, signals.get(source_name), unit, definition)
        source_name = link
    return unit, warning


def _link_unit(
    row: dict,
    source_name: str,
    source_row: Any,
    source_unit: str | None,
    definition: TransformDefinition,
) -> tuple[str, str | None]:
    """
    One link's unit, given its source's: *source_unit* is the unit the source is drawn in.

    Three steps, first match wins. A ``unit`` the row sets is used, unless the method changes
    the unit and the row merely copies the source row's ``unit`` cell. Else a row with its own
    ``unit_conversion`` gets ``-``: the factor may mean anything (x60 for per-minute), so the
    unit is not guessed. Else the method's unit rule applied to *source_unit*.
    """
    signal_config = cst.DatabaseOptions.SignalConfig
    own_unit = _unit_of(row)
    changes_unit = definition.unit_rule is not unchanged
    # Against the cell, not the unit the source is drawn in: only the cell is carried over
    # by duplicating the row.
    copied = own_unit is not None and own_unit == _unit_of(source_row)
    if own_unit is not None and not (copied and changes_unit):
        return own_unit, None

    has_own_factor = own_factor(row, source_row) is not None
    if has_own_factor:
        effective = signal_config.DEFAULT_UNIT
        reason = (
            f"this row's own unit_conversion means its unit cannot be derived from the unit "
            f"of '{source_name}'"
        )
    else:
        effective = definition.unit_rule(source_unit or signal_config.DEFAULT_UNIT)
        reason = ""

    if copied:
        message = (
            f"`{definition.name}` changes the unit; `{own_unit}`, copied from "
            f"'{source_name}', is ignored and `{effective}` is used. Set `unit` to choose another."
        )
        if has_own_factor:
            message = (
                f"`{definition.name}` changes the unit, so the `{own_unit}` copied from "
                f"'{source_name}' cannot be kept; {reason}. Set `unit`."
            )
        return effective, message
    if has_own_factor:
        return effective, f"Set `unit`: {reason}"
    return effective, None


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

        A grid method runs on each gap-free stretch in turn, each regularised at its own
        sampling step, so no output exists inside a recording gap and nothing on one side of a
        gap shapes the other. A stretch too short for the method is left out and logged; if
        every stretch is, this raises. *name* only labels that log line.
        """
        method = self.definition
        if not method.needs_uniform_grid:
            y_out = method.fn(x, y, **self.params)
            keep = np.isfinite(y_out)
            if not keep.any():
                msg = f"{method.name} produced no finite value from {len(x)} sample(s)"
                raise ValueError(msg)
            return x[keep], y_out[keep]

        x_parts: list[np.ndarray] = []
        y_parts: list[np.ndarray] = []
        left_out: list[str] = []
        for run in gap_free_runs(x):
            try:
                x_grid, y_grid, dt_s = build_uniform_grid(x[run], y[run])
            except TooFewSamplesError as exc:
                left_out.append(str(exc))
                continue
            # A run can still hold a gap against its own, finer median step.
            for segment in contiguous_segments(y_grid):
                try:
                    y_parts.append(method.fn(y_grid[segment], dt_s, **self.params))
                except SegmentTooShortError as exc:
                    left_out.append(str(exc))
                    continue
                x_parts.append(x_grid[segment])

        x_out = np.concatenate(x_parts) if x_parts else x[:0]
        y_out = np.concatenate(y_parts) if y_parts else y[:0]
        keep = np.isfinite(y_out)
        if not keep.any():
            msg = (
                f"every gap-free stretch is too short for {method.name} ({left_out[0]})"
                if left_out
                else f"{method.name} produced no finite value from {len(x)} sample(s)"
            )
            raise ValueError(msg)
        if left_out:
            logger.warning(
                "Derived signal '%s': %d gap-free stretch(es) left out, too short for %s (%s).",
                name,
                len(left_out),
                method.name,
                left_out[0],
            )
        return x_out[keep], y_out[keep]


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
