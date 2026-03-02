import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.philips_numerics.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class PhilipsNumericsDataSource(DataSourceBase):
    """Philips Numerics datasource processor."""

    DATASOURCE_NAME = "philips_numerics"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming
    SOURCE_OPTIONS = options_naming.source_options

    @classmethod
    def _find(cls, folder_path: Path) -> Path | None:
        return helper.find_file(
            folder_path,
            options_naming.KEYWORD_FILE,
            "philips numerics file",
            options_naming.FILE_EXTENSION_LIST,
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        else:
            msg = f"file_path extension was neither '.csv' or '.parquet'. Input: '{file_path}'"
            raise NotImplementedError(msg)
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        cls._save_dataframe(df, path_output)
        return df

    @classmethod
    @helper.time_it
    def _format(
        cls,
        df: pd.DataFrame,
        patient_options: dict,
        database_options_specific: dict,
    ) -> pd.DataFrame:
        # Apply timezone only if missing (parquet already has it; CSV may not)
        df = cls._apply_timezone(
            df, database_options_specific, options_naming.DATA_SOURCE_DEFAULT_TIMEZONE
        )
        df = cls._apply_time_shift(df, patient_options)
        return cls._filter_by_datetime(df, patient_options)


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    return PhilipsNumericsDataSource.main(patient_options, database_options_specific)
