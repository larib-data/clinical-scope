import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.philips_waves.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class PhilipsWavesDataSource(DataSourceBase):
    """Philips Waves datasource processor."""

    DATASOURCE_NAME = "philips_waves"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming
    ALLOW_QUICK_LOAD = options_naming.ALLOW_LOADED_DATAFRAME_SAVING

    @classmethod
    def _find(cls, folder_path: Path) -> Path | None:
        return helper.find_file(
            folder_path,
            options_naming.KEYWORD_FILE,
            "philips waves file",
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path, **kwargs) -> pd.DataFrame:
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        else:
            raise NotImplementedError(
                f"file_path extension was neither '.csv' or '.parquet'. Input: '{file_path}'"
            )
        df = df[~df.index.duplicated(keep="first")]

        if options_naming.ALLOW_LOADED_DATAFRAME_SAVING:
            cls._save_dataframe(df, path_output)
        else:
            logger.info(
                "Not saving loaded data for philips waves, since it can be large and loading is trivial"
            )

        return df

    @classmethod
    @helper.time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        # Philips waves doesn't need timezone handling (already has it)
        df = cls._apply_time_shift(df, patient_options)
        df = cls._filter_by_datetime(df, patient_options)
        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None):
    return PhilipsWavesDataSource.main(patient_options, database_options_specific)
