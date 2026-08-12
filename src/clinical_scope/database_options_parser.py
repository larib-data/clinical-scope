"""Parse and validate database_options files."""

import logging
from typing import Literal, NamedTuple

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


class ValidationIssue(NamedTuple):
    severity: Literal["error", "warning", "info"]
    path: str
    message: str


def normalize_database_options(database_options: dict) -> None:
    """
    Normalize the database_options dict in place before use.

    Moves top-level ``other::<filename>`` sections into
    ``database_options["other"]["files"]["<filename>"]`` so that ``OtherDataSource``
    receives per-file config without needing to scan the global dict itself.
    A bare ``"other": {}`` entry is created if only ``other::*`` keys exist,
    so the normal datasource-dispatch loop still triggers the datasource.
    """
    per_file = {
        key[len(cst.OTHER_FILE_PREFIX) :]: value
        for key, value in database_options.items()
        if key.startswith(cst.OTHER_FILE_PREFIX)
    }
    if not per_file:
        return
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
    _check_redundant_entries(section, path_prefix, issues)


def _check_unknown_keys(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    unknown = set(section.keys()) - cst.DatabaseOptions.KNOWN_SECTION_KEYS
    if unknown:
        issues.append(
            ValidationIssue(
                severity="warning",
                path=path_prefix,
                message=(
                    f"Unknown keys: {sorted(unknown)}. "
                    f"Expected: {sorted(cst.DatabaseOptions.KNOWN_SECTION_KEYS)}"
                ),
            )
        )
    signals = section.get(cst.DatabaseOptions.SIGNALS)
    if signals and isinstance(signals, dict):
        for raw_name, signal_options in signals.items():
            if not isinstance(signal_options, dict):
                continue
            unknown_sig = set(signal_options.keys()) - cst.DatabaseOptions.SignalConfig.KNOWN_KEYS
            if unknown_sig:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        path=f"{path_prefix}.signals.{raw_name}",
                        message=(
                            f"Unknown keys: {sorted(unknown_sig)}. "
                            f"Expected: {sorted(cst.DatabaseOptions.SignalConfig.KNOWN_KEYS)}"
                        ),
                    )
                )

    for section_key, config_cls in (
        (cst.DatabaseOptions.SPECTROGRAM, cst.DatabaseOptions.SpectrogramConfig),
        (cst.DatabaseOptions.PSD, cst.DatabaseOptions.PsdConfig),
    ):
        entries = section.get(section_key)
        if not entries or not isinstance(entries, dict):
            continue
        for entry_name, entry_options in entries.items():
            if not isinstance(entry_options, dict):
                continue
            unknown_entry = set(entry_options.keys()) - config_cls.KNOWN_KEYS
            if unknown_entry:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        path=f"{path_prefix}.{section_key}.{entry_name}",
                        message=(
                            f"Unknown keys: {sorted(unknown_entry)}. "
                            f"Expected: {sorted(config_cls.KNOWN_KEYS)}"
                        ),
                    )
                )


def _check_spectral_types(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    """Validate ``spectrogram`` and ``psd``, which differ only in how they name their signals."""
    spectrogram_config = cst.DatabaseOptions.SpectrogramConfig
    psd_config = cst.DatabaseOptions.PsdConfig

    # Each row carries its own config class: the two schemas happen to share key *names* today,
    # but reading one section's keys off the other's class would hide the day they diverge.
    for section_key, config_cls in (
        (cst.DatabaseOptions.SPECTROGRAM, spectrogram_config),
        (cst.DatabaseOptions.PSD, psd_config),
    ):
        entries = section.get(section_key)
        if entries is not None and not isinstance(entries, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{path_prefix}.{section_key}",
                    message=f"Must be a dict, got {type(entries).__name__}",
                )
            )
            continue

        for entry_name, entry_options in (entries or {}).items():
            if not isinstance(entry_options, dict):
                continue
            entry_path = f"{path_prefix}.{section_key}.{entry_name}"

            if config_cls is psd_config:
                names = entry_options.get(psd_config.SIGNALS)
                if not (isinstance(names, list) and names):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            path=f"{entry_path}.signals",
                            message=(
                                f"Must be a required non-empty list of signal names, got {names!r}"
                            ),
                        )
                    )
                else:
                    _check_psd_entries(names, entry_path, issues)
            elif spectrogram_config.SIGNAL not in entry_options:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        path=entry_path,
                        message="Missing required key 'signal'",
                    )
                )

            freq_range = entry_options.get(config_cls.FREQ_RANGE)
            if freq_range is None or not (
                isinstance(freq_range, list)
                and len(freq_range) == 2  # noqa: PLR2004
                and all(isinstance(bound, (int, float)) for bound in freq_range)
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        path=f"{entry_path}.freq_range",
                        message=(
                            f"Must be a required 2-element list of numbers, got {freq_range!r}"
                        ),
                    )
                )


def _check_psd_entries(entries: list, entry_path: str, issues: list[ValidationIssue]) -> None:
    """Validate each ``psd.<name>.signals`` item: a plain ref string, or an Entry dict."""
    entry_config = cst.DatabaseOptions.PsdConfig.Entry
    for item_idx, item in enumerate(entries):
        if isinstance(item, str):
            continue
        item_path = f"{entry_path}.signals[{item_idx}]"
        if not isinstance(item, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=item_path,
                    message=f"Must be a signal name string or a dict, got {item!r}",
                )
            )
            continue
        if not isinstance(item.get(entry_config.SIGNAL), str) or not item.get(entry_config.SIGNAL):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=item_path,
                    message="Missing required key 'signal'",
                )
            )
        unknown_item = set(item.keys()) - entry_config.KNOWN_KEYS
        if unknown_item:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    path=item_path,
                    message=(
                        f"Unknown keys: {sorted(unknown_item)}. "
                        f"Expected: {sorted(entry_config.KNOWN_KEYS)}"
                    ),
                )
            )


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
                ValidationIssue(
                    severity="warning",
                    path=f"{path_prefix}.trace_options",
                    message=(
                        f"Unknown keys: {sorted(unknown_trace)}. "
                        f"Expected: {sorted(known_trace_keys)}"
                    ),
                )
            )

    _check_spectral_types(section, path_prefix, issues)

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
