"""Leaf half of the ``psd`` plot type: power spectral density against frequency."""

import logging
from collections.abc import Callable
from typing import Any

from clinical_scope.plot_types.base import PlotTypeSchema, check_freq_range
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)


def _resolve_shared_range(
    current: list[float] | None,
    candidate: list[float] | None,
    *,
    label: str,
    row_idx: int,
    group_name: str,
    datasource: str,
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
            datasource,
        )
    return current


class PsdSchema(PlotTypeSchema):
    """
    A PSD plots power against frequency, several signals overlaid on one subplot.

    Frequency on x, so nothing about the time axis applies; one entry names several signals
    precisely so their spectra can be compared, which is what the shared subplot is for.

    The JSON keys and the spreadsheet columns below are one schema in two spellings -- the
    sheet requires ``freq_min``/``freq_max`` precisely because ``FREQ_RANGE`` is required --
    so they are declared together, where they cannot drift apart.
    """

    NAME = "psd"
    SECTION_KEY = "psd"

    TIME_AXIS = False
    UNIFIED_HOVER = False
    RESAMPLED = False

    class Config:
        """One entry of the ``psd`` section, keyed by the plot's name."""

        # Plural where a spectrogram has a single SIGNAL: PSDs share a subplot, so one
        # entry overlays several. Freq/db range are shared axis properties of the whole
        # subplot, so they stay here; window_s/overlap/label are per-trace (see Entry)
        # since two traces sharing one channel need their own processing/legend.
        SIGNALS = "signals"
        FREQ_RANGE = "freq_range"  # [min_hz, max_hz], required — no workable global default
        DB_RANGE = "db_range"  # [min_db, max_db], optional — y-axis range; autoscales when unset

        # --- One item of SIGNALS; a plain string is shorthand for {SIGNAL: <str>} ---
        class Entry:
            SIGNAL = "signal"
            WINDOW_S = "window_s"  # optional override; derived from freq_min by default
            OVERLAP = "overlap"  # optional override; fixed at 50% by default
            LABEL = "label"  # optional trace label; tells apart 2 entries sharing a signal
            COLOR = "color"  # optional override; defaults to the source signal's own color
            LINE_DASH = "line_dash"  # optional override; defaults to the source signal's own

            KNOWN_KEYS = frozenset({SIGNAL, WINDOW_S, OVERLAP, LABEL, COLOR, LINE_DASH})

    KNOWN_KEYS = frozenset({Config.SIGNALS, Config.FREQ_RANGE, Config.DB_RANGE})

    SHEET_NAME = "psds"
    SHEET_REQUIRED_COLUMNS = frozenset({"datasource", "groups", "signal", "freq_min", "freq_max"})

    @classmethod
    def validate_entry(cls, entry: Any, path: str) -> list[ValidationIssue]:
        if not isinstance(entry, dict):
            return [
                ValidationIssue(
                    severity="error",
                    path=path,
                    message=f"Must be a dict of options, got {type(entry).__name__}",
                )
            ]
        issues: list[ValidationIssue] = []
        unknown = set(entry) - cls.KNOWN_KEYS
        if unknown:
            issues.append(ValidationIssue.unknown_keys(path, unknown, cls.KNOWN_KEYS))

        names = entry.get(cls.Config.SIGNALS)
        if not (isinstance(names, list) and names):
            issues.append(
                ValidationIssue(
                    severity="error",
                    path=f"{path}.signals",
                    message=f"Must be a required non-empty list of signal names, got {names!r}",
                )
            )
        else:
            issues.extend(cls._validate_signal_entries(names, path))

        issues.extend(check_freq_range(entry.get(cls.Config.FREQ_RANGE), path))
        return issues

    @classmethod
    def _validate_signal_entries(cls, names: list, path: str) -> list[ValidationIssue]:
        """Check each ``signals`` item: a plain ref string, or an Entry dict."""
        entry_config = cls.Config.Entry
        issues: list[ValidationIssue] = []
        for item_idx, item in enumerate(names):
            if isinstance(item, str):
                continue
            item_path = f"{path}.signals[{item_idx}]"
            if not isinstance(item, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        path=item_path,
                        message=f"Must be a signal name string or a dict, got {item!r}",
                    )
                )
                continue
            if not isinstance(item.get(entry_config.SIGNAL), str) or not item.get(
                entry_config.SIGNAL
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        path=item_path,
                        message="Missing required key 'signal'",
                    )
                )
            unknown_item = set(item) - entry_config.KNOWN_KEYS
            if unknown_item:
                issues.append(
                    ValidationIssue.unknown_keys(item_path, unknown_item, entry_config.KNOWN_KEYS)
                )
        return issues

    @classmethod
    def map_refs(cls, config: Any, map_ref: Callable[[str], str]) -> Any:
        key = cls.Config.SIGNALS
        entry_key = cls.Config.Entry.SIGNAL
        if not isinstance(config, dict) or not isinstance(config.get(key), (list, tuple)):
            return config
        mapped = []
        for entry in config[key]:
            if not isinstance(entry, dict):
                mapped.append(map_ref(entry))
            elif entry_key in entry:
                mapped.append({**entry, entry_key: map_ref(entry[entry_key])})
            else:
                mapped.append(dict(entry))
        return {**config, key: mapped}

    @classmethod
    def read_sheet(cls, rows: Any, cells: Any) -> dict[str, dict[str, Any]]:
        """
        Read the psds sheet in two phases, mirroring the signals sheet's group resolution.

        A group is denormalized across rows, so every row's contribution is accumulated
        first and each group resolved once -- that way a freq/db mismatch between rows can
        be reported instead of one row silently winning.
        """
        membership = cls._accumulate_rows(rows, cells)
        by_datasource: dict[str, dict[str, Any]] = {}
        for (datasource, group_name), contributions in membership.items():
            options = cls._resolve_group(datasource, group_name, contributions)
            if options is not None:
                by_datasource.setdefault(datasource, {})[group_name] = options
        return by_datasource

    @classmethod
    def _accumulate_rows(cls, rows: Any, cells: Any) -> dict[tuple[str, str], list[dict]]:
        entry_config = cls.Config.Entry
        membership: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row_idx, row in rows.iterrows():
            try:
                datasource = cells.text(row, "datasource")
                signal = cells.text(row, "signal")
                groups_list = cells.parse_groups(row.get("groups", ""))

                if cells.is_empty(datasource) or cells.is_empty(signal) or not groups_list:
                    continue

                db_range, db_half_written = cells.pair(row, "db_min", "db_max")
                contribution: dict[str, Any] = {
                    "row_idx": row_idx,
                    entry_config.SIGNAL: signal,
                    "freq_range": cells.pair(row, "freq_min", "freq_max")[0],
                    "db_range": db_range,
                    "db_half_written": db_half_written,
                }
                window_s = cells.to_float(row.get("window_s", ""))
                if window_s is not None:
                    contribution[entry_config.WINDOW_S] = window_s
                overlap = cells.to_float(row.get("overlap", ""))
                if overlap is not None:
                    contribution[entry_config.OVERLAP] = overlap
                label = cells.text(row, "label")
                if label:
                    contribution[entry_config.LABEL] = label
                color = cells.text(row, "color")
                if color:
                    contribution[entry_config.COLOR] = color
                line_dash = cells.text(row, "line_dash")
                if line_dash:
                    contribution[entry_config.LINE_DASH] = line_dash

                for group_name in groups_list:
                    membership.setdefault((datasource, group_name), []).append(contribution)
            except Exception:
                logger.warning(
                    "Skipping psds row %s due to unexpected error.", row_idx, exc_info=True
                )
        return membership

    @classmethod
    def _resolve_group(
        cls, datasource: str, group_name: str, contributions: list[dict]
    ) -> dict[str, Any] | None:
        entry_config = cls.Config.Entry
        freq_range = None
        db_range = None
        entries: list[Any] = []

        for contribution in contributions:
            row_idx = contribution["row_idx"]

            freq_range = _resolve_shared_range(
                freq_range,
                contribution["freq_range"],
                label="freq_range",
                row_idx=row_idx,
                group_name=group_name,
                datasource=datasource,
            )

            if contribution["db_range"] is not None:
                db_range = _resolve_shared_range(
                    db_range,
                    contribution["db_range"],
                    label="db_range",
                    row_idx=row_idx,
                    group_name=group_name,
                    datasource=datasource,
                )
            elif contribution["db_half_written"]:
                logger.warning(
                    "Skipping db_range for %s row %s: db_min/db_max must both be set.",
                    cls.SHEET_NAME,
                    row_idx,
                )

            # Shorthand: a plain ref string when the row set no per-entry override.
            entry = {
                key: contribution[key]
                for key in (
                    entry_config.SIGNAL,
                    entry_config.WINDOW_S,
                    entry_config.OVERLAP,
                    entry_config.LABEL,
                    entry_config.COLOR,
                    entry_config.LINE_DASH,
                )
                if key in contribution
            }
            entries.append(entry[entry_config.SIGNAL] if len(entry) == 1 else entry)

        if freq_range is None:
            logger.warning(
                "Skipping PSD group %r (datasource %r): freq_min/freq_max must be set on "
                "at least one row.",
                group_name,
                datasource,
            )
            return None

        options: dict[str, Any] = {
            cls.Config.SIGNALS: entries,
            cls.Config.FREQ_RANGE: freq_range,
        }
        if db_range is not None:
            options[cls.Config.DB_RANGE] = db_range
        return options
