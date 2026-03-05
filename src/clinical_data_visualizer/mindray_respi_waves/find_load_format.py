import ast
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import clinical_data_visualizer.mindray_respi_waves.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


class MindRayRespiWavesDataSource(DataSourceBase):
    """MindRay Respi Waves datasource processor."""

    DATASOURCE_NAME = "mindray_respi_waves"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming
    SOURCE_OPTIONS = options_naming.source_options

    @classmethod
    def _find(cls, folder_path: Path) -> Path | None:
        return helper.find_file(
            folder_path,
            options_naming.KEYWORD_FILE,
            "MindRay Respi Waves files",
            options_naming.FILE_EXTENSION_LIST,
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path: Path, path_output: Path, **kwargs: Any) -> pd.DataFrame:
        """
        Load and parse MindRay Respi Waves data.

        The data has one row per waveform block (not per timestamp).
        We need to:
        1. Create a composite column "full_label_name" = f"{waveform_label}-{waveform_unit}"
        2. Parse the waveform_samples list and apply scale_factor
        3. Expand timestamps to nanosecond precision using sampling_rate
        4. Pivot the data to have one column per unique waveform
        5. Set the expanded timestamps as the index
        """
        database_options_specific = kwargs.get("database_options_specific", {})

        # Load the data
        if file_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(file_path)
        elif file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path, delimiter=",", decimal=".")
        else:
            msg = f"Unsupported extension: '{file_path}'"
            raise NotImplementedError(msg)

        base_timestamps = pd.to_datetime(df["event_timestamp"])
        full_label_names = df["waveform_label"] + "-" + df["waveform_unit"]

        # Expand waveform blocks to per-sample rows.
        # Outer loop: one iteration per waveform block (few hundreds to low thousands of rows).
        # Sample expansion inside each block is fully vectorized with numpy —
        # no Python-level per-sample iteration, and no list-of-dicts overhead.
        timestamps_chunks: list[np.ndarray] = []
        labels_chunks: list[np.ndarray] = []
        values_chunks: list[np.ndarray] = []

        for samples_raw, base_ts, rate, scale, wf_label, full_name in zip(
            df["waveform_samples"],
            base_timestamps,
            df["sampling_rate"],
            df["scale_factor"],
            df["waveform_label"],
            full_label_names,
            strict=True,
        ):
            # Parse waveform_samples: str from CSV, ndarray/list from parquet
            try:
                samples = (
                    ast.literal_eval(samples_raw) if isinstance(samples_raw, str) else samples_raw
                )
            except (ValueError, SyntaxError) as e:
                logger.warning("Failed to parse waveform_samples for %s: %s", wf_label, e)
                continue

            samples_arr = np.asarray(samples, dtype=float)
            n = len(samples_arr)
            if n == 0:
                continue

            if rate <= 0:
                logger.warning("sampling_rate <= 0 for %s, skipping block.", wf_label)
                continue

            # Generate timestamps as int64 nanoseconds (fastest arithmetic path).
            # base_ts.value is nanoseconds since epoch; offsets computed in ns.
            ns_per_sample = round(1_000_000_000.0 / rate)
            offsets_ns = np.arange(n, dtype="int64") * ns_per_sample
            timestamps_chunks.append(base_ts.value + offsets_ns)
            labels_chunks.append(np.full(n, full_name))
            values_chunks.append(samples_arr * scale)

        if not timestamps_chunks:
            logger.warning("[%s] No data rows expanded.", cls.DATASOURCE_NAME)
            return pd.DataFrame()

        # Build expanded DataFrame from concatenated arrays (avoids list-of-dicts overhead)
        df_expanded = pd.DataFrame(
            {
                "event_timestamp": pd.DatetimeIndex(np.concatenate(timestamps_chunks)),
                "full_label_name": np.concatenate(labels_chunks),
                "waveform_value": np.concatenate(values_chunks),
            }
        )

        # Pivot: one column per waveform type
        df_pivoted = df_expanded.pivot_table(
            index="event_timestamp",
            columns="full_label_name",
            values="waveform_value",
            aggfunc="first",
        )

        df_pivoted.columns = df_pivoted.columns.get_level_values(0)
        df_pivoted = df_pivoted.sort_index()
        df_pivoted = df_pivoted[~df_pivoted.index.duplicated(keep="first")]

        # Apply timezone if needed
        df_pivoted = helper.apply_timezone_to_dataframe(
            df_pivoted,
            database_options_specific,
            options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
            options_naming,
        )

        cls._save_dataframe(df_pivoted, path_output)
        return df_pivoted


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    """Load and process MindRay Respi Waves data."""
    return MindRayRespiWavesDataSource.main(patient_options, database_options_specific)
