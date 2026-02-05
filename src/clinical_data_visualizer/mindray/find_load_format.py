import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.mindray.options as options_naming
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
    mindray_folder = helper.find_folder(folder_path, keyword_folder, "Mindray folder")

    return mindray_folder


# ==================================================================================================
def _find(folder_path: Path) -> list[Path] | None:
    mindray_files = helper.find_file_list(folder_path, keyword_extension, "Mindray files file")

    return mindray_files


# ==================================================================================================
def _optimize_df_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame types using pandas nullable dtypes.
    - Integer columns -> nullable integer dtypes (Int8, Int16, UInt8, etc.)
    - Float columns -> downcast to float32 if possible
    - Works with NaNs (missing values)
    """
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]) or pd.api.types.is_float_dtype(df[col]):
            # Check if column contains only integer-like values
            is_integer_like = (df[col].dropna() % 1 == 0).all()

            c_min = df[col].min(skipna=True)
            c_max = df[col].max(skipna=True)

            if is_integer_like:
                if c_min >= 0:
                    # Unsigned nullable integer
                    if c_max <= np.iinfo(np.uint8).max:
                        df[col] = df[col].astype("UInt8")
                    elif c_max <= np.iinfo(np.uint16).max:
                        df[col] = df[col].astype("UInt16")
                    elif c_max <= np.iinfo(np.uint32).max:
                        df[col] = df[col].astype("UInt32")
                    else:
                        df[col] = df[col].astype("UInt64")
                else:
                    # Signed nullable integer
                    if c_min >= np.iinfo(np.int8).min and c_max <= np.iinfo(np.int8).max:
                        df[col] = df[col].astype("Int8")
                    elif c_min >= np.iinfo(np.int16).min and c_max <= np.iinfo(np.int16).max:
                        df[col] = df[col].astype("Int16")
                    elif c_min >= np.iinfo(np.int32).min and c_max <= np.iinfo(np.int32).max:
                        df[col] = df[col].astype("Int32")
                    else:
                        df[col] = df[col].astype("Int64")
            else:
                # Float column → downcast to float32 if possible
                df[col] = pd.to_numeric(df[col], downcast="float")
    return df


# ==================================================================================================
def _get_name_time_series(file_path: Path) -> str:
    full_name = file_path.name
    match = re.search(r"^([^-]+)", full_name)
    name = match.group(1)

    return name


# ==================================================================================================
def _is_float(x):
    """True if x is a valid float"""
    try:
        float(x)
        return True
    except Exception:
        return False


# ==================================================================================================
def _remove_polluted_columns(df):
    """
    Remove polluted columns where at least one cell contains non-numeric data.
    Column 0 is kept (timestamp).
    """
    good_cols = [0]  # Keep timestamp column

    for col in df.columns[1:]:
        series = df[col].astype(str)

        # Condition 1: must all convert to float (except empty "")
        numeric_mask = series.apply(lambda x: _is_float(x))

        # Condition 2: detect known garbage patterns
        pattern_mask = series.str.contains(
            r"SampleRate:|TimeStamp\(|Beep_Pulse|HeartBeat_", regex=True, na=False
        )

        if numeric_mask.all() and not pattern_mask.any():
            good_cols.append(col)

    return df[good_cols]


# ==================================================================================================
@helper.time_it
def _load(
    file_path_list: list[Path], path_output: Path, optimize_storage_dtypes: bool = True
) -> pd.DataFrame | None:
    df_list = []

    for file_path in file_path_list:
        name = _get_name_time_series(file_path)
        data = pd.read_csv(file_path, delimiter=",", decimal=".", header=None)
        data = _remove_polluted_columns(data)
        time_rows = pd.to_datetime(data.iloc[:, 0])
        signal = data.iloc[:, 1:].to_numpy().flatten()
        samples_per_row = data.shape[1] - 1
        timestamps = []
        for t in time_rows:
            # evenly spaced timestamps in the 1-second interval (endpoint=False to avoid overlap)
            row_times = np.linspace(
                t.value, (t + pd.Timedelta(seconds=1)).value, samples_per_row, endpoint=False
            )
            timestamps.extend(pd.to_datetime(row_times))
        df_local = pd.DataFrame({name: signal}, index=timestamps)
        df_list.append(df_local)

    df_list = [df.sort_index() for df in df_list]
    df = pd.concat(df_list, axis=1)
    df = df.sort_index()
    if optimize_storage_dtypes:
        df = _optimize_df_types(df)

    try:
        Path(path_output).parent.mkdir(parents=False, exist_ok=True)
        df.to_parquet(path_output, engine="pyarrow")
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
    time_shift_second = patient_options.get(datasource.DataSource.MindRay.NAME, {}).get(
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
    database_options_mindray = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_mindray = patient_options.get(datasource.DataSource.MindRay.NAME, {})

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

    df = _format(df, patient_options, database_options_mindray)

    list_signal_container = _extract_signals(
        df,
        patient_options=patient_options_mindray,
        database_options_specific=database_options_mindray,
    )

    return list_signal_container
