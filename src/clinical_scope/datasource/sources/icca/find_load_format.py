import logging
from pathlib import Path
from typing import Any

import pandas as pd

import clinical_scope.constants as cst
import clinical_scope.datasource.sources.icca.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_utils import deduplicate_then_sort_index, sniff_csv_delimiter

logger = logging.getLogger(__name__)


class IccaDataSource(DataSourceBase):
    """ICCA (Philips IntelliSpace Critical Care and Anesthesia) datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    def _read_export(cls, file_path: Path) -> pd.DataFrame:
        """
        Read an ICCA export into its raw long-format frame.

        Extensions ICCA can produce but this loader cannot parse yet raise
        ``NotImplementedError``; anything ICCA never produces raises ``ValueError``, so a
        misfiled neighbour is not mistaken for a missing feature.
        """
        suffix = file_path.suffix.lower()

        if suffix == ".csv":
            return pd.read_csv(file_path, delimiter=sniff_csv_delimiter(file_path), decimal=".")

        if suffix in options_naming.FILE_EXTENSIONS_PLANNED:
            msg = f"ICCA '{suffix}' exports are not supported yet: '{file_path}'"
            raise NotImplementedError(msg)

        msg = f"'{suffix}' is not an ICCA export format (ICCA exports CSV): '{file_path}'"
        raise ValueError(msg)

    @classmethod
    def _warn_dropped_non_numeric(cls, df: pd.DataFrame) -> None:
        """
        Report attributeIds that hold no numeric value and so vanish in the pivot.

        Only ``valueNumber`` is pivoted, so a string- or datetime-valued attributeId becomes
        an all-NaN column that ``pivot_table`` then drops entirely — leaving no trace in the
        loaded frame for ``inspect()`` to report.
        """
        numeric_per_attribute = df.groupby(options_naming.COLUMN_ATTRIBUTE_ID)[
            options_naming.COLUMN_VALUE
        ].count()
        dropped = numeric_per_attribute[numeric_per_attribute == 0]
        if dropped.empty:
            return

        described = []
        for attribute_id in dropped.index:
            rows = df[df[options_naming.COLUMN_ATTRIBUTE_ID] == attribute_id]
            carriers = [
                column
                for column in options_naming.COLUMNS_VALUE_NON_NUMERIC
                if column in rows.columns and rows[column].notna().any()
            ]
            held_in = ", ".join(carriers) if carriers else "no value column"
            described.append(f"{attribute_id} ({len(rows)} rows, values in {held_in})")

        logger.warning(
            "[%s] %d attributeId(s) hold no %s and are absent from the loaded signals: %s",
            cls.DATASOURCE_NAME,
            len(dropped),
            options_naming.COLUMN_VALUE,
            ", ".join(described),
        )

    @classmethod
    def _warn_collapsed_duplicates(cls, df: pd.DataFrame) -> None:
        """
        Report the measurements the pivot is about to discard.

        Nothing in the export separates the rows of a colliding
        ``(utcmeasurementTime, attributeId)`` pair — same instant, same signal, different
        value — so keeping the first is arbitrary. Counting them is the only signal a user
        gets that the loaded frame holds fewer measurements than the file.
        """
        collapsed = df.duplicated(
            subset=[options_naming.COLUMN_TIME, options_naming.COLUMN_ATTRIBUTE_ID]
        )
        if not collapsed.any():
            return

        per_attribute = df[collapsed].groupby(options_naming.COLUMN_ATTRIBUTE_ID).size()
        logger.warning(
            "[%s] %d of %d measurements share a (%s, %s) pair; only the first of each is kept. "
            "Dropped per attributeId: %s",
            cls.DATASOURCE_NAME,
            int(collapsed.sum()),
            len(df),
            options_naming.COLUMN_TIME,
            options_naming.COLUMN_ATTRIBUTE_ID,
            ", ".join(f"{attribute_id}: {count}" for attribute_id, count in per_attribute.items()),
        )

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs: Any) -> pd.DataFrame:  # noqa: ARG003
        """
        Load and parse an ICCA high-density anesthesia export.

        The export is long-format — one row per measurement — so it is pivoted to one column
        per ``attributeId`` (the time-series identifier), keyed on ``utcmeasurementTime``.
        The index stays tz-naive: ``_format`` localizes it, which keeps the cached frame
        honest about the timezone a later run may override.
        """
        df = cls._read_export(file_path)

        if df.empty:
            logger.warning("[%s] Empty data file: %s", cls.DATASOURCE_NAME, file_path)
            return pd.DataFrame(index=pd.DatetimeIndex([]))

        cls._warn_dropped_non_numeric(df)
        cls._warn_collapsed_duplicates(df)

        df_pivoted = df.pivot_table(
            index=options_naming.COLUMN_TIME,
            columns=options_naming.COLUMN_ATTRIBUTE_ID,
            values=options_naming.COLUMN_VALUE,
            aggfunc="first",
        )

        # attributeId is an integer; use string column names so they round-trip
        # through parquet and resolve as raw signal names in database_options.
        df_pivoted.columns = [str(c) for c in df_pivoted.columns]

        df_pivoted.index = pd.to_datetime(df_pivoted.index)
        df_pivoted = deduplicate_then_sort_index(df_pivoted)

        if path_output is not None:
            cls._save_dataframe(df_pivoted, path_output)
        return df_pivoted

    @classmethod
    @time_it
    def _format(
        cls,
        df: pd.DataFrame,
        patient_options: dict,
        database_options_specific: dict,
    ) -> pd.DataFrame:
        """
        Warn about a non-UTC timezone override, then format as usual.

        ``utcmeasurementTime`` is UTC by construction, so an override does not correct the
        stamps — it reinterprets them as wall-clock time in another zone, shifting the whole
        recording.
        """
        override = database_options_specific.get(
            cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
        ).get(options_naming.DatabaseOptionsAdditionalInformations.TIMEZONE)
        if override is not None and override != options_naming.DATA_SOURCE_DEFAULT_TIMEZONE:
            logger.warning(
                "[%s] Timezone override %r applied to %s, which the export records in UTC: "
                "timestamps will shift by that zone's offset.",
                cls.DATASOURCE_NAME,
                override,
                options_naming.COLUMN_TIME,
            )
        return super()._format(df, patient_options, database_options_specific)
