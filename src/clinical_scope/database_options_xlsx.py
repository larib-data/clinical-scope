"""
Convert a database_options XLSX file to the canonical dict format.

The XLSX file must contain a ``signals`` sheet -- one row per signal, or datasource-level
defaults with ``signal = *``. Each registered plot type may add an optional sheet of its own
(``loops``, ...); this module locates whichever sheets the registry names and hands each to
its plot type, which alone says what its rows mean. Registering a new plot type therefore
needs no edit here.

The returned dict is structurally identical to a parsed ``database_options.json``
and is ready to be consumed by :func:`normalize_datasource_options`.

Group scope resolution
----------------------
A group whose signals come from a single datasource is placed in that
datasource's ``grouped_fields``.  A group whose signals span multiple
datasources is placed in ``global.grouped_fields``.  The same group name
must therefore be unique across datasources.
"""

import io
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

import clinical_scope.constants as cst
from clinical_scope.plot_types import registry as plot_types
from clinical_scope.plot_types.base import CellReader

logger = logging.getLogger(__name__)

# Sentinel value in the ``signal`` column that defines datasource-level defaults
_SENTINEL_DATASOURCE_DEFAULT = "*"

_SIGNALS_SHEET_NAME = "signals"
_SIGNALS_REQUIRED_COLS = {"datasource", "signal"}

# Every other sheet belongs to a plot type, which names it and says what its rows mean.


# ---------------------------------------------------------------------------
# Cell-value helpers
# ---------------------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    """Return True when *value* represents an absent/empty cell."""
    if value is None:
        return True
    return str(value).strip() == ""


def _to_float(value: Any) -> float | None:
    """Convert *value* to float; return ``None`` when empty or unconvertible."""
    if _is_empty(value):
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        logger.warning("Cannot convert %r to float, ignoring.", value)
        return None


_TRUTHY_VALUES = {"yes", "1", "true", "oui", "vrai"}
_FALSY_VALUES = {"no", "0", "false", "non", "faux"}


def _is_truthy(value: Any) -> bool:
    """
    Interpret a yes/no cell.

    - Empty / absent → ``True`` (default = shown / visible)
    - ``"yes"``, ``"1"``, ``"true"``, ``"oui"``, ``"vrai"`` (case-insensitive) → ``True``
    - ``"no"``,  ``"0"``, ``"false"`` → ``False``
    - Anything else → ``False`` with a warning
    """
    if _is_empty(value):
        return True
    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized not in _FALSY_VALUES:
        logger.warning("Unrecognized yes/no value %r, treating as 'no'.", value)
    return False


def _parse_groups(value: Any) -> list[str]:
    """Return a list of group names from a semicolon-separated cell value."""
    if _is_empty(value):
        return []
    return [group.strip() for group in str(value).split(";") if group.strip()]


# Lent to each plot type's read_sheet: the reader owns how a cell is read, the plot type owns
# what a row means. Passed rather than imported -- this module imports every definition.
_CELL_READER = CellReader(
    is_empty=_is_empty,
    to_float=_to_float,
    parse_groups=_parse_groups,
)


