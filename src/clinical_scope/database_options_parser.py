"""Parse and validate database_options files."""

import logging

import clinical_scope.constants as cst
from clinical_scope.plot_types import registry as plot_types
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)


def _known_section_keys() -> frozenset[str]:
    """Every section key a config may set: the fixed ones, plus one per registered type."""
    return cst.DatabaseOptions.KNOWN_SECTION_KEYS | plot_types.SECTION_KEYS


def normalize_database_options(database_options: dict) -> None:
    """
    Normalize the database_options dict in place before use.

    Moves top-level ``other::<filename>`` sections into
    ``database_options["other"]["files"]["<filename>"]`` so that ``OtherDataSource``
    receives per-file config without needing to scan the global dict itself.
    A bare ``"other": {}`` entry is created if only ``other::*`` keys exist,
    so the normal datasource-dispatch loop still triggers the datasource.

    The source keys are removed, not copied: leaving both spellings in place made
    :func:`validate_database_options` walk each per-file section twice and report every
    issue twice. Idempotent -- a second call finds nothing left to move.
    """
    source_keys = [key for key in database_options if key.startswith(cst.OTHER_FILE_PREFIX)]
    if not source_keys:
        return
    per_file = {key[len(cst.OTHER_FILE_PREFIX) :]: database_options.pop(key) for key in source_keys}
    if "other" not in database_options:
        database_options["other"] = {}
    database_options["other"].setdefault(cst.DatabaseOptions.FILES, {}).update(per_file)


def validate_database_options(database_options: dict) -> list[ValidationIssue]:
    """
    Full validation pass on a database_options dict.

    Works on both pre- and post-:func:`normalize_database_options` dicts.
    Covers unknown keys, type errors, and redundant entries.
    Returns a list of issues; empty means the config is clean.
    """
    issues: list[ValidationIssue] = []
    for section_name, section in database_options.items():
        if section_name == cst.DatabaseOptions.GLOBAL:
            continue
        if section_name.startswith(cst.OTHER_FILE_PREFIX):
            if isinstance(section, dict):
                file_stem = section_name[len(cst.OTHER_FILE_PREFIX) :]
                _validate_section(section, f"other.files.{file_stem}", issues)
            continue
        if not isinstance(section, dict):
            continue
        _validate_section(section, section_name, issues)
        if section_name == "other":
            for file_stem, file_opts in section.get(cst.DatabaseOptions.FILES, {}).items():
                if isinstance(file_opts, dict):
                    _validate_section(file_opts, f"other.files.{file_stem}", issues)
    return issues


