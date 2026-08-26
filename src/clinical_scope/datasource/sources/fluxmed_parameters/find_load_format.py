import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_scope.datasource.sources.fluxmed_parameters.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.time_axis import set_datetime_index

logger = logging.getLogger(__name__)


def _is_time_header(line: str) -> bool:
    """Return True if *line* starts with any multilingual variant of 'Time'."""
    return any(
        line.casefold().startswith(prefix.casefold())
        for prefix in options_naming.TIME_HEADER_PREFIXES
    )


class FluxmedParametersDataSource(DataSourceBase):
    """Fluxmed Parameters datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path) -> pd.DataFrame:
        if file_path.suffix.lower() == ".parquet":
            df = set_datetime_index(pd.read_parquet(file_path))
        elif file_path.suffix.lower() in [".txt", ".csv"]:
            filename = file_path.name
            match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
            if not match:
                raise ValueError("Cannot extract timestamp from filename: " + filename)

            start_time_str = match.group(1)
            # Naive: _format localizes from the configured timezone (ADR-0010).
            start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S")  # noqa: DTZ007

            with Path.open(file_path, "r", encoding="utf-8") as file:
                lines = [line.strip() for line in file.readlines()]

            # Find the column names row(accept multilingual "Time" variants, e.g. "Tiempo", "Tempo")
            header_line_index = None
            for line_index, line in enumerate(lines):
                if _is_time_header(line):
                    header_line_index = line_index
                    break

            if header_line_index is None:
                known = ", ".join(options_naming.TIME_HEADER_PREFIXES)
                msg = f"No time header found (tried: {known})"
                raise RuntimeError(msg)

            column_names = lines[header_line_index].split()
            column_units = lines[header_line_index + 1].split()
            columns = [
                f"{name}({unit})" for name, unit in zip(column_names, column_units, strict=False)
            ]

            def make_unique(columns: list[str]) -> list[str]:
                seen = {}
                result = []
                for column_name in columns:
                    if column_name not in seen:
                        seen[column_name] = 1
                        result.append(column_name)
                    else:
                        deduped_name = f"{column_name}_{seen[column_name]}"
                        seen[column_name] += 1
                        result.append(deduped_name)
                return result

            columns = make_unique(columns)

            # Read the data starting from the row after units
            data_start_index = header_line_index + 2
            df = pd.read_csv(
                file_path,
                sep=r"\s+",
                header=None,
                names=columns,
                skiprows=data_start_index,
                decimal=",",
                engine="python",
                on_bad_lines="warn",
            )

            df.columns = df.columns.str.strip()
            df = df.apply(pd.to_numeric, errors="coerce")

            # Compute datetime index from the first column (the time-offset column)
            time_column = columns[0]
            timestamps = [
                start_time + timedelta(seconds=offset_seconds) for offset_seconds in df[time_column]
            ]
            df.index = pd.to_datetime(timestamps)
            df.index.name = "datetime_index"
        else:
            msg = (
                f"file_path extension was neither '.txt', '.csv' or '.parquet'. "
                f"Input: '{file_path}'"
            )
            raise NotImplementedError(msg)

        return df[~df.index.duplicated(keep="first")]
