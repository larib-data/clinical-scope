"""Parse and validate database_options files."""

import logging

import clinical_data_visualizer.constants as cst

logger = logging.getLogger(__name__)


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


def validate_database_options_structure(db_options: dict) -> list[str]:
    """
    Validate the top-level structure of a full database_options dict.

    Returns a list of warning strings (empty when everything looks fine).
    """
    warnings: list[str] = []

    for section_name, section in db_options.items():
        if section_name == cst.DatabaseOptions.GLOBAL or section_name.startswith("other::"):
            continue
        if not isinstance(section, dict):
            continue

        unknown = set(section.keys()) - cst.DatabaseOptions.KNOWN_SECTION_KEYS
        if unknown:
            warnings.append(
                f"[{section_name}] Unknown keys: {sorted(unknown)}. "
                f"Expected: {sorted(cst.DatabaseOptions.KNOWN_SECTION_KEYS)}"
            )

    return warnings


def warn_redundant_entries(raw: dict, datasource_name: str) -> None:
    """Log warnings for unknown keys, identity / default-value entries in the `"signals"` block."""
    signals = raw.get(cst.DatabaseOptions.SIGNALS)
    if not signals or not isinstance(signals, dict):
        return

    sig_cst = cst.DatabaseOptions.Signal

    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            continue

        # Warn about unknown per-signal keys
        unknown = set(sig_opts.keys()) - sig_cst.KNOWN_KEYS
        if unknown:
            logger.warning(
                "Unknown key(s) %s in signal '%s'. Known keys: %s",
                sorted(unknown),
                raw_name,
                sorted(sig_cst.KNOWN_KEYS),
            )

        # label == raw_name is redundant
        if sig_opts.get(sig_cst.LABEL) == raw_name:
            logger.info(
                "[%s] Signal '%s': label '%s' is identical to raw_name (can be omitted).",
                datasource_name,
                raw_name,
                raw_name,
            )

        # unit_conversion == 1.0
        uc = sig_opts.get(sig_cst.UNIT_CONVERSION)
        if uc is not None and float(uc) == sig_cst.DEFAULT_UNIT_CONVERSION:
            logger.info(
                "[%s] Signal '%s': unit_conversion=%.1f is the default (can be omitted).",
                datasource_name,
                raw_name,
                uc,
            )

        # unit == "-"
        if sig_opts.get(sig_cst.UNIT) == sig_cst.DEFAULT_UNIT:
            logger.info(
                "[%s] Signal '%s': unit='%s' is the default (can be omitted).",
                datasource_name,
                raw_name,
                sig_cst.DEFAULT_UNIT,
            )
