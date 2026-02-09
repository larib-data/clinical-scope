import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.fluxmed_signals.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class FluxmedSignalsDataSource(DataSourceBase):
    """Fluxmed Signals datasource processor."""

    DATASOURCE_NAME = "fluxmed_signals"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming

    @classmethod
    def _find(cls, folder_path: Path) -> Path | None:
        return helper.find_file(
            folder_path,
            options_naming.KEYWORD_FILE,
            "paramsignals",
            [".txt", ".csv", ".parquet"],
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path, **kwargs) -> pd.DataFrame:
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

            # Read raw file
            with Path.open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f]

            # Find header row
            header_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Time"):
                    header_idx = i
                    break

            if header_idx is None:
                msg = "No 'Time' header found"
                raise RuntimeError(msg)

            units_idx = header_idx + 1
            data_start_idx = units_idx + 6  # skip 6 lines after units

            # Build column names
            col_names = re.split(r"\s+", lines[header_idx])
            col_units = re.split(r"\s+", lines[units_idx])
            columns = [f"{name}({unit})" for name, unit in zip(col_names, col_units, strict=False)]

            # Extract numeric rows only
            numeric_lines = [
                line for line in lines[data_start_idx:] if re.match(r"^[0-9]+[.,][0-9]", line)
            ]

            if not numeric_lines:
                msg = "No numeric signal rows found after skipping 6 lines"
                raise RuntimeError(msg)

            # Load into DataFrame
            df = pd.read_csv(
                pd.io.common.StringIO("\n".join(numeric_lines)),
                sep=r"\s+",
                header=None,
                names=columns,
                decimal=",",
                engine="python",
            )

            # Build datetime index
            time_col = columns[0]
            df = df.apply(pd.to_numeric, errors="coerce")
            df.index = pd.to_datetime(
                [start_time + timedelta(seconds=float(t)) for t in df[time_col]]
            )
            df.index.name = "datetime_index"
        else:
            msg = f"file_path extension was neither '.txt', '.csv' or '.parquet'. Input: '{file_path}'"
            raise NotImplementedError(
                msg
            )

        df = df[~df.index.duplicated(keep="first")]
        cls._save_dataframe(df, path_output)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None):
    return FluxmedSignalsDataSource.main(patient_options, database_options_specific)
