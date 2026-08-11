"""
Convert a database_options XLSX file to the canonical dict format.

The XLSX file must contain two sheets:

- ``signals``: one row per signal (or datasource-level defaults with ``signal = *``)
- ``loops``: one row per PV-loop definition (optional sheet)

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

logger = logging.getLogger(__name__)

# Sentinel value in the ``signal`` column that defines datasource-level defaults
_SENTINEL_DATASOURCE_DEFAULT = "*"

_SIGNALS_SHEET_NAME = "signals"
_SIGNALS_REQUIRED_COLS = {"datasource", "signal"}

_LOOPS_SHEET_NAME = "loops"
_LOOPS_REQUIRED_COLS = {"datasource", "loop_name", "x_signal", "y_signal"}

_SPECTROGRAMS_SHEET_NAME = "spectrograms"
_SPECTROGRAMS_REQUIRED_COLS = {"datasource", "spectrogram_name", "signal", "freq_min", "freq_max"}

_PSDS_SHEET_NAME = "psds"
_PSDS_REQUIRED_COLS = {"datasource", "groups", "signal", "freq_min", "freq_max"}


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


def _resolve_shared_range(
    current: list[float] | None,
    candidate: list[float] | None,
    *,
    label: str,
    row_idx: int,
    group_name: str,
    ds: str,
) -> list[float] | None:
    """
    Keep the first ``[min, max]`` seen for a group; a later mismatch warns and is dropped.

    A psds group is denormalized across rows, but the axis range it produces is shared by
    the whole subplot -- so once a row has set it, later rows can only confirm or conflict.
    """
    if candidate is None:
        return current
    if current is None:
        return candidate
    if candidate != current:
        logger.warning(
            "psds row %s: %s %s conflicts with %s already set for group %r (datasource %r); "
            "keeping the first.",
            row_idx,
            label,
            candidate,
            current,
            group_name,
            ds,
        )
    return current


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

    loops_df = _read_optional_sheet(file_obj, _LOOPS_SHEET_NAME, _LOOPS_REQUIRED_COLS, "loop")
    spectrograms_df = _read_optional_sheet(
        file_obj, _SPECTROGRAMS_SHEET_NAME, _SPECTROGRAMS_REQUIRED_COLS, "spectrogram"
    )
    psds_df = _read_optional_sheet(file_obj, _PSDS_SHEET_NAME, _PSDS_REQUIRED_COLS, "psd")

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
                    numerics["period_resampling"] = period_resampling
                priority = _to_float(row.get("priority", ""))
                if priority is not None:
                    numerics["priority"] = priority
                if numerics:
                    result[ds].setdefault("numerics", {}).update(numerics)

                timezone = str(row.get("timezone", "")).strip()
                if timezone:
                    result[ds].setdefault("additional_informations", {})["timezone"] = timezone

                trace_config = cst.DatabaseOptions.TraceOptionsConfig
                trace_options = {}
                trace_mode = str(row.get("trace_mode", "")).strip()
                if trace_mode:
                    trace_options[trace_config.MODE] = trace_mode
                line_width = _to_float(row.get("line_width", ""))
                if line_width is not None:
                    trace_options[trace_config.LINE_WIDTH] = line_width
                opacity = _to_float(row.get("opacity", ""))
                if opacity is not None:
                    trace_options[trace_config.OPACITY] = opacity
                marker_symbol = str(row.get("marker_symbol", "")).strip()
                if marker_symbol:
                    trace_options[trace_config.MARKER_SYMBOL] = marker_symbol
                if trace_options:
                    result[ds].setdefault(cst.DatabaseOptions.TRACE_OPTIONS, {}).update(
                        trace_options
                    )

                continue

            # ----------------------------------------------------------
            # Per-signal metadata → _SIGNALS_SHEET_NAME sub-dict
            # ----------------------------------------------------------
            signal_options = {}

            label = str(row.get("label", "")).strip()
            if label and label != signal:
                signal_options["label"] = label

            unit = str(row.get("unit", "")).strip()
            if unit:
                signal_options["unit"] = unit

            unit_conversion = _to_float(row.get("unit_conversion", ""))
            if unit_conversion is not None:
                signal_options["unit_conversion"] = unit_conversion

            range_min = _to_float(row.get("range_min", ""))
            range_max = _to_float(row.get("range_max", ""))
            if range_min is not None or range_max is not None:
                signal_options["range"] = [range_min, range_max]

            priority = _to_float(row.get("priority", ""))
            if priority is not None:
                signal_options["priority"] = priority

            color = str(row.get("color", "")).strip()
            if color:
                signal_options["color"] = color

            visible_raw = str(row.get("visible", "")).strip()
            if not _is_empty(visible_raw) and not _is_truthy(visible_raw):
                signal_options["visible"] = False

            line_dash = str(row.get("line_dash", "")).strip()
            if line_dash:
                signal_options["line_dash"] = line_dash

            period_resampling = _to_float(row.get("period_resampling", ""))
            if period_resampling is not None:
                signal_options["period_resampling"] = period_resampling

            hover_template = str(row.get("hover_template", "")).strip()
            if hover_template:
                signal_options["hover_template"] = hover_template

            # Warn about fields that are only meaningful in the sentinel (*) row
            sentinel_only_columns = (
                "timezone",
                "trace_mode",
                "line_width",
                "opacity",
                "marker_symbol",
            )
            for column_name in sentinel_only_columns:
                if str(row.get(column_name, "")).strip():
                    logger.warning(
                        "Row %s (datasource=%r, signal=%r): '%s' is only valid in the "
                        "sentinel ('*') row — ignored for per-signal rows.",
                        row_idx,
                        ds,
                        signal,
                        column_name,
                    )

            result[ds].setdefault(_SIGNALS_SHEET_NAME, {})[signal] = signal_options

            # ----------------------------------------------------------
            # display column → field_display list
            # ----------------------------------------------------------
            display_raw = str(row.get("display", "")).strip()
            field_display = result[ds].setdefault("field_display", [])
            if _is_truthy(display_raw) and signal not in field_display:
                field_display.append(signal)

            # ----------------------------------------------------------
            # groups column → collect membership for later resolution
            # ----------------------------------------------------------
            for group_name in _parse_groups(row.get("groups", "")):
                group_membership.setdefault(group_name, {}).setdefault(ds, []).append(signal)

        except Exception:  # noqa: BLE001
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
            result[only_ds].setdefault("grouped_fields", {})[group_name] = signals_list

    if global_grouped:
        result[cst.DatabaseOptions.GLOBAL] = {"grouped_fields": global_grouped}

    # ------------------------------------------------------------------
    # Process loops sheet
    # ------------------------------------------------------------------
    for row_idx, row in loops_df.iterrows():
        try:
            ds = str(row.get("datasource", "")).strip()
            loop_name = str(row.get("loop_name", "")).strip()
            x_signal = str(row.get("x_signal", "")).strip()
            y_signal = str(row.get("y_signal", "")).strip()

            if any(_is_empty(field) for field in (ds, loop_name, x_signal, y_signal)):
                continue

            if ds not in result:
                result[ds] = {}
            result[ds].setdefault("loop", {})[loop_name] = [x_signal, y_signal]

        except Exception:  # noqa: BLE001
            logger.warning("Skipping loops row %s due to unexpected error.", row_idx, exc_info=True)

    # ------------------------------------------------------------------
    # Process spectrograms sheet
    # ------------------------------------------------------------------
    spectrogram_config = cst.DatabaseOptions.SpectrogramConfig
    for row_idx, row in spectrograms_df.iterrows():
        try:
            ds = str(row.get("datasource", "")).strip()
            spectrogram_name = str(row.get("spectrogram_name", "")).strip()
            signal = str(row.get("signal", "")).strip()
            freq_min = _to_float(row.get("freq_min", ""))
            freq_max = _to_float(row.get("freq_max", ""))

            if any(_is_empty(field) for field in (ds, spectrogram_name, signal)):
                continue
            if freq_min is None or freq_max is None:
                logger.warning(
                    "Skipping spectrograms row %s: freq_min/freq_max must both be set.", row_idx
                )
                continue

            spectrogram_options: dict[str, Any] = {
                spectrogram_config.SIGNAL: signal,
                spectrogram_config.FREQ_RANGE: [freq_min, freq_max],
            }

            db_min = _to_float(row.get("db_min", ""))
            db_max = _to_float(row.get("db_max", ""))
            if db_min is not None and db_max is not None:
                spectrogram_options[spectrogram_config.DB_RANGE] = [db_min, db_max]
            elif db_min is not None or db_max is not None:
                logger.warning(
                    "Skipping db_range for spectrograms row %s: db_min/db_max must both be set.",
                    row_idx,
                )

            window_s = _to_float(row.get("window_s", ""))
            if window_s is not None:
                spectrogram_options[spectrogram_config.WINDOW_S] = window_s
            overlap = _to_float(row.get("overlap", ""))
            if overlap is not None:
                spectrogram_options[spectrogram_config.OVERLAP] = overlap

            if ds not in result:
                result[ds] = {}
            result[ds].setdefault(cst.DatabaseOptions.SPECTROGRAM, {})[spectrogram_name] = (
                spectrogram_options
            )

        except Exception:  # noqa: BLE001
            logger.warning(
                "Skipping spectrograms row %s due to unexpected error.", row_idx, exc_info=True
            )

    # ------------------------------------------------------------------
    # Process psds sheet
    # ------------------------------------------------------------------
    # Two-phase, mirroring the signals sheet's groups resolution above: accumulate every
    # row's contribution per (datasource, group) first, then resolve each group once --
    # so a freq/db mismatch across rows can be reported instead of silently dropped.
    psd_config = cst.DatabaseOptions.PsdConfig
    psd_entry = psd_config.Entry
    psd_membership: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for row_idx, row in psds_df.iterrows():
        try:
            ds = str(row.get("datasource", "")).strip()
            signal = str(row.get("signal", "")).strip()
            groups_list = _parse_groups(row.get("groups", ""))

            if _is_empty(ds) or _is_empty(signal) or not groups_list:
                continue

            contribution: dict[str, Any] = {
                "row_idx": row_idx,
                psd_entry.SIGNAL: signal,
                "freq_min": _to_float(row.get("freq_min", "")),
                "freq_max": _to_float(row.get("freq_max", "")),
                "db_min": _to_float(row.get("db_min", "")),
                "db_max": _to_float(row.get("db_max", "")),
            }
            window_s = _to_float(row.get("window_s", ""))
            if window_s is not None:
                contribution[psd_entry.WINDOW_S] = window_s
            overlap = _to_float(row.get("overlap", ""))
            if overlap is not None:
                contribution[psd_entry.OVERLAP] = overlap
            label = str(row.get("label", "")).strip()
            if label:
                contribution[psd_entry.LABEL] = label
            color = str(row.get("color", "")).strip()
            if color:
                contribution[psd_entry.COLOR] = color
            line_dash = str(row.get("line_dash", "")).strip()
            if line_dash:
                contribution[psd_entry.LINE_DASH] = line_dash

            for group_name in groups_list:
                psd_membership.setdefault((ds, group_name), []).append(contribution)

        except Exception:  # noqa: BLE001
            logger.warning("Skipping psds row %s due to unexpected error.", row_idx, exc_info=True)

    for (ds, group_name), contributions in psd_membership.items():
        freq_range = None
        db_range = None
        entries: list[Any] = []

        for contribution in contributions:
            row_idx = contribution["row_idx"]

            freq_min, freq_max = contribution["freq_min"], contribution["freq_max"]
            freq_candidate = (
                [freq_min, freq_max] if freq_min is not None and freq_max is not None else None
            )
            freq_range = _resolve_shared_range(
                freq_range,
                freq_candidate,
                label="freq_range",
                row_idx=row_idx,
                group_name=group_name,
                ds=ds,
            )

            db_min, db_max = contribution["db_min"], contribution["db_max"]
            if db_min is not None and db_max is not None:
                db_range = _resolve_shared_range(
                    db_range,
                    [db_min, db_max],
                    label="db_range",
                    row_idx=row_idx,
                    group_name=group_name,
                    ds=ds,
                )
            elif db_min is not None or db_max is not None:
                logger.warning(
                    "Skipping db_range for psds row %s: db_min/db_max must both be set.", row_idx
                )

            # Shorthand: a plain ref string when the row set no per-entry override.
            entry = {
                key: contribution[key]
                for key in (
                    psd_entry.SIGNAL,
                    psd_entry.WINDOW_S,
                    psd_entry.OVERLAP,
                    psd_entry.LABEL,
                    psd_entry.COLOR,
                    psd_entry.LINE_DASH,
                )
                if key in contribution
            }
            entries.append(entry[psd_entry.SIGNAL] if len(entry) == 1 else entry)

        if freq_range is None:
            logger.warning(
                "Skipping PSD group %r (datasource %r): freq_min/freq_max must be set on "
                "at least one row.",
                group_name,
                ds,
            )
            continue

        psd_options: dict[str, Any] = {
            psd_config.SIGNALS: entries,
            psd_config.FREQ_RANGE: freq_range,
        }
        if db_range is not None:
            psd_options[psd_config.DB_RANGE] = db_range

        if ds not in result:
            result[ds] = {}
        result[ds].setdefault(cst.DatabaseOptions.PSD, {})[group_name] = psd_options

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
