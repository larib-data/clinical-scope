import logging
from pathlib import Path
from typing import Any

import pandas as pd

import clinical_scope.datasource.sources.icca.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.formatting.timezone import apply_timezone_to_dataframe
from clinical_scope.datasource.timing import time_it

logger = logging.getLogger(__name__)

# Raw column names in the ICCA PtHighDensityAnesthesiaData export.
COLUMN_ATTRIBUTE_ID = "attributeId"
COLUMN_TIME = "utcmeasurementTime"
COLUMN_VALUE = "valueNumber"


class IccaDataSource(DataSourceBase):
    """ICCA (Philips IntelliSpace Critical Care and Anesthesia) datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs: Any) -> pd.DataFrame:
        """
        Load and parse an ICCA high-density anesthesia export.

        The data is long-format — one row per measurement — so we:
        1. Pivot to one column per ``attributeId`` (the time-series identifier),
           keyed on ``utcmeasurementTime`` with ``valueNumber`` as the value.
        2. Use ``pivot_table(aggfunc="first")`` because the same ``attributeId`` can
           appear more than once at the same timestamp.
        3. Set a sorted, deduplicated, UTC-localized DatetimeIndex.
        """
        database_options_specific = kwargs.get("database_options_specific", {})

        # Load the data
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path, delimiter=",", decimal=".")
        else:
            msg = f"Unsupported extension: '{file_path}'"
            raise NotImplementedError(msg)

        if df.empty:
            logger.warning("[%s] Empty data file: %s", cls.DATASOURCE_NAME, file_path)
            return pd.DataFrame(
                index=pd.DatetimeIndex([], tz=options_naming.DATA_SOURCE_DEFAULT_TIMEZONE)
            )

        # Pivot the data: one column per attributeId (the time-series identifier)
        df_pivoted = df.pivot_table(
            index=COLUMN_TIME,
            columns=COLUMN_ATTRIBUTE_ID,
            values=COLUMN_VALUE,
            aggfunc="first",
        )

        # attributeId is an integer; use string column names so they round-trip
        # through parquet and resolve as raw signal names in database_options.
        df_pivoted.columns = [str(c) for c in df_pivoted.columns]

        # Convert index to datetime
        df_pivoted.index = pd.to_datetime(df_pivoted.index)

        # Sort by timestamp
        df_pivoted = df_pivoted.sort_index()

        # Remove duplicate timestamps (keep first)
        df_pivoted = df_pivoted[~df_pivoted.index.duplicated(keep="first")]

        # Apply timezone if needed
        df_pivoted = apply_timezone_to_dataframe(
            df_pivoted,
            database_options_specific,
            options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
            options_naming,
        )

        if path_output is not None:
            cls._save_dataframe(df_pivoted, path_output)
        return df_pivoted
