import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.servo_u.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


def parse_header_info(lines):
    """Parse header metadata from Servo U file."""
    header_info = {}
    for line in lines:
        match = re.match(r"%%\s+(.*?):\s+([\d\-:.\s]+)", line)
        if match:
            field = match.group(1).strip()
            value = match.group(2).strip()
            for fmt in ("%Y-%m-%d:%H:%M:%S.%f", "%Y-%m-%d:%H:%M:%S"):
                try:
                    header_info[field] = datetime.strptime(value, fmt)
                    break
                except Exception:
                    pass
    return header_info


def compute_timestamp_index_from_timems(time_ms_series, start_time):
    """Compute timezone-aware timestamps from Time(ms) column + log start."""
    start_time = start_time.replace(tzinfo=UTC).astimezone(
        pd.Timestamp.now(tz=options_naming.DATA_SOURCE_DEFAULT_TIMEZONE).tz
    )
    timestamps = [start_time + timedelta(milliseconds=ms) for ms in time_ms_series]
    return pd.DatetimeIndex(timestamps, name="datetime_index")


def extract_column_mapping_from_section(lines):
    """Extract mapping from the section between the 2nd and 3rd '%%%%%%...' separator."""
    separator_indices = [
        i for i, L in enumerate(lines) if L.strip().startswith("%%%%%%") and set(L.strip()) == {"%"}
    ]
    if len(separator_indices) < 3:
        msg = "File does not have enough separators for mapping section"
        raise ValueError(msg)

    start_idx = separator_indices[1] + 1
    end_idx = separator_indices[2]

    mapping = {}
    for line in lines[start_idx:end_idx]:
        line = line.strip()
        if not line or line.startswith("% Phase"):
            continue
        line = line.lstrip("%").strip()
        parts = line.split(":")
        if len(parts) != 2:
            continue
        code_with_unit, measurement = parts
        code_with_unit = code_with_unit.strip()
        measurement = measurement.strip()
        code = code_with_unit.split()[0].strip()
        unit = code_with_unit[code_with_unit.find("(") :].strip()
        mapping[code] = f"{measurement} {unit}"
    return mapping


def parse_file(filepath: Path, start_time, first_file=False, rename_map=None):
    """Parse a single Servo U file."""
    with Path.open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if first_file:
        header_info = parse_header_info(lines)
        start_time = header_info[options_naming.REFERENCE_TIME_FIELD]
        rename_map = extract_column_mapping_from_section(lines)

    # Find table header
    table_header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("%% Time(ms)"):
            table_header_idx = i
            break
    if table_header_idx is None:
        msg = f"No table header found in {filepath}"
        raise ValueError(msg)

    # Column names
    header_line = lines[table_header_idx].replace("%%", "").strip()
    columns = [c.strip() for c in header_line.split("\t")]

    # Data lines
    data_lines = lines[table_header_idx + 1 :]
    data_lines = [line for line in data_lines if line.strip() and not line.strip().startswith("%")]

    # Read table
    df = pd.read_csv(
        pd.io.common.StringIO("".join(data_lines)), sep="\t", engine="python", names=columns
    )

    # Rename measurement columns
    if rename_map:
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Drop old T(h:m:s.ms) column
    df = df.drop(columns=["T(h:m:s.ms)"], errors="ignore")

    # Reorder columns: keep Time(ms) first
    cols = df.columns.tolist()
    if options_naming.COLUMN_RELATIVE_TIME in cols:
        cols.remove(options_naming.COLUMN_RELATIVE_TIME)
        df = df[[options_naming.COLUMN_RELATIVE_TIME, *cols]]

    # Compute index from Time(ms)
    df.index = compute_timestamp_index_from_timems(
        df[options_naming.COLUMN_RELATIVE_TIME], start_time
    )

    return df, start_time, rename_map


class ServoUDataSource(DataSourceBase):
    """Servo U datasource processor."""

    DATASOURCE_NAME = "servo_u"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | None:
        return helper.find_file_list(folder_path, options_naming.KEYWORD_EXTENSION, "Servo U file")

    @classmethod
    @helper.time_it
    def _load(cls, file_path_list: list[Path], path_output: Path, **kwargs) -> pd.DataFrame:
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
        df = df[~df.index.duplicated(keep="first")]
        cls._save_dataframe(df, path_output)
        return df

    @classmethod
    @helper.time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        # Servo U doesn't need timezone handling (already has it from loading)
        df = cls._apply_time_shift(df, patient_options)
        return cls._filter_by_datetime(df, patient_options)


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None):
    return ServoUDataSource.main(patient_options, database_options_specific)
