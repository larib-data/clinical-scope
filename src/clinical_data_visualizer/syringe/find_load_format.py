import csv
import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.syringe.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword = options_naming.KEYWORD_FILE
raw_file_extension_preference = options_naming.ORDERED_PREFERED_RAW_FILES_EXTENSION
file_name_df_loaded = options_naming.FILE_NAME_DATAFRAME_LOADED

folder_name_visu = cst.FOLDER_NAME_VISU


# ==================================================================================================
def _find(folder_path: Path) -> Path | None:
    selected_path = helper.find_file(
        folder_path,
        keyword,
        "syringe file",
        raw_file_extension_preference,
    )

    return selected_path


# ==================================================================================================
@helper.time_it
def _load(file_path: Path, path_output: Path) -> pd.DataFrame:
    if file_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(file_path)
    elif file_path.suffix.lower() == ".csv":
        # Try to detect delimiter automatically
        with Path.open(file_path, "r", newline="") as f:
            sample = f.read(2048)
            dialect = csv.Sniffer().sniff(sample)
            sep = dialect.delimiter

        df = pd.read_csv(file_path, sep=sep)

        # If the index is integer dtype, we assume it means it's basic dtype
        if pd.api.types.is_integer_dtype(df.index):
            time_candidates = [
                col
                for col in df.columns
                if col.lower().replace("'", "").replace('"', "")
                in options_naming.CANDIDATE_LIST_DATETIME_COLUMN
            ]
            if time_candidates:
                time_col = time_candidates[0]
                try:
                    # Try parse as datetime
                    df[time_col] = pd.to_datetime(df[time_col], errors="raise")
                    df = df.set_index(time_col)
                except (ValueError, TypeError):
                    # Fallback: treat as float (seconds)
                    df = df.set_index(time_col)
            else:
                raise NotImplementedError(
                    "We need a column to play the role of the datetime index column<br>"
                    "Maybe we could do something with a given day and if a relative column time "
                    "exists, but not implemented."
                )

        cols_to_convert = [c for c in df.columns]
        df[cols_to_convert] = df[cols_to_convert].apply(pd.to_numeric, errors="coerce")
    else:
        raise NotImplementedError(
            f"Invalid file format: {file_path.name}. Only .csv or .parquet supported."
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
    time_shift_second = patient_options.get(datasource.DataSource.Syringe.NAME, {}).get(
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
    database_options_syringe = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_syringe = patient_options.get(datasource.DataSource.Syringe.NAME, {})

    folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
    dataframe_path = folder_path / folder_name_visu / file_name_df_loaded

    if (
        patient_options.get(cst.PatientOptions.QuickLoad.NAME, cst.DEFAULT_QUICK_LOAD)
        and dataframe_path.is_file()
    ):
        df = _quick_load(dataframe_path)
    else:
        file_path = _find(folder_path)
        if file_path is None:
            return []
        df = _load(file_path, dataframe_path)

    df = _format(df, patient_options, database_options_syringe)

    list_signal_container = _extract_signals(
        df,
        patient_options=patient_options_syringe,
        database_options_specific=database_options_syringe,
    )

    return list_signal_container
