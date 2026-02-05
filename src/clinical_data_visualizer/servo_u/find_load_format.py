import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.servo_u.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword_folder = options_naming.KEYWORD_FOLDER
keyword_extension = options_naming.KEYWORD_EXTENSION
folder_name_visu = cst.FOLDER_NAME_VISU
file_name_df_loaded = options_naming.FILE_NAME_DATAFRAME_LOADED


# ==================================================================================================
def _find_folder(folder_path: Path) -> Path | None:
    servo_u_folder = helper.find_folder(folder_path, keyword_folder, "Servo U folder")

    return servo_u_folder


# ==================================================================================================
def _find(folder_path: Path) -> list[Path] | None:
    servo_u_files = helper.find_file_list(folder_path, keyword_extension, "Servo U file")

    return servo_u_files


# ==================================================================================================
def parse_header_info(lines):
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


# ==================================================================================================
def compute_timestamp_index_from_timems(time_ms_series, start_time):
    """
    Compute timezone-aware timestamps from Time(ms) column + log start.
    """
    start_time = start_time.replace(tzinfo=timezone.utc).astimezone(
        pd.Timestamp.now(tz=options_naming.DATA_SOURCE_DEFAULT_TIMEZONE).tz
    )
    timestamps = [start_time + timedelta(milliseconds=ms) for ms in time_ms_series]
    return pd.DatetimeIndex(timestamps, name="datetime_index")


# ==================================================================================================
def extract_column_mapping_from_section(lines):
    """
    Extract mapping from the section between the 2nd and 3rd '%%%%%%...' separator.
    Returns a dictionary: code -> 'Measurement (unit)'
    """
    # Find all separator indices
    separator_indices = [
        i for i, L in enumerate(lines) if L.strip().startswith("%%%%%%") and set(L.strip()) == {"%"}
    ]
    if len(separator_indices) < 3:
        raise ValueError("File does not have enough separators for mapping section")

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


# ==================================================================================================
def parse_file(filepath: Path, start_time, first_file=False, rename_map=None):
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
        raise ValueError(f"No table header found in {filepath}")

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


# ==================================================================================================
@helper.time_it
def _load(file_path_list: list[Path], path_output: Path) -> pd.DataFrame:
    all_dfs = []
    first_file_done = False
    start_time = None
    rename_map = None

    for file_path in file_path_list:
        if not first_file_done:
            df_local, start_time, rename_map = parse_file(file_path, start_time, first_file=True)
            first_file_done = True
        else:
            df_local, _, _ = parse_file(file_path, start_time, rename_map=rename_map)
        all_dfs.append(df_local)

    df = pd.concat(all_dfs)

    df = df[~df.index.duplicated(keep="first")]

    try:
        Path(path_output).parent.mkdir(parents=False, exist_ok=True)
        df.to_parquet(path_output)
    except Exception:
        logger.exception("Could not save the dataframe for future quick-reloading:")

    return df


# ==================================================================================================
def _quick_load(path_dataframe: Path) -> pd.DataFrame:
    df = pd.read_parquet(path_dataframe)
    return df


# ==================================================================================================
@helper.time_it
def _format(df: pd.DataFrame, patient_options: dict) -> pd.DataFrame:
    # Apply time-shift
    time_shift_second = patient_options.get(datasource.DataSource.ServoU.NAME, {}).get(
        options_naming.PatientOptionsDataSourceRelative.TimeShift.NAME, 0.0
    )
    helper.shift_data_by_seconds(df, time_shift_second)

    # Filter by datetime start and end
    datetime_start = patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
    datetime_end = patient_options.get(cst.PatientOptions.DatetimeEnd.NAME)
    datetime_start = pd.Timestamp(datetime_start) if datetime_start else None
    datetime_end = pd.Timestamp(datetime_end) if datetime_end else None
    df = helper.filter_data_by_timestamps(
        df, time_start=datetime_start, time_end=datetime_end, filter_date=True
    )

    return df


# ==================================================================================================
@helper.time_it
def _extract_signals(
    df: pd.DataFrame,
    patient_options: dict,
    database_options_specific: dict,
) -> list[Signal]:
    list_signals = database_options_specific.get(
        cst.DatabaseOptions.FIELD_DISPLAY, list(df.columns)
    )

    list_signal_container = []
    for signal in list_signals:
        try:
            list_signal_container.append(
                Signal.time_series_from_dataframe(
                    df=df,
                    raw_signal_name=signal,
                    patient_options=patient_options,
                    database_options_specific=database_options_specific,
                )
            )
        except Exception:  # noqa: PERF203
            logger.exception("❌ Could not process the signal '%s' as Signal object", signal)

    return list_signal_container


# ==================================================================================================
@helper.time_it
def main(
    patient_options: dict,
    database_options_specific: dict | None,
) -> list[Signal]:
    database_options_servo_u = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_servo_u = patient_options.get(datasource.DataSource.ServoU.NAME, {})

    folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
    dataframe_path = folder_path / folder_name_visu / file_name_df_loaded

    if patient_options.get(cst.PatientOptions.QuickLoad.NAME, False) and dataframe_path.is_file():
        df = _quick_load(dataframe_path)
    else:
        fluxmed_folder_path = _find_folder(folder_path)
        if fluxmed_folder_path is None:
            return []
        file_path = _find(fluxmed_folder_path)
        if file_path is None:
            return []
        df = _load(file_path, dataframe_path)

    df = _format(df, patient_options)

    list_signal_container = _extract_signals(
        df,
        patient_options=patient_options_servo_u,
        database_options_specific=database_options_servo_u,
    )

    return list_signal_container
