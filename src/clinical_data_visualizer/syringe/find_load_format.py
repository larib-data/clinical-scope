import csv
import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.syringe.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class SyringeDataSource(DataSourceBase):
    """Syringe datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            # Try to detect delimiter automatically
            with Path.open(file_path, "r", newline="") as f:
                sample = f.read(2048)
                dialect = csv.Sniffer().sniff(sample)
                sep = dialect.delimiter

            df = pd.read_csv(file_path, sep=sep)

            # If the index is integer dtype, we assume it means it's basic dtype
            if pd.api.types.is_integer_dtype(df.index):
                time_candidates = [
                    col
                    for col in df.columns
                    if col.lower().replace("'", "").replace('"', "")
                    in options_naming.CANDIDATE_LIST_DATETIME_COLUMN
                ]
                if time_candidates:
                    time_col = time_candidates[0]
                    try:
                        # Try parse as datetime
                        df[time_col] = pd.to_datetime(df[time_col], errors="raise")
                        df = df.set_index(time_col)
                    except (ValueError, TypeError):
                        # Fallback: treat as float (seconds)
                        df = df.set_index(time_col)
                else:
                    msg = (
                        "We need a column to play the role of the datetime index column<br>"
                        "Maybe we could do something with a given day and if a "
                        "relative column time exists, but not implemented."
                    )
                    raise NotImplementedError(msg)

            cols_to_convert = list(df.columns)
            df[cols_to_convert] = df[cols_to_convert].apply(pd.to_numeric, errors="coerce")
        else:
            msg = f"Invalid file format: {file_path.name}. Only .csv or .parquet supported."
            raise NotImplementedError(msg)

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    return SyringeDataSource.main(patient_options, database_options_specific)
