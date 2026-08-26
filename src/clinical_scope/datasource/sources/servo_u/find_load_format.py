import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_scope.datasource.sources.servo_u.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.time_axis import deduplicate_then_sort_index

logger = logging.getLogger(__name__)


def parse_header_info(lines: list[str]) -> dict[str, datetime]:
    """Parse header metadata from Servo U file."""
    header_info = {}
    for line in lines:
        match = re.match(r"%%\s+(.*?):\s+([\d\-:.\s]+)", line)
        if match:
            field = match.group(1).strip()
            value = match.group(2).strip()
            for time_format in ("%Y-%m-%d:%H:%M:%S.%f", "%Y-%m-%d:%H:%M:%S"):
                try:
                    header_info[field] = datetime.strptime(value, time_format)  # noqa: DTZ007
                    break
                except ValueError:
                    continue
    return header_info


def compute_timestamp_index_from_timems(
    time_ms_series: pd.Series,
    start_time: datetime,
) -> pd.DatetimeIndex:
    """Compute tz-naive timestamps from Time(ms) column + log start."""
    timestamps = [start_time + timedelta(milliseconds=ms) for ms in time_ms_series]
    return pd.DatetimeIndex(timestamps, name="datetime_index")


MIN_SEPARATORS_NEEDED = 3
MAPPING_PARTS_EXPECTED = 2


def extract_column_mapping_from_section(
    lines: list[str],
) -> dict[str, str]:
    """Extract mapping from the section between the 2nd and 3rd '%%%%%%...' separator."""
    separator_indices = [
        line_index
        for line_index, line in enumerate(lines)
        if line.strip().startswith("%%%%%%") and set(line.strip()) == {"%"}
    ]
    if len(separator_indices) < MIN_SEPARATORS_NEEDED:
        msg = "File does not have enough separators for mapping section"
        raise ValueError(msg)

    start_index = separator_indices[1] + 1
    end_index = separator_indices[2]

    mapping = {}
    for line in lines[start_index:end_index]:
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("% Phase"):
            continue
        stripped_line = stripped_line.lstrip("%").strip()
        parts = stripped_line.split(":")
        if len(parts) != MAPPING_PARTS_EXPECTED:
            continue
        code_with_unit, measurement = parts
        code_with_unit = code_with_unit.strip()
        measurement = measurement.strip()
        code = code_with_unit.split()[0].strip()
        unit = code_with_unit[code_with_unit.find("(") :].strip()
        mapping[code] = f"{measurement} {unit}"
    return mapping


def parse_file(
    filepath: Path,
    start_time: datetime | None,
    first_file: bool = False,
    rename_map: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, datetime, dict[str, str] | None]:
    """Parse a single Servo U file."""
    with Path.open(filepath, "r", encoding="utf-8") as file:
        lines = file.readlines()

    if first_file:
        header_info = parse_header_info(lines)
        start_time = header_info[options_naming.REFERENCE_TIME_FIELD]
        rename_map = extract_column_mapping_from_section(lines)

    table_header_index = None
    for line_index, line in enumerate(lines):
        if line.strip().startswith("%% Time(ms)"):
            table_header_index = line_index
            break
    if table_header_index is None:
        msg = f"No table header found in {filepath}"
        raise ValueError(msg)

    header_line = lines[table_header_index].replace("%%", "").strip()
    columns = [column_name.strip() for column_name in header_line.split("\t")]

    data_lines = lines[table_header_index + 1 :]
    data_lines = [line for line in data_lines if line.strip() and not line.strip().startswith("%")]

    df = pd.read_csv(
        pd.io.common.StringIO("".join(data_lines)), sep="\t", engine="python", names=columns
    )

    if rename_map:
        df = df.rename(
            columns={
                code: measurement for code, measurement in rename_map.items() if code in df.columns
            }
        )

    df = df.drop(columns=["T(h:m:s.ms)"], errors="ignore")

    ordered_columns = df.columns.tolist()
    if options_naming.COLUMN_RELATIVE_TIME in ordered_columns:
        ordered_columns.remove(options_naming.COLUMN_RELATIVE_TIME)
        df = df[[options_naming.COLUMN_RELATIVE_TIME, *ordered_columns]]

    df.index = compute_timestamp_index_from_timems(
        df[options_naming.COLUMN_RELATIVE_TIME], start_time
    )

    return df, start_time, rename_map


class ServoUDataSource(DataSourceBase):
    """Servo U datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path_list: list[Path]) -> pd.DataFrame:
        all_dfs = []
        first_file_done = False
        start_time = None
        rename_map = None

        for file_path in file_path_list:
            if not first_file_done:
                df_local, start_time, rename_map = parse_file(
                    file_path, start_time, first_file=True
                )
                first_file_done = True
            else:
                df_local, _, _ = parse_file(file_path, start_time, rename_map=rename_map)
            all_dfs.append(df_local)

        df = pd.concat(all_dfs)
        return deduplicate_then_sort_index(df)

    @classmethod
    @time_it
    def _format(
        cls,
        df: pd.DataFrame,
        patient_options: dict,
        database_options_specific: dict,
    ) -> pd.DataFrame:
        df = cls._apply_timezone(
            df, database_options_specific, options_naming.DATA_SOURCE_DEFAULT_TIMEZONE
        )
        df = cls._apply_time_shift(df, patient_options)
        return cls._filter_by_datetime(df, patient_options)
