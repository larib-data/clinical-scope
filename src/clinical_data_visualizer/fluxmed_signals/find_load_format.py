import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.fluxmed_signals.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


def _is_time_header(line: str) -> bool:
    """Return True if *line* starts with any multilingual variant of 'Time'."""
    return any(
        line.casefold().startswith(p.casefold()) for p in options_naming.TIME_HEADER_PREFIXES
    )


class FluxmedSignalsDataSource(DataSourceBase):
    """Fluxmed Signals datasource processor."""

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

            # Read raw file
            with Path.open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f]

            # Find header row (accept multilingual "Time" variants, e.g. "Tiempo", "Tempo")
            header_idx = None
            for i, line in enumerate(lines):
                if _is_time_header(line):
                    header_idx = i
                    break

            if header_idx is None:
                known = ", ".join(options_naming.TIME_HEADER_PREFIXES)
                msg = f"No time header found (tried: {known})"
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
            msg = (
                f"file_path extension was neither '.txt', '.csv' or '.parquet'. "
                f"Input: '{file_path}'"
            )
            raise NotImplementedError(msg)

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    return FluxmedSignalsDataSource.main(patient_options, database_options_specific)
