import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_scope.datasource.sources.fluxmed_signals.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_utils import (
    deduplicate_then_sort_index,
    load_parquet_with_datetime_index,
)

logger = logging.getLogger(__name__)


def _is_time_header(line: str) -> bool:
    """Return True if *line* starts with any multilingual variant of 'Time'."""
    return any(
        line.casefold().startswith(prefix.casefold())
        for prefix in options_naming.TIME_HEADER_PREFIXES
    )


class FluxmedSignalsDataSource(DataSourceBase):
    """Fluxmed Signals datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = load_parquet_with_datetime_index(file_path)
        elif file_path.suffix.lower() in [".txt", ".csv"]:
            filename = file_path.name
            match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
            if not match:
                raise ValueError("Cannot extract timestamp from filename: " + filename)

            start_time_str = match.group(1)
            start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S").replace(tzinfo=UTC)

            with Path.open(file_path, "r", encoding="utf-8") as file:
                lines = [line.strip() for line in file]

            # Find header row (accept multilingual "Time" variants, e.g. "Tiempo", "Tempo")
            header_line_index = None
            for line_index, line in enumerate(lines):
                if _is_time_header(line):
                    header_line_index = line_index
                    break

            if header_line_index is None:
                known = ", ".join(options_naming.TIME_HEADER_PREFIXES)
                msg = f"No time header found (tried: {known})"
                raise RuntimeError(msg)

            units_line_index = header_line_index + 1
            data_start_index = units_line_index + 6  # skip 6 lines after units

            column_names = re.split(r"\s+", lines[header_line_index])
            column_units = re.split(r"\s+", lines[units_line_index])
            columns = [
                f"{name}({unit})" for name, unit in zip(column_names, column_units, strict=False)
            ]

            # Extract numeric rows only
            numeric_lines = [
                line for line in lines[data_start_index:] if re.match(r"^[0-9]+[.,][0-9]", line)
            ]

            if not numeric_lines:
                msg = "No numeric signal rows found after skipping 6 lines"
                raise RuntimeError(msg)

            df = pd.read_csv(
                pd.io.common.StringIO("\n".join(numeric_lines)),
                sep=r"\s+",
                header=None,
                names=columns,
                decimal=",",
                engine="python",
            )

            time_column = columns[0]
            df = df.apply(pd.to_numeric, errors="coerce")
            df.index = pd.to_datetime(
                [
                    start_time + timedelta(seconds=float(offset_seconds))
                    for offset_seconds in df[time_column]
                ]
            )
            df.index.name = "datetime_index"
        else:
            msg = (
                f"file_path extension was neither '.txt', '.csv' or '.parquet'. "
                f"Input: '{file_path}'"
            )
            raise NotImplementedError(msg)

        df = deduplicate_then_sort_index(df)
        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df
