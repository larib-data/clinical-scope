import ast
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import clinical_scope.datasource.sources.mindray_respi_waves.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.formatting.timezone import apply_timezone_to_dataframe
from clinical_scope.datasource.timing import time_it

logger = logging.getLogger(__name__)


class MindRayRespiWavesDataSource(DataSourceBase):
    """MindRay Respi Waves datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path: Path, path_output: Path | None, **kwargs: Any) -> pd.DataFrame:
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

        if df.empty:
            logger.warning("[%s] Empty data file: %s", cls.DATASOURCE_NAME, file_path)
            return pd.DataFrame(
                index=pd.DatetimeIndex([], tz=options_naming.DATA_SOURCE_DEFAULT_TIMEZONE)
            )

        base_timestamps = pd.to_datetime(df["event_timestamp"])
        tz = base_timestamps.dt.tz
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
            tz_str = str(tz) if tz is not None else options_naming.DATA_SOURCE_DEFAULT_TIMEZONE
            return pd.DataFrame(index=pd.DatetimeIndex([], tz=tz_str))

        # Build expanded DataFrame from concatenated arrays (avoids list-of-dicts overhead)
        df_expanded = pd.DataFrame(
            {
                "event_timestamp": pd.DatetimeIndex(
                    np.concatenate(timestamps_chunks),
                    tz=str(tz) if tz is not None else options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
                ),
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
        df_pivoted = apply_timezone_to_dataframe(
            df_pivoted,
            database_options_specific,
            options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
            options_naming,
        )

        if path_output is not None:
            cls._save_dataframe(df_pivoted, path_output)
        return df_pivoted
