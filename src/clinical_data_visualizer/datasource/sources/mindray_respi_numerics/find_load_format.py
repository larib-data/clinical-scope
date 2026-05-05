import logging
from pathlib import Path
from typing import Any

import pandas as pd

import clinical_data_visualizer.datasource.sources.mindray_respi_numerics.options as options_naming
from clinical_data_visualizer.datasource.base import DataSourceBase
from clinical_data_visualizer.datasource.formatting.timezone import apply_timezone_to_dataframe
from clinical_data_visualizer.datasource.timing import time_it

logger = logging.getLogger(__name__)


class MindRayRespiNumericsDataSource(DataSourceBase):
    """MindRay Respi Numerics datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs: Any) -> pd.DataFrame:
        """
        Load and parse MindRay Respi Numerics data.

        The data has one row per measurement (not per timestamp), so we need to:
        1. Create a composite column "full_label_name" = f"{measurement_label}-{measurement_unit}"
        2. Pivot the data to have one column per unique measurement
        3. Set "event_timestamp" as the index
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

        # Create composite column for label+unit
        df["full_label_name"] = df["measurement_label"] + "-" + df["measurement_unit"]

        # Remove legacy columns
        df = df.drop(columns=["measurement_label", "measurement_unit"])

        # Pivot the data: one column per measurement type
        df_pivoted = df.pivot_table(
            index="event_timestamp",
            columns="full_label_name",
            values="measurement_value",
            aggfunc="first",
        )

        # Flatten multi-index columns - keep the full label name
        df_pivoted.columns = df_pivoted.columns.get_level_values(0)

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
