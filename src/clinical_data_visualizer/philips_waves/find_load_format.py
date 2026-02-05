import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.philips_waves.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword = options_naming.KEYWORD_FILE
folder_name_visu = cst.FOLDER_NAME_VISU


# ==================================================================================================
def _find(folder_path: Path) -> Path | None:
    # no suffix preference
    selected_path = helper.find_file(
        folder_path,
        keyword,
        "philips waves file",
    )

    return selected_path


# ==================================================================================================
@helper.time_it
def _load(file_path: Path, path_output: Path) -> pd.DataFrame:
    if file_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(file_path)
    else:
        raise NotImplementedError(
            f"file_path extension was neither '.csv' or '.parquet'. Input: '{file_path}'"
        )
    df = df[~df.index.duplicated(keep="first")]

    if options_naming.ALLOW_LOADED_DATAFRAME_SAVING:
        try:
            Path(path_output).parent.mkdir(parents=False, exist_ok=True)
            df.to_parquet(path_output)
        except Exception:
            logger.exception("Could not save the dataframe for future quick-reloading:")
    else:
        logger.info(
            "Not saving loaded data for philips waves, since it can be large and loading is trivial"
        )

    return df


# ==================================================================================================
def _quick_load(path_dataframe: Path) -> pd.DataFrame:
    df = pd.read_parquet(path_dataframe)
    return df


# ==================================================================================================
@helper.time_it
def _format(df: pd.DataFrame, patient_options: dict) -> pd.DataFrame:
    # Apply time-shift
    time_shift_second = patient_options.get(datasource.DataSource.PhilipsWaves.NAME, {}).get(
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
    df: pd.DataFrame, patient_options: dict, database_options_specific: dict
) -> list[Signal]:
    list_signals = database_options_specific.get(
        cst.DatabaseOptions.FIELD_DISPLAY, list(df.columns)
    )

    # Time-series
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
    database_options_waves = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_waves = patient_options.get(datasource.DataSource.PhilipsWaves.NAME, {})

    folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
    dataframe_path = folder_path / folder_name_visu / options_naming.FILE_NAME_DATAFRAME_LOADED

    if (
        options_naming.ALLOW_LOADED_DATAFRAME_SAVING
        and patient_options.get(cst.PatientOptions.QuickLoad.NAME, False)
        and dataframe_path.is_file()
    ):
        df = _quick_load(dataframe_path)
    else:
        file_path = _find(folder_path)
        if file_path is None:
            return []
        df = _load(file_path, dataframe_path)

    df = _format(df, patient_options)

    list_signal_container = _extract_signals(df, patient_options_waves, database_options_waves)

    return list_signal_container
