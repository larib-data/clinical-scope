import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.fluxmed_parameters.options as options_naming  # noqa: E501
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword_file = options_naming.KEYWORD_FILE
keyword_folder = options_naming.KEYWORD_FOLDER
folder_name_visu = cst.FOLDER_NAME_VISU
file_name_df_loaded = options_naming.FILE_NAME_DATAFRAME_LOADED
if keyword_file in file_name_df_loaded:
    raise ValueError(
        f"'KEYWORD_FILE'({keyword_file}) is in "
        f"'FILE_NAME_DATAFRAME_LOADED'({file_name_df_loaded}). "
        "This dangerous since we might override the raw data, or read the wrong one"
    )


# ==================================================================================================
def _find_folder(folder_path: Path) -> Path | None:
    fluxmed_folder = helper.find_folder(folder_path, keyword_folder, "FLUXMED folder")

    return fluxmed_folder


# ==================================================================================================
def _find(folder_path: Path) -> Path | None:
    selected_path = helper.find_file(
        folder_path,
        keyword_file,
        "parameters file",
        [".txt", ".csv", ".parquet"],
    )

    return selected_path


# ==================================================================================================
@helper.time_it
def _load(file_path: Path, path_output: Path, time_col_name: str = "Time(sec)") -> pd.DataFrame:
    if file_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(file_path)
    elif file_path.suffix.lower() in [".txt", ".csv"]:
        # Extract timestamp from filename
        filename = file_path.name

        # Look for patterns like : 25_03_12-13_42_47 or 2025_03_12-13_42_47 ...
        match = re.search(r"(\d+_\d+_\d+-\d+_\d+_\d+)", filename)
        if not match:
            raise ValueError("Cannot extract timestamp from filename: " + filename)

        start_time_str = match.group(1)
        start_time = datetime.strptime(start_time_str, "%y_%m_%d-%H_%M_%S")

        # Read the first lines to get headers and units
        with Path.open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]

        # Find the column names row
        for i, line in enumerate(lines):
            if line.startswith(time_col_name.split("(")[0]):  # match only "Time" part
                col_idx = i
                break

        # Extract column names and units
        col_names = lines[col_idx].split()
        col_units = lines[col_idx + 1].split()

        # Combine name and unit
        columns = [f"{n}({u})" for n, u in zip(col_names, col_units)]

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
            sep=r"\s+",  # split on any whitespace
            header=None,
            names=columns,
            skiprows=data_start_idx,
            decimal=",",
            engine="python",
            on_bad_lines="warn",
        )

        # Strip leading/trailing spaces from column names
        df.columns = df.columns.str.strip()

        # Convert columns to numeric
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

    try:
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
    time_shift_second = patient_options.get(datasource.DataSource.FluxmedParameters.NAME, {}).get(
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
                    source_options=options_naming.source_options,
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
    database_options_parameters = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_parameters = patient_options.get(
        datasource.DataSource.FluxmedParameters.NAME, {}
    )

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

    df = _format(df, patient_options, database_options_parameters)

    list_signal_container = _extract_signals(
        df,
        patient_options=patient_options_parameters,
        database_options_specific=database_options_parameters,
    )

    return list_signal_container
