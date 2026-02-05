import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.fluxmed_signals.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword_file = options_naming.KEYWORD_FILE
keyword_folder = options_naming.KEYWORD_FOLDER
folder_name_visu = cst.FOLDER_NAME_VISU
file_name_df_loaded = options_naming.FILE_NAME_DATAFRAME_LOADED


# ==================================================================================================
def _find_folder(folder_path: Path) -> Path | None:
    fluxmed_folder = helper.find_folder(folder_path, keyword_folder, "FLUXMED folder")

    return fluxmed_folder


# ==================================================================================================
def _find(folder_path: Path) -> Path | None:
    selected_path = helper.find_file(
        folder_path,
        keyword_file,
        "paramsignals",
        [".txt", ".csv", ".parquet"],
    )
    return selected_path


# ==================================================================================================
@helper.time_it
def _load(file_path: Path, path_output: Path) -> pd.DataFrame:
    if file_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(file_path)
    elif file_path.suffix.lower() in [".txt", ".csv"]:
        # 0) Extract timestamp from filename
        filename = file_path.name

        # Look for patterns like : 25_03_12-13_42_47 or 2025_03_12-13_42_47 ...
        match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
        if not match:
            raise ValueError("Cannot extract timestamp from filename: " + filename)

        start_time_str = match.group(1)
        start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S")

        # 1) Read raw file
        with Path.open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f]

        # 2) Find header row
        header_idx = None
        for i, line in enumerate(lines):
            if line.startswith("Time"):
                header_idx = i
                break

        if header_idx is None:
            raise RuntimeError("No 'Time' header found")

        units_idx = header_idx + 1
        data_start_idx = units_idx + 6  # skip 6 lines after units

        # 3) Build column names
        col_names = re.split(r"\s+", lines[header_idx])
        col_units = re.split(r"\s+", lines[units_idx])
        columns = [f"{name}({unit})" for name, unit in zip(col_names, col_units)]

        # 4) Extract numeric rows only
        numeric_lines = [
            line for line in lines[data_start_idx:] if re.match(r"^[0-9]+[.,][0-9]", line)
        ]

        if not numeric_lines:
            raise RuntimeError("No numeric signal rows found after skipping 6 lines")

        # 5) Load into DataFrame
        df = pd.read_csv(
            pd.io.common.StringIO("\n".join(numeric_lines)),
            sep=r"\s+",
            header=None,
            names=columns,
            decimal=",",
            engine="python",
        )

        # 6) Build datetime index
        time_col = columns[0]
        df = df.apply(pd.to_numeric, errors="coerce")

        df.index = pd.to_datetime([start_time + timedelta(seconds=float(t)) for t in df[time_col]])

        df.index.name = "datetime_index"

    else:
        raise NotImplementedError(
            f"file_path extension was neither '.txt', '.csv' or '.parquet'. Input: '{file_path}'"
        )
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
def _format(
    df: pd.DataFrame, patient_options: dict, database_options_specific: dict
) -> pd.DataFrame:
    # Add time-zone if None present, otherwise go to library timezone
    timezone = database_options_specific.get(cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}).get(
        options_naming.DatabaseOptionsAdditionalInformations.TIMEZONE,
        options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
    )
    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone)

    # Apply time-shift
    time_shift_second = patient_options.get(datasource.DataSource.FluxmedSignals.NAME, {}).get(
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
    database_options_signals = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_signals = patient_options.get(datasource.DataSource.FluxmedSignals.NAME, {})

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

    df = _format(df, patient_options, database_options_signals)

    list_signal_container = _extract_signals(
        df,
        patient_options=patient_options_signals,
        database_options_specific=database_options_signals,
    )

    return list_signal_container
