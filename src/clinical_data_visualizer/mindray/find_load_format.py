import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

import clinical_data_visualizer.mindray.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


def _optimize_df_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame types using pandas nullable dtypes.
    - Integer columns -> nullable integer dtypes (Int8, Int16, UInt8, etc.)
    - Float columns -> downcast to float32 if possible
    - Works with NaNs (missing values)
    """
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]) or pd.api.types.is_float_dtype(df[col]):
            is_integer_like = (df[col].dropna() % 1 == 0).all()
            c_min = df[col].min(skipna=True)
            c_max = df[col].max(skipna=True)

            if is_integer_like:
                if c_min >= 0:
                    if c_max <= np.iinfo(np.uint8).max:
                        df[col] = df[col].astype("UInt8")
                    elif c_max <= np.iinfo(np.uint16).max:
                        df[col] = df[col].astype("UInt16")
                    elif c_max <= np.iinfo(np.uint32).max:
                        df[col] = df[col].astype("UInt32")
                    else:
                        df[col] = df[col].astype("UInt64")
                elif c_min >= np.iinfo(np.int8).min and c_max <= np.iinfo(np.int8).max:
                    df[col] = df[col].astype("Int8")
                elif c_min >= np.iinfo(np.int16).min and c_max <= np.iinfo(np.int16).max:
                    df[col] = df[col].astype("Int16")
                elif c_min >= np.iinfo(np.int32).min and c_max <= np.iinfo(np.int32).max:
                    df[col] = df[col].astype("Int32")
                else:
                    df[col] = df[col].astype("Int64")
            else:
                df[col] = pd.to_numeric(df[col], downcast="float")
    return df


def _get_name_time_series(file_path: Path) -> str:
    """Extract signal name from filename."""
    full_name = file_path.name
    match = re.search(r"^([^-]+)", full_name)
    return match.group(1)


def _is_float(x):
    """True if x is a valid float."""
    try:
        float(x)
        return True
    except Exception:
        return False


def _remove_polluted_columns(df):
    """Remove polluted columns where at least one cell contains non-numeric data."""
    good_cols = [0]  # Keep timestamp column

    for col in df.columns[1:]:
        series = df[col].astype(str)
        numeric_mask = series.apply(lambda x: _is_float(x))
        pattern_mask = series.str.contains(
            r"SampleRate:|TimeStamp\(|Beep_Pulse|HeartBeat_", regex=True, na=False
        )
        if numeric_mask.all() and not pattern_mask.any():
            good_cols.append(col)

    return df[good_cols]


class MindRayDataSource(DataSourceBase):
    """MindRay datasource processor."""

    DATASOURCE_NAME = "mindray"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming

    @classmethod
    def _find_folder(cls, folder_path: Path) -> Path | None:
        return helper.find_folder(folder_path, options_naming.KEYWORD_FOLDER, "Mindray folder")

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | None:
        return helper.find_file_list(
            folder_path, options_naming.KEYWORD_EXTENSION, "Mindray files file"
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path_list: list[Path], path_output: Path, **kwargs) -> pd.DataFrame:
        optimize_storage_dtypes = True
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

        cls._save_dataframe(df, path_output)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None):
    return MindRayDataSource.main(patient_options, database_options_specific)
