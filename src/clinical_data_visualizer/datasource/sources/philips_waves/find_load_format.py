import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.datasource.sources.philips_waves.options as options_naming
from clinical_data_visualizer.datasource.base import DataSourceBase
from clinical_data_visualizer.datasource.timing import time_it
from clinical_data_visualizer.io.file_utils import load_csv_with_datetime_index

logger = logging.getLogger(__name__)


class PhilipsWavesDataSource(DataSourceBase):
    """Philips Waves datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs) -> pd.DataFrame:  # noqa: ARG003
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = load_csv_with_datetime_index(file_path)
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
    @time_it
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
