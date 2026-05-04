"""Parse and validate database_options files."""

import logging
from typing import Literal, NamedTuple

import clinical_data_visualizer.constants as cst

logger = logging.getLogger(__name__)


class ValidationIssue(NamedTuple):
    severity: Literal["error", "warning", "info"]
    path: str
    message: str


def normalize_database_options(db_opts: dict) -> None:
    """
    Normalize the database_options dict in place before use.

    Moves top-level ``other::<filename>`` sections into
    ``db_opts["other"]["files"]["<filename>"]`` so that ``OtherDataSource``
    receives per-file config without needing to scan the global dict itself.
    A bare ``"other": {}`` entry is created if only ``other::*`` keys exist,
    so the normal datasource-dispatch loop still triggers the datasource.
    """
    per_file = {k[len("other::") :]: v for k, v in db_opts.items() if k.startswith("other::")}
    if not per_file:
        return
    if "other" not in db_opts:
        db_opts["other"] = {}
    db_opts["other"].setdefault(cst.DatabaseOptions.FILES, {}).update(per_file)


def validate_database_options(db_opts: dict) -> list[ValidationIssue]:
    """
    Full validation pass on a database_options dict.

    Works on both pre- and post-:func:`normalize_database_options` dicts.
    Covers unknown keys, type errors, and redundant entries.
    Returns a list of issues; empty means the config is clean.
    """
    issues: list[ValidationIssue] = []
    for section_name, section in db_opts.items():
        if section_name == cst.DatabaseOptions.GLOBAL:
            continue
        if section_name.startswith("other::"):
            if isinstance(section, dict):
                file_stem = section_name[len("other::") :]
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
    if not signals or not isinstance(signals, dict):
        return
    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            continue
        unknown_sig = set(sig_opts.keys()) - cst.DatabaseOptions.Signal.KNOWN_KEYS
        if unknown_sig:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    path=f"{path_prefix}.signals.{raw_name}",
                    message=(
                        f"Unknown keys: {sorted(unknown_sig)}. "
                        f"Expected: {sorted(cst.DatabaseOptions.Signal.KNOWN_KEYS)}"
                    ),
                )
            )


def _check_types(section: dict, path_prefix: str, issues: list[ValidationIssue]) -> None:
    sig_cst = cst.DatabaseOptions.Signal

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

    fd = section.get(cst.DatabaseOptions.FIELD_DISPLAY)
    if fd is not None and not isinstance(fd, list):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.field_display",
                message=f"Must be a list, got {type(fd).__name__}",
            )
        )

    gf = section.get(cst.DatabaseOptions.GROUPED_FIELDS)
    if gf is not None and not isinstance(gf, dict):
        issues.append(
            ValidationIssue(
                severity="error",
                path=f"{path_prefix}.grouped_fields",
                message=f"Must be a dict, got {type(gf).__name__}",
            )
        )

    signals = signals_raw if isinstance(signals_raw, dict) else {}
    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            continue
        sig_path = f"{path_prefix}.signals.{raw_name}"

        uc = sig_opts.get(sig_cst.UNIT_CONVERSION)
        if uc is not None and not isinstance(uc, (int, float)):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{sig_path}.unit_conversion",
                    message=f"Must be numeric, got {type(uc).__name__!r} ({uc!r})",
                )
            )

        r = sig_opts.get(sig_cst.RANGE)
        if r is not None and not (
            isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) for v in r)  # noqa: PLR2004
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{sig_path}.range",
                    message=f"Must be a 2-element list of numbers, got {r!r}",
                )
            )

        vis = sig_opts.get(sig_cst.VISIBLE)
        if vis is not None and not isinstance(vis, bool):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    path=f"{sig_path}.visible",
                    message=f"Expected bool, got {type(vis).__name__!r} ({vis!r})",
                )
            )


def _check_redundant_entries(
    section: dict, path_prefix: str, issues: list[ValidationIssue]
) -> None:
    sig_cst = cst.DatabaseOptions.Signal
    signals = section.get(cst.DatabaseOptions.SIGNALS)
    if not signals or not isinstance(signals, dict):
        return
    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            continue
        sig_path = f"{path_prefix}.signals.{raw_name}"

        if sig_opts.get(sig_cst.LABEL) == raw_name:
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=sig_path,
                    message=f"label '{raw_name}' is identical to raw_name (can be omitted)",
                )
            )

        uc = sig_opts.get(sig_cst.UNIT_CONVERSION)
        if (
            uc is not None
            and isinstance(uc, (int, float))
            and float(uc) == sig_cst.DEFAULT_UNIT_CONVERSION
        ):
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=sig_path,
                    message=f"unit_conversion={uc} is the default (can be omitted)",
                )
            )

        if sig_opts.get(sig_cst.UNIT) == sig_cst.DEFAULT_UNIT:
            issues.append(
                ValidationIssue(
                    severity="info",
                    path=sig_path,
                    message=f"unit='{sig_cst.DEFAULT_UNIT}' is the default (can be omitted)",
                )
            )
