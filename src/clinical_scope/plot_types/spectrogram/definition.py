"""Leaf half of the ``spectrogram`` plot type: one signal's spectrum over time."""

import logging
from collections.abc import Callable
from typing import Any

from clinical_scope.plot_types.base import PlotTypeDefinition, check_freq_range
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)


class SpectrogramDefinition(PlotTypeDefinition):
    """
    A spectrogram is a heatmap of one signal's power spectrum against time.

    Time on x like a time-series, but a colour scale rather than a line: it carries a
    colorbar, and a unified hover panel is meaningless when each pixel is its own cell.

    The JSON keys and the spreadsheet columns below are one definition in two spellings -- the
    sheet requires ``freq_min``/``freq_max`` precisely because ``FREQ_RANGE`` is required --
    so they are declared together, where they cannot drift apart.
    """

    NAME = "spectrogram"
    SECTION_KEY = "spectrogram"

    UNIFIED_HOVER = False
    RESAMPLED = False
    HAS_COLORBAR = True

    class Config:
        """One entry of the ``spectrogram`` section, keyed by the plot's name."""

        SIGNAL = "signal"  # one raw name — no arithmetic, no pairs, no wildcards
        FREQ_RANGE = "freq_range"  # [min_hz, max_hz], required — no workable global default
        DB_RANGE = "db_range"  # [min_db, max_db], optional — falls back to a user option
        WINDOW_S = "window_s"  # optional override; derived from freq_min by default
        OVERLAP = "overlap"  # optional override; fixed at 50% by default

    KNOWN_KEYS = frozenset(
        {Config.SIGNAL, Config.FREQ_RANGE, Config.DB_RANGE, Config.WINDOW_S, Config.OVERLAP}
    )

    SHEET_NAME = "spectrograms"
    SHEET_REQUIRED_COLUMNS = frozenset(
        {"datasource", "spectrogram_name", "signal", "freq_min", "freq_max"}
    )

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
        if cls.Config.SIGNAL not in entry:
            issues.append(
                ValidationIssue(
                    severity="error", path=path, message="Missing required key 'signal'"
                )
            )
        issues.extend(check_freq_range(entry.get(cls.Config.FREQ_RANGE), path))
        return issues

    @classmethod
    def map_refs(cls, config: Any, map_ref: Callable[[str], str]) -> Any:
        key = cls.Config.SIGNAL
        if not isinstance(config, dict):
            return config
        if key not in config:
            return dict(config)
        return {**config, key: map_ref(config[key])}

    @classmethod
    def read_sheet(cls, rows: Any, cells: Any) -> dict[str, dict[str, Any]]:
        by_datasource: dict[str, dict[str, Any]] = {}
        for row_idx, row in rows.iterrows():
            try:
                datasource = cells.text(row, "datasource")
                spectrogram_name = cells.text(row, "spectrogram_name")
                signal = cells.text(row, "signal")
                freq_range, _ = cells.pair(row, "freq_min", "freq_max")

                if any(cells.is_empty(value) for value in (datasource, spectrogram_name, signal)):
                    continue
                if freq_range is None:
                    logger.warning(
                        "Skipping %s row %s: freq_min/freq_max must both be set.",
                        cls.SHEET_NAME,
                        row_idx,
                    )
                    continue

                options: dict[str, Any] = {
                    cls.Config.SIGNAL: signal,
                    cls.Config.FREQ_RANGE: freq_range,
                }

                db_range, db_half_written = cells.pair(row, "db_min", "db_max")
                if db_range is not None:
                    options[cls.Config.DB_RANGE] = db_range
                elif db_half_written:
                    logger.warning(
                        "Skipping db_range for %s row %s: db_min/db_max must both be set.",
                        cls.SHEET_NAME,
                        row_idx,
                    )

                window_s = cells.to_float(row.get("window_s", ""))
                if window_s is not None:
                    options[cls.Config.WINDOW_S] = window_s
                overlap = cells.to_float(row.get("overlap", ""))
                if overlap is not None:
                    options[cls.Config.OVERLAP] = overlap

                by_datasource.setdefault(datasource, {})[spectrogram_name] = options
            except Exception:
                logger.warning(
                    "Skipping spectrograms row %s due to unexpected error.",
                    row_idx,
                    exc_info=True,
                )
        return by_datasource
