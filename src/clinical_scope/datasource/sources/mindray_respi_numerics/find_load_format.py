import logging
from pathlib import Path

import pandas as pd

import clinical_scope.constants as cst
import clinical_scope.datasource.sources.mindray_respi_numerics.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.time_axis import deduplicate_then_sort_index

logger = logging.getLogger(__name__)


class MindRayRespiNumericsDataSource(DataSourceBase):
    """MindRay Respi Numerics datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path) -> pd.DataFrame:
        """
        Load a MindRay Respi Numerics export, one measurement per row.

        Columns are one per "{measurement_label}-{measurement_unit}" pair, indexed by
        "event_timestamp".
        """
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path, delimiter=",", decimal=".")
        else:
            msg = f"Unsupported extension: '{file_path}'"
            raise NotImplementedError(msg)

        if df.empty:
            logger.warning("[%s] Empty data file: %s", cls.DATASOURCE_NAME, file_path)
            return pd.DataFrame(index=pd.DatetimeIndex([], name=cst.DATETIME_INDEX_NAME))

        df["full_label_name"] = df["measurement_label"] + "-" + df["measurement_unit"]
        df = df.drop(columns=["measurement_label", "measurement_unit"])

        df_pivoted = df.pivot_table(
            index="event_timestamp",
            columns="full_label_name",
            values="measurement_value",
            aggfunc="first",
        )

        df_pivoted.columns = df_pivoted.columns.get_level_values(0)

        df_pivoted.index = pd.to_datetime(df_pivoted.index)
        return deduplicate_then_sort_index(df_pivoted)
