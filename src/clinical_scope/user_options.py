"""
The user_options schema as data: traversal, defaults, and validation.

Pure by design — nothing here reads ``~/.clinical_scope/user_options.json``. Disk I/O lives in
``dash_api.helper_api``, so the core is structurally unable to pick up an ambient settings file
and an ``extract_*`` run cannot depend on who is at the keyboard (ADR-0014).
"""

from dataclasses import dataclass
from typing import Any

import clinical_scope.constants as cst
from clinical_scope.datasource.formatting.timezone import resolve_display_timezone


@dataclass(frozen=True)
class Correction:
    """
    One stored value the schema rejected, and what replaced it.

    Returned rather than logged so each boundary can react on its own: the settings modal
    discards silently (its widget re-renders showing *used*), the loader logs, because a
    hand-edited file has nobody watching a widget.
    """

    name: str
    given: Any
    used: Any
    reason: str

    @property
    def message(self) -> str:
        """Log-ready sentence naming the option, what it held, and what was used instead."""
        return f"user_options[{self.name!r}] = {self.given!r} {self.reason}; using {self.used!r}"


def iter_fields() -> list[Any]:
    """Return the UserOptions nested schema classes (those exposing a NAME)."""
    return [
        getattr(cst.UserOptions, attr)
        for attr in dir(cst.UserOptions)
        if hasattr(getattr(cst.UserOptions, attr), "NAME")
    ]


def defaults() -> dict[str, Any]:
    """Build the default user_options dict from the UserOptions schema classes."""
    return {field.NAME: field.DEFAULT for field in iter_fields()}


def api_type(name: str) -> str | None:
    """API_TYPE of the named field, or None if the schema has no field by that name."""
    return getattr(_field_by_name(name), "API_TYPE", None)


def validate(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[Correction]]:
    """
    Hold every user option to its schema, returning the clean dict and what was corrected.

    The result always carries every schema field: a missing key takes its default silently,
    since a settings file predating an option is the normal case. Keys the schema does not
    know are absent from the result — this walks the schema, not *raw*.
    """
    given = raw or {}
    clean: dict[str, Any] = {}
    corrections: list[Correction] = []

    for field in iter_fields():
        if field.NAME not in given:
            clean[field.NAME] = field.DEFAULT
            continue
        value, correction = _validated_field(field, given[field.NAME])
        clean[field.NAME] = value
        if correction is not None:
            corrections.append(correction)

    pair_correction = _order_spectrogram_bounds(clean)
    if pair_correction is not None:
        corrections.append(pair_correction)

    return clean, corrections


# ==================================================================================================
def _field_by_name(name: str) -> Any | None:
    """Return the UserOptions nested schema class whose NAME matches, or None."""
    return next((field for field in iter_fields() if name == field.NAME), None)


def _validated_field(field: Any, value: Any) -> tuple[Any, Correction | None]:
    """Dispatch one present value to the check its API_TYPE calls for."""
    if field.API_TYPE in (cst.ApiType.INT, cst.ApiType.FLOAT):
        return _bounded_number(field, value)
    if field.API_TYPE == cst.ApiType.CHOICE:
        return _one_of(field, value)
    if field.API_TYPE == cst.ApiType.TIMEZONE:
        return _valid_timezone(field, value)
    return value, None


def _bounded_number(field: Any, value: Any) -> tuple[Any, Correction | None]:
    cast = int if field.API_TYPE == cst.ApiType.INT else float
    try:
        number = cast(value)
    except (TypeError, ValueError):
        return field.DEFAULT, Correction(field.NAME, value, field.DEFAULT, "is not a number")
    clamped = max(field.MIN, min(field.MAX, number))
    if clamped != number:
        reason = f"is outside [{field.MIN}, {field.MAX}]"
        return clamped, Correction(field.NAME, number, clamped, reason)
    return clamped, None


def _one_of(field: Any, value: Any) -> tuple[Any, Correction | None]:
    allowed = [choice_value for choice_value, _ in field.CHOICES]
    if value in allowed:
        return value, None
    reason = f"is not one of {allowed}"
    return field.DEFAULT, Correction(field.NAME, value, field.DEFAULT, reason)


def _valid_timezone(field: Any, value: Any) -> tuple[Any, Correction | None]:
    resolved = resolve_display_timezone(value, fallback=field.DEFAULT)
    if resolved == value:
        return value, None
    reason = "is not a usable IANA timezone name"
    return resolved, Correction(field.NAME, value, resolved, reason)


def _order_spectrogram_bounds(clean: dict[str, Any]) -> Correction | None:
    """
    Reset the spectrogram colour range in place if its bounds are not strictly increasing.

    Each bound can sit inside MIN/MAX on its own while the pair is still inverted, which
    reaches Plotly as zmin > zmax and renders an unreadable scale.
    """
    low_field = cst.UserOptions.SpectrogramDbMin
    high_field = cst.UserOptions.SpectrogramDbMax
    low, high = clean[low_field.NAME], clean[high_field.NAME]
    if low < high:
        return None

    clean[low_field.NAME] = low_field.DEFAULT
    clean[high_field.NAME] = high_field.DEFAULT
    return Correction(
        name=low_field.NAME,
        given=(low, high),
        used=(low_field.DEFAULT, high_field.DEFAULT),
        reason=f"is not below {high_field.NAME!r}",
    )
