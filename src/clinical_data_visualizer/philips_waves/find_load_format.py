import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.philips_waves.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class PhilipsWavesDataSource(DataSourceBase):
    """Philips Waves datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = helper.load_csv_with_datetime_index(file_path)
        else:
            msg = f"file_path extension was neither '.csv' nor '.parquet'. Input: '{file_path}'"
            raise NotImplementedError(msg)
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]

        if path_output is not None:
            cls._save_dataframe(df, path_output)
        else:
            logger.info(
                "Not saving loaded data for philips waves, since it can be "
                "large and loading is trivial"
            )

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
    return PhilipsWavesDataSource.main(patient_options, database_options_specific)
