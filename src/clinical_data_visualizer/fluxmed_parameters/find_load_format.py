import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.fluxmed_parameters.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


def _is_time_header(line: str) -> bool:
    """Return True if *line* starts with any multilingual variant of 'Time'."""
    return any(
        line.casefold().startswith(p.casefold()) for p in options_naming.TIME_HEADER_PREFIXES
    )


class FluxmedParametersDataSource(DataSourceBase):
    """Fluxmed Parameters datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() in [".txt", ".csv"]:
            # Extract timestamp from filename
            filename = file_path.name
            match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
            if not match:
                raise ValueError("Cannot extract timestamp from filename: " + filename)

            start_time_str = match.group(1)
            start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S").replace(tzinfo=UTC)

            # Read the first lines to get headers and units
            with Path.open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()]

            # Find the column names row(accept multilingual "Time" variants, e.g. "Tiempo", "Tempo")
            col_idx = None
            for i, line in enumerate(lines):
                if _is_time_header(line):
                    col_idx = i
                    break

            if col_idx is None:
                known = ", ".join(options_naming.TIME_HEADER_PREFIXES)
                msg = f"No time header found (tried: {known})"
                raise RuntimeError(msg)

            # Extract column names and units
            col_names = lines[col_idx].split()
            col_units = lines[col_idx + 1].split()
            columns = [f"{n}({u})" for n, u in zip(col_names, col_units, strict=False)]

            # Make columns unique if duplicates exist
            def make_unique(columns: list[str]) -> list[str]:
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

            # Compute datetime index from the first column (the time-offset column)
            time_col = columns[0]
            timestamps = [start_time + timedelta(seconds=s) for s in df[time_col]]
            df.index = pd.to_datetime(timestamps)
            df.index.name = "datetime_index"
        else:
            msg = (
                f"file_path extension was neither '.txt', '.csv' or '.parquet'. "
                f"Input: '{file_path}'"
            )
            raise NotImplementedError(msg)

        df = df[~df.index.duplicated(keep="first")]
        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df