def _validate_section(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    _check_unknown_keys(section, path_prefix, issues)
    _check_types(section, path_prefix, issues)
    _check_plot_types(section, path_prefix, issues)
    _check_redundant_entries(section, path_prefix, issues)


def _check_unknown_keys(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    known = _known_section_keys()
    unknown = set(section.keys()) - known
    if unknown:
        issues.append(ValidationIssue.unknown_keys(path_prefix, unknown, known))
    signals = section.get(cst.DatabaseOptions.SIGNALS)
    if signals and isinstance(signals, dict):
        for raw_name, signal_options in signals.items():
            if not isinstance(signal_options, dict):
                continue
            unknown_sig = set(signal_options.keys()) - cst.DatabaseOptions.SignalConfig.KNOWN_KEYS
            if unknown_sig:
                issues.append(
                    ValidationIssue.unknown_keys(
                        f"{path_prefix}.signals.{raw_name}",
                        unknown_sig,
                        cst.DatabaseOptions.SignalConfig.KNOWN_KEYS,
                    )
                )


def _check_plot_types(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    """
    Hand each plot type its own section to check.

    The parser knows a section may configure plot types; it does not know what any of them
    requires. A section no plot type vouches for is one the parser cannot silently accept: it
    would validate cleanly and then render nothing.
    """
    for definition in plot_types.DERIVED:
        issues.extend(definition.validate(section.get(definition.SECTION_KEY), path_prefix))


def _check_types(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    signal_config = cst.DatabaseOptions.SignalConfig

    signals_raw = section.get(cst.DatabaseOptions.SIGNALS)
    if signals_raw is not None and not isinstance(signals_raw, dict):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.signals",
                message=f"Must be a dict, got {type(signals_raw).__name__}",
            )
        )
        return

    field_display = section.get(cst.DatabaseOptions.FIELD_DISPLAY)
    if field_display is not None and not isinstance(field_display, list):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.field_display",
                message=f"Must be a list, got {type(field_display).__name__}",
            )
        )

    grouped_fields = section.get(cst.DatabaseOptions.GROUPED_FIELDS)
    if grouped_fields is not None and not isinstance(grouped_fields, dict):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.grouped_fields",
                message=f"Must be a dict, got {type(grouped_fields).__name__}",
            )
        )

    trace_options = section.get(cst.DatabaseOptions.TRACE_OPTIONS)
    if trace_options is not None and not isinstance(trace_options, dict):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.trace_options",
                message=f"Must be a dict, got {type(trace_options).__name__}",
            )
        )
    elif isinstance(trace_options, dict):
        known_trace_keys = cst.DatabaseOptions.TraceOptionsConfig.KNOWN_KEYS
        unknown_trace = set(trace_options) - known_trace_keys
        if unknown_trace:
            issues.append(
                ValidationIssue.unknown_keys(
                    f"{path_prefix}.trace_options", unknown_trace, known_trace_keys
                )
            )

    signals = signals_raw if isinstance(signals_raw, dict) else {}
    for raw_name, signal_options in signals.items():
        if not isinstance(signal_options, dict):
            continue
        signal_path = f"{path_prefix}.signals.{raw_name}"

        unit_conversion = signal_options.get(signal_config.UNIT_CONVERSION)
        if unit_conversion is not None and not isinstance(unit_conversion, (int, float)):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{signal_path}.unit_conversion",
                    message=(
                        f"Must be numeric, got {type(unit_conversion).__name__!r} "
                        f"({unit_conversion!r})"
                    ),
                )
            )

        range_value = signal_options.get(signal_config.RANGE)
        if range_value is not None and not (
            isinstance(range_value, list)
            and len(range_value) == 2  # noqa: PLR2004
            and all(isinstance(bound, (int, float)) for bound in range_value)
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{signal_path}.range",
                    message=f"Must be a 2-element list of numbers, got {range_value!r}",
                )
            )

        visible = signal_options.get(signal_config.VISIBLE)
        if visible is not None and not isinstance(visible, bool):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    path=f"{signal_path}.visible",
                    message=f"Expected bool, got {type(visible).__name__!r} ({visible!r})",
                )
            )


def _check_redundant_entries(
    section: dict, path_prefix: str, issues: list[ValidationIssue]
) -> None:
    signal_config = cst.DatabaseOptions.SignalConfig
    signals = section.get(cst.DatabaseOptions.SIGNALS)
    if not signals or not isinstance(signals, dict):
        return
    for raw_name, signal_options in signals.items():
        if not isinstance(signal_options, dict):
            continue
        signal_path = f"{path_prefix}.signals.{raw_name}"

        if signal_options.get(signal_config.LABEL) == raw_name:
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=signal_path,
                    message=f"label '{raw_name}' is identical to raw_name (can be omitted)",
                )
            )

        unit_conversion = signal_options.get(signal_config.UNIT_CONVERSION)
        if (
            unit_conversion is not None
            and isinstance(unit_conversion, (int, float))
            and float(unit_conversion) == signal_config.DEFAULT_UNIT_CONVERSION
        ):
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=signal_path,
                    message=f"unit_conversion={unit_conversion} is the default (can be omitted)",
                )
            )

        if signal_options.get(signal_config.UNIT) == signal_config.DEFAULT_UNIT:
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=signal_path,
                    message=f"unit='{signal_config.DEFAULT_UNIT}' is the default (can be omitted)",
                )
            )