def _read_optional_sheet(
    file_obj: Any, sheet_name: str, required_cols: set[str], item_label: str
) -> pd.DataFrame:
    """
    Read one optional sheet, normalizing columns and validating *required_cols*.

    Unlike the required ``signals`` sheet, a missing sheet or a missing required column
    both log and fall back to an empty DataFrame rather than raising -- these sheets are
    purely additive, so a bad "loops"/"spectrograms" sheet shouldn't block the rest.
    """
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    try:
        df = pd.read_excel(
            file_obj, sheet_name=sheet_name, dtype=str, keep_default_na=False, engine="openpyxl"
        )
    except Exception:  # noqa: BLE001
        logger.debug("No '%s' sheet found, skipping %s definitions.", sheet_name, item_label)
        return pd.DataFrame(columns=list(required_cols))

    df.columns = [column.strip().lower() for column in df.columns]
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        logger.warning(
            "'%s' sheet is missing required columns %s — %s definitions will be skipped.",
            sheet_name,
            sorted(missing_cols),
            item_label,
        )
        return pd.DataFrame(columns=list(required_cols))
    return df


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def _parse_xlsx_data(file_obj: Any) -> dict:
    """
    Parse XLSX data from a file-like object or path and return the canonical dict.

    Parameters
    ----------
    file_obj
        Anything accepted by :func:`pandas.read_excel` (path, ``Path``, ``BytesIO``, …).

    Returns
    -------
    dict
        Canonical ``database_options`` dict.

    """
    # ------------------------------------------------------------------
    # Read sheets
    # ------------------------------------------------------------------
    try:
        signals_df = pd.read_excel(
            file_obj,
            sheet_name=_SIGNALS_SHEET_NAME,
            dtype=str,
            keep_default_na=False,
            engine="openpyxl",
        )
    except Exception as exc:
        msg = f"Could not read 'signals' sheet: {exc}"
        raise ValueError(msg) from exc

    plot_type_sheets = {
        definition: _read_optional_sheet(
            file_obj, definition.SHEET_NAME, set(definition.SHEET_REQUIRED_COLUMNS), definition.NAME
        )
        for definition in plot_types.AVAILABLE
        if definition.SHEET_NAME
    }

    # ------------------------------------------------------------------
    # Normalize column names and validate required columns -- required sheet only; the
    # optional sheets above already did both inside _read_optional_sheet.
    # ------------------------------------------------------------------
    signals_df.columns = [column.strip().lower() for column in signals_df.columns]
    missing_signal_cols = _SIGNALS_REQUIRED_COLS - set(signals_df.columns)
    if missing_signal_cols:
        msg = f"'signals' sheet is missing required columns: {sorted(missing_signal_cols)}"
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # Process signals sheet
    # ------------------------------------------------------------------
    result: dict[str, Any] = {}

    # Accumulate group membership: {group_name: {datasource: [signal, …]}}
    group_membership: dict[str, dict[str, list[str]]] = {}

    for row_idx, row in signals_df.iterrows():
        try:
            ds = str(row["datasource"]).strip()
            signal = str(row["signal"]).strip()

            if _is_empty(ds) or _is_empty(signal):
                continue

            if ds not in result:
                result[ds] = {}

            # ----------------------------------------------------------
            # Sentinel row: datasource-level defaults → "numerics" / "additional_informations"
            # ----------------------------------------------------------
            if signal == _SENTINEL_DATASOURCE_DEFAULT:
                numerics = {}
                period_resampling = _to_float(row.get("period_resampling", ""))
                if period_resampling is not None:
                    numerics[cst.DatabaseOptions.Numerics.PERIOD_RESAMPLING] = period_resampling
                priority = _to_float(row.get("priority", ""))
                if priority is not None:
                    numerics[cst.DatabaseOptions.Numerics.PRIORITY] = priority
                if numerics:
                    result[ds].setdefault(cst.DatabaseOptions.NUMERICS, {}).update(numerics)

                timezone = _CELL_READER.text(row, "timezone")
                if timezone:
                    result[ds].setdefault(cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {})[
                        cst.DatabaseOptions.AdditionalInformations.TIMEZONE
                    ] = timezone

                trace_config = cst.DatabaseOptions.TraceOptionsConfig
                trace_options = {}
                trace_mode = _CELL_READER.text(row, "trace_mode")
                if trace_mode:
                    trace_options[trace_config.MODE] = trace_mode
                line_width = _to_float(row.get("line_width", ""))
                if line_width is not None:
                    trace_options[trace_config.LINE_WIDTH] = line_width
                opacity = _to_float(row.get("opacity", ""))
                if opacity is not None:
                    trace_options[trace_config.OPACITY] = opacity
                marker_symbol = _CELL_READER.text(row, "marker_symbol")
                if marker_symbol:
                    trace_options[trace_config.MARKER_SYMBOL] = marker_symbol
                if trace_options:
                    result[ds].setdefault(cst.DatabaseOptions.TRACE_OPTIONS, {}).update(
                        trace_options
                    )

                continue

            # ----------------------------------------------------------
            # Per-signal metadata → the "signals" config section
            # ----------------------------------------------------------
            signal_config = cst.DatabaseOptions.SignalConfig
            signal_options = {}

            label = _CELL_READER.text(row, "label")
            if label and label != signal:
                signal_options[signal_config.LABEL] = label

            unit = _CELL_READER.text(row, "unit")
            if unit:
                signal_options[signal_config.UNIT] = unit

            unit_conversion = _to_float(row.get("unit_conversion", ""))
            if unit_conversion is not None:
                signal_options[signal_config.UNIT_CONVERSION] = unit_conversion

            range_min = _to_float(row.get("range_min", ""))
            range_max = _to_float(row.get("range_max", ""))
            if range_min is not None or range_max is not None:
                signal_options[signal_config.RANGE] = [range_min, range_max]

            priority = _to_float(row.get("priority", ""))
            if priority is not None:
                signal_options[signal_config.PRIORITY] = priority

            color = _CELL_READER.text(row, "color")
            if color:
                signal_options[signal_config.COLOR] = color

            visible_raw = _CELL_READER.text(row, "visible")
            if not _is_empty(visible_raw) and not _is_truthy(visible_raw):
                signal_options[signal_config.VISIBLE] = False

            line_dash = _CELL_READER.text(row, "line_dash")
            if line_dash:
                signal_options[signal_config.LINE_DASH] = line_dash

            period_resampling = _to_float(row.get("period_resampling", ""))
            if period_resampling is not None:
                signal_options[signal_config.PERIOD_RESAMPLING] = period_resampling

            hover_template = _CELL_READER.text(row, "hover_template")
            if hover_template:
                signal_options[signal_config.HOVER_TEMPLATE] = hover_template

            # Warn about fields that are only meaningful in the sentinel (*) row
            sentinel_only_columns = (
                "timezone",
                "trace_mode",
                "line_width",
                "opacity",
                "marker_symbol",
            )
            for column_name in sentinel_only_columns:
                if _CELL_READER.text(row, column_name):
                    logger.warning(
                        "Row %s (datasource=%r, signal=%r): '%s' is only valid in the "
                        "sentinel ('*') row — ignored for per-signal rows.",
                        row_idx,
                        ds,
                        signal,
                        column_name,
                    )

            # The config section, not the sheet it was read from: the two share a name today,
            # but renaming the sheet must not silently write a different section.
            result[ds].setdefault(cst.DatabaseOptions.SIGNALS, {})[signal] = signal_options

            # ----------------------------------------------------------
            # display column → field_display list
            # ----------------------------------------------------------
            display_raw = _CELL_READER.text(row, "display")
            field_display = result[ds].setdefault(cst.DatabaseOptions.FIELD_DISPLAY, [])
            if _is_truthy(display_raw) and signal not in field_display:
                field_display.append(signal)

            # ----------------------------------------------------------
            # groups column → collect membership for later resolution
            # ----------------------------------------------------------
            for group_name in _parse_groups(row.get("groups", "")):
                group_membership.setdefault(group_name, {}).setdefault(ds, []).append(signal)

        except Exception:
            logger.warning(
                "Skipping signals row %s due to unexpected error.", row_idx, exc_info=True
            )

    # ------------------------------------------------------------------
    # Resolve group scope: local (single datasource) vs global (multi)
    # ------------------------------------------------------------------
    global_grouped: dict[str, list[str]] = {}

    for group_name, signals_by_datasource in group_membership.items():
        if len(signals_by_datasource) > 1:
            # Global: union of all signals across datasources (preserve order). Signals from an
            # 'other::<stem>' section are renamed '<stem>::<signal>' at load time, so a bare name
            # would never resolve here — emit the qualified reference instead.
            all_signals = []
            for datasource_name, signal_names in signals_by_datasource.items():
                prefix = (
                    f"{datasource_name}{cst.QUALIFIED_NAME_SEPARATOR}"
                    if datasource_name.startswith(cst.OTHER_FILE_PREFIX)
                    else ""
                )
                all_signals.extend(f"{prefix}{signal}" for signal in signal_names)
            global_grouped[group_name] = all_signals
        else:
            (only_ds, signals_list) = next(iter(signals_by_datasource.items()))
            result[only_ds].setdefault(cst.DatabaseOptions.GROUPED_FIELDS, {})[group_name] = (
                signals_list
            )

    if global_grouped:
        result[cst.DatabaseOptions.GLOBAL] = {cst.DatabaseOptions.GROUPED_FIELDS: global_grouped}

    # ------------------------------------------------------------------
    # Process each plot type's own sheet
    # ------------------------------------------------------------------
    # The reader transcribes and the plot type interprets: a row's meaning lives beside the
    # JSON keys it produces, so the two spellings of one grammar cannot drift apart.
    for definition, sheet in plot_type_sheets.items():
        try:
            by_datasource = definition.read_sheet(sheet, _CELL_READER)
        except Exception:
            logger.warning(
                "Could not read the '%s' sheet; skipping %s definitions.",
                definition.SHEET_NAME,
                definition.NAME,
                exc_info=True,
            )
            continue
        for datasource_name, entries in by_datasource.items():
            if entries:
                result.setdefault(datasource_name, {}).setdefault(
                    definition.SECTION_KEY, {}
                ).update(entries)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def xlsx_to_database_options(path: Path) -> dict:
    """
    Read a database_options XLSX file from *path* and return a canonical dict.

    After conversion the intermediate result is saved as a JSON file named
    ``<stem>_from_xlsx.json`` next to the source file.  A warning is logged
    if the write fails (e.g. the directory is read-only).

    Parameters
    ----------
    path
        Path to the ``.xlsx`` file.

    Returns
    -------
    dict
        Canonical ``database_options`` dict, structurally identical to one
        parsed from ``database_options.json``.

    """
    path = Path(path)
    result = _parse_xlsx_data(path)
    _try_save_intermediate_json(path, result)
    return result


def xlsx_bytes_to_database_options(data: bytes) -> dict:
    """
    Parse database options from raw XLSX *data* bytes.

    No intermediate JSON file is saved (the original file path is unknown).

    Parameters
    ----------
    data
        Raw bytes of an ``.xlsx`` file.

    Returns
    -------
    dict
        Canonical ``database_options`` dict.

    """
    return _parse_xlsx_data(io.BytesIO(data))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_save_intermediate_json(xlsx_path: Path, database_options: dict) -> None:
    """Try to write the converted dict as JSON alongside the XLSX file."""
    json_path = xlsx_path.with_name(xlsx_path.stem + "_from_xlsx.json")
    try:
        json_path.write_text(
            json.dumps(database_options, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved intermediate JSON to %s", json_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save intermediate JSON to %s: %s", json_path, exc)
