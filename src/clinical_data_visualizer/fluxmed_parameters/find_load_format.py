import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.fluxmed_parameters.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)

# Safety check
if options_naming.KEYWORD_FILE in options_naming.FILE_NAME_DATAFRAME_LOADED:
    raise ValueError(
        f"'KEYWORD_FILE'({options_naming.KEYWORD_FILE}) is in "
        f"'FILE_NAME_DATAFRAME_LOADED'({options_naming.FILE_NAME_DATAFRAME_LOADED}). "
        "This dangerous since we might override the raw data, or read the wrong one"
    )


class FluxmedParametersDataSource(DataSourceBase):
    """Fluxmed Parameters datasource processor."""

    DATASOURCE_NAME = "fluxmed_parameters"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming
    SOURCE_OPTIONS = options_naming.source_options

    @classmethod
    def _find_folder(cls, folder_path: Path) -> Path | None:
        return helper.find_folder(folder_path, options_naming.KEYWORD_FOLDER, "FLUXMED folder")

    @classmethod
    def _find(cls, folder_path: Path) -> Path | None:
        return helper.find_file(
            folder_path,
            options_naming.KEYWORD_FILE,
            "parameters file",
            [".txt", ".csv", ".parquet"],
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path, **kwargs) -> pd.DataFrame:
        time_col_name = "Time(sec)"

        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() in [".txt", ".csv"]:
            # Extract timestamp from filename
            filename = file_path.name
            match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
            if not match:
                raise ValueError("Cannot extract timestamp from filename: " + filename)

            start_time_str = match.group(1)
            start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S")

            # Read the first lines to get headers and units
            with Path.open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()]

            # Find the column names row
            col_idx = None
            for i, line in enumerate(lines):
                if line.startswith(time_col_name.split("(")[0]):
                    col_idx = i
                    break

            # Extract column names and units
            col_names = lines[col_idx].split()
            col_units = lines[col_idx + 1].split()
            columns = [f"{n}({u})" for n, u in zip(col_names, col_units, strict=False)]

            # Make columns unique if duplicates exist
            def make_unique(columns):
                seen = {}
                result = []
                for col in columns:
                    if col not in seen:
                        seen[col] = 1
                        result.append(col)
                    else:
                        new_col = f"{col}_{seen[col]}"
                        seen[col] += 1
                        result.append(new_col)
                return result

            columns = make_unique(columns)

            # Read the data starting from the row after units
            data_start_idx = col_idx + 2
            df = pd.read_csv(
                file_path,
                sep=r"\s+",
                header=None,
                names=columns,
                skiprows=data_start_idx,
                decimal=",",
                engine="python",
                on_bad_lines="warn",
            )

            df.columns = df.columns.str.strip()
            df = df.apply(pd.to_numeric, errors="coerce")

            # Compute datetime index
            timestamps = [start_time + timedelta(seconds=s) for s in df[time_col_name]]
            df.index = pd.to_datetime(timestamps)
            df.index.name = "datetime_index"
        else:
            raise NotImplementedError(
                f"file_path extension was neither '.txt', '.csv' or '.parquet'. Input: '{file_path}'"
            )

        df = df[~df.index.duplicated(keep="first")]
        cls._save_dataframe(df, path_output)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None):
    return FluxmedParametersDataSource.main(patient_options, database_options_specific)
