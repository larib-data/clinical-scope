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

logger = logging.getLogger(__name__)

# Sentinel value in the ``signal`` column that defines datasource-level defaults
_SENTINEL_DATASOURCE_DEFAULT = "*"

# Columns that must be present in the ``signals`` sheet
_SIGNALS_SHEET_NAME = "signals"
_SIGNALS_REQUIRED_COLS = {"datasource", "signal"}

# Columns that must be present in the ``loops`` sheet
_LOOPS_SHEET_NAME = "loops"
_LOOPS_REQUIRED_COLS = {"datasource", "loop_name", "x_signal", "y_signal"}


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
    return [g.strip() for g in str(value).split(";") if g.strip()]


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

    # Re-wind if BytesIO so we can read the second sheet
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    try:
        loops_df = pd.read_excel(
            file_obj,
            sheet_name=_LOOPS_SHEET_NAME,
            dtype=str,
            keep_default_na=False,
            engine="openpyxl",
        )
    except Exception:  # noqa: BLE001
        logger.debug("No 'loops' sheet found, skipping loop definitions.")
        loops_df = pd.DataFrame(columns=list(_LOOPS_REQUIRED_COLS))

    # ------------------------------------------------------------------
    # Validate required columns
    # ------------------------------------------------------------------
    missing_signal_cols = _SIGNALS_REQUIRED_COLS - set(signals_df.columns)
    if missing_signal_cols:
        msg = f"'signals' sheet is missing required columns: {sorted(missing_signal_cols)}"
        raise ValueError(msg)

    missing_loop_cols = _LOOPS_REQUIRED_COLS - set(loops_df.columns)
    if missing_loop_cols:
        logger.warning(
            "'loops' sheet is missing required columns %s — loop definitions will be skipped.",
            sorted(missing_loop_cols),
        )
        loops_df = pd.DataFrame(columns=list(_LOOPS_REQUIRED_COLS))

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
            # Sentinel row: datasource-level defaults → "numerics"
            # ----------------------------------------------------------
            if signal == _SENTINEL_DATASOURCE_DEFAULT:
                numerics = {}
                pr = _to_float(row.get("period_resampling", ""))
                if pr is not None:
                    numerics["period_resampling"] = pr
                prio = _to_float(row.get("priority", ""))
                if prio is not None:
                    numerics["priority"] = prio
                if numerics:
                    result[ds].setdefault("numerics", {}).update(numerics)
                continue

            # ----------------------------------------------------------
            # Per-signal metadata → _SIGNALS_SHEET_NAME sub-dict
            # ----------------------------------------------------------
            sig_opts = {}

            label = str(row.get("label", "")).strip()
            if label and label != signal:
                sig_opts["label"] = label

            unit = str(row.get("unit", "")).strip()
            if unit:
                sig_opts["unit"] = unit

            uc = _to_float(row.get("unit_conversion", ""))
            if uc is not None:
                sig_opts["unit_conversion"] = uc

            r_min = _to_float(row.get("range_min", ""))
            r_max = _to_float(row.get("range_max", ""))
            if r_min is not None or r_max is not None:
                sig_opts["range"] = [r_min, r_max]

            prio = _to_float(row.get("priority", ""))
            if prio is not None:
                sig_opts["priority"] = prio

            color = str(row.get("color", "")).strip()
            if color:
                sig_opts["color"] = color

            visible_raw = str(row.get("visible", "")).strip()
            if not _is_empty(visible_raw) and not _is_truthy(visible_raw):
                sig_opts["visible"] = False

            line_dash = str(row.get("line_dash", "")).strip()
            if line_dash:
                sig_opts["line_dash"] = line_dash

            pr = _to_float(row.get("period_resampling", ""))
            if pr is not None:
                sig_opts["period_resampling"] = pr

            result[ds].setdefault(_SIGNALS_SHEET_NAME, {})[signal] = sig_opts

            # ----------------------------------------------------------
            # display column → field_display list
            # ----------------------------------------------------------
            display_raw = str(row.get("display", "")).strip()
            if _is_truthy(display_raw):
                fd = result[ds].setdefault("field_display", [])
                if signal not in fd:
                    fd.append(signal)

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

    for group_name, ds_signals in group_membership.items():
        if len(ds_signals) > 1:
            # Global: union of all signals across datasources (preserve order)
            all_signals = []
            for sigs in ds_signals.values():
                all_signals.extend(sigs)
            global_grouped[group_name] = all_signals
        else:
            # Local: single datasource
            (only_ds, signals_list) = next(iter(ds_signals.items()))
            result[only_ds].setdefault("grouped_fields", {})[group_name] = signals_list

    if global_grouped:
        result["global"] = {"grouped_fields": global_grouped}

    # ------------------------------------------------------------------
    # Process loops sheet
    # ------------------------------------------------------------------
    for row_idx, row in loops_df.iterrows():
        try:
            ds = str(row.get("datasource", "")).strip()
            loop_name = str(row.get("loop_name", "")).strip()
            x_sig = str(row.get("x_signal", "")).strip()
            y_sig = str(row.get("y_signal", "")).strip()

            if any(_is_empty(v) for v in (ds, loop_name, x_sig, y_sig)):
                continue

            if ds not in result:
                result[ds] = {}
            result[ds].setdefault("loop", {})[loop_name] = [x_sig, y_sig]

        except Exception:  # noqa: BLE001
            logger.warning("Skipping loops row %s due to unexpected error.", row_idx, exc_info=True)

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


def _try_save_intermediate_json(xlsx_path: Path, db_options: dict) -> None:
    """Try to write the converted dict as JSON alongside the XLSX file."""
    json_path = xlsx_path.with_name(xlsx_path.stem + "_from_xlsx.json")
    try:
        json_path.write_text(
            json.dumps(db_options, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved intermediate JSON to %s", json_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save intermediate JSON to %s: %s", json_path, exc)
