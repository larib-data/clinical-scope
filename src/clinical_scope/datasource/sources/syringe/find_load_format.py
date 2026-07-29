import csv
import logging
from pathlib import Path

import pandas as pd

import clinical_scope.datasource.sources.syringe.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_utils import (
    deduplicate_then_sort_index,
    load_parquet_with_datetime_index,
    set_datetime_index,
)

logger = logging.getLogger(__name__)


class SyringeDataSource(DataSourceBase):
    """Syringe datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = load_parquet_with_datetime_index(file_path)
        elif file_path.suffix.lower() == ".csv":
            # Try to detect delimiter automatically
            with Path.open(file_path, "r", newline="") as f:
                sample = f.read(2048)
                dialect = csv.Sniffer().sniff(sample)
                sep = dialect.delimiter

            df = pd.read_csv(file_path, sep=sep)
            df = set_datetime_index(df)

            cols_to_convert = list(df.columns)
            df[cols_to_convert] = df[cols_to_convert].apply(pd.to_numeric, errors="coerce")
        else:
            msg = f"Invalid file format: {file_path.name}. Only .csv or .parquet supported."
            raise NotImplementedError(msg)

        df = deduplicate_then_sort_index(df)
        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df
