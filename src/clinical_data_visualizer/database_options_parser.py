"""
Parse and normalize database_options.json files.

Supports both the new per-signal ``"signals"`` format and the legacy flat
``"data"`` format.  The public entry-point for downstream code is
`normalize_datasource_options()`, which always returns the internal flat
``"data"`` dict so existing processing pipelines are unaffected.
"""

import logging

import clinical_data_visualizer.constants as cst

logger = logging.getLogger(__name__)

# Keys recognized inside a per-signal object (new format)
_SIGNAL_KEYS = {
    "label",
    "unit",
    "unit_conversion",
    "range",
    "period_resampling",
    "priority",
    "color",
    "visible",
    "line_dash",
    "hover_template",
}

# Mapping: new per-signal key -> old flat sub-dict key
_KEY_TO_FLAT = {
    "label": cst.DatabaseOptions.Data.LABEL_CORRESPONDENCE,
    "unit": cst.DatabaseOptions.Data.UNIT_INFO,
    "unit_conversion": cst.DatabaseOptions.Data.UNIT_CONVERSION,
    "range": cst.DatabaseOptions.Data.UNIT_RANGE,
    "period_resampling": cst.DatabaseOptions.Data.PERIOD_RESAMPLING,
    "priority": cst.DatabaseOptions.Data.PRIORITY,
    "color": cst.DatabaseOptions.Data.COLOR,
    "hover_template": cst.DatabaseOptions.Data.HOVER_TEMPLATE,
}

# Default values -- entries matching these are redundant and can be omitted
_DEFAULTS = {
    "label": None,  # special: default = raw_name (checked separately)
    "unit": cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO,
    "unit_conversion": cst.DatabaseOptions.DEFAULT_UNIT_FACTOR,
}

# Top-level keys we expect per datasource section
_KNOWN_DATASOURCE_KEYS = {
    "signals",
    cst.DatabaseOptions.DATA,
    cst.DatabaseOptions.FIELD_DISPLAY,
    cst.DatabaseOptions.NUMERICS,
    cst.DatabaseOptions.GROUPED_FIELDS,
    cst.DatabaseOptions.LOOP,
    cst.DatabaseOptions.ADDITIONAL_INFORMATIONS,
}


def _signals_to_flat_data(signals: dict) -> dict:
    """Convert a ``"signals"`` dict to the legacy flat ``"data"`` dict."""
    flat: dict[str, dict] = {}

    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            logger.warning("Signal '%s' value is not a dict, skipping.", raw_name)
            continue

        for key, value in sig_opts.items():
            if key in _KEY_TO_FLAT:
                flat_key = _KEY_TO_FLAT[key]
                flat.setdefault(flat_key, {})[raw_name] = value
            elif key == "visible":
                flat.setdefault(cst.DatabaseOptions.Data.VISIBLE, {})[raw_name] = value
            elif key == "line_dash":
                flat.setdefault(cst.DatabaseOptions.Data.LINE_DASH, {})[raw_name] = value
            else:
                logger.warning(
                    "Unknown key '%s' in signal '%s'. Known keys: %s",
                    key,
                    raw_name,
                    sorted(_SIGNAL_KEYS),
                )

    return flat


def normalize_datasource_options(raw: dict) -> dict:
    """
    Normalize a single datasource section of database_options.

    If the section uses the new ``"signals"`` key, it is converted to the
    internal flat ``"data"`` format.  If it uses the legacy ``"data"`` key,
    it is returned as-is (with a deprecation warning).  If both are present,
    ``"signals"`` takes precedence.

    Returns a *new* dict (the original is not mutated).
    """
    result = dict(raw)

    has_signals = "signals" in result
    has_data = cst.DatabaseOptions.DATA in result

    if has_signals:
        if has_data:
            logger.warning(
                "Both 'signals' and 'data' found; 'signals' takes precedence. "
                "Remove the deprecated 'data' key."
            )
        result[cst.DatabaseOptions.DATA] = _signals_to_flat_data(result.pop("signals"))

        # Auto-populate field_display from signals keys if not explicitly set
        if cst.DatabaseOptions.FIELD_DISPLAY not in result:
            result[cst.DatabaseOptions.FIELD_DISPLAY] = list(raw["signals"].keys())

    elif has_data:
        logger.info(
            "Legacy 'data' format detected. Consider migrating to the new 'signals' format."
        )

    return result


def validate_database_options_structure(db_options: dict) -> list[str]:
    """
    Validate the top-level structure of a full database_options dict.

    Returns a list of warning strings (empty when everything looks fine).
    """
    warnings: list[str] = []

    for section_name, section in db_options.items():
        if section_name == cst.DatabaseOptions.GLOBAL:
            continue
        if not isinstance(section, dict):
            continue

        unknown = set(section.keys()) - _KNOWN_DATASOURCE_KEYS
        if unknown:
            warnings.append(
                f"[{section_name}] Unknown keys: {sorted(unknown)}. "
                f"Expected: {sorted(_KNOWN_DATASOURCE_KEYS)}"
            )

    return warnings


def warn_redundant_entries(raw: dict, datasource_name: str) -> None:
    """
    Log warnings for identity / default-value entries in the ``"signals"`` block.

    Only operates on the new format.  Called *before* normalization for
    clearest messages.
    """
    signals = raw.get("signals")
    if not signals or not isinstance(signals, dict):
        return

    for raw_name, sig_opts in signals.items():
        if not isinstance(sig_opts, dict):
            continue

        # label == raw_name is redundant
        if sig_opts.get("label") == raw_name:
            logger.info(
                "[%s] Signal '%s': label '%s' is identical to raw_name (can be omitted).",
                datasource_name,
                raw_name,
                raw_name,
            )

        # unit_conversion == 1.0
        uc = sig_opts.get("unit_conversion")
        if uc is not None and float(uc) == _DEFAULTS["unit_conversion"]:
            logger.info(
                "[%s] Signal '%s': unit_conversion=%.1f is the default (can be omitted).",
                datasource_name,
                raw_name,
                uc,
            )

        # unit == "-"
        if sig_opts.get("unit") == _DEFAULTS["unit"]:
            logger.info(
                "[%s] Signal '%s': unit='%s' is the default (can be omitted).",
                datasource_name,
                raw_name,
                _DEFAULTS["unit"],
            )
