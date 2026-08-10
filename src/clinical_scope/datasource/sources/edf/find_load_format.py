import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyedflib

import clinical_scope.constants as cst
import clinical_scope.datasource.sources.edf.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_utils import deduplicate_then_sort_index

logger = logging.getLogger(__name__)


def _unique_labels(labels: list[str]) -> list[str]:
    """Suffix repeated channel labels — EDF allows duplicates, a DataFrame column can't."""
    seen: dict[str, int] = {}
    unique_labels = []
    for label in labels:
        occurrence = seen.get(label, 0)
        seen[label] = occurrence + 1
        unique_labels.append(label if occurrence == 0 else f"{label}_{occurrence + 1}")
    return unique_labels


def _channel_index(
    start_time: pd.Timestamp, sample_count: int, sample_rate: float
) -> pd.DatetimeIndex:
    """Regular index for one channel — EDF sets a sample rate per signal, not per file."""
    offsets_ns = np.round(np.arange(sample_count) * 1e9 / sample_rate).astype("int64")
    return pd.DatetimeIndex(start_time + pd.to_timedelta(offsets_ns, unit="ns"))


def _resolve_start_time(raw_start: pd.Timestamp) -> pd.Timestamp:
    """Map an 'unknown date' header onto the canonical sentinel, keeping the time of day."""
    if raw_start.date() not in options_naming.UNKNOWN_START_DATES:
        return raw_start
    canonical_day = pd.Timestamp(options_naming.CANONICAL_UNKNOWN_START_DATE)
    return canonical_day + (raw_start - raw_start.normalize())


def read_edf_file(file_path: Path) -> pd.DataFrame:
    """Read one EDF/EDF+ file into a wide, tz-naive DataFrame of physical-unit values."""
    reader = pyedflib.EdfReader(str(file_path))
    try:
        start_time = _resolve_start_time(pd.Timestamp(reader.getStartdatetime()))
        labels = _unique_labels(reader.getSignalLabels())
        sample_counts = reader.getNSamples()
        channels = [
            pd.Series(
                reader.readSignal(channel_index),
                index=_channel_index(
                    start_time,
                    int(sample_counts[channel_index]),
                    reader.getSampleFrequency(channel_index),
                ),
                name=label,
            )
            for channel_index, label in enumerate(labels)
        ]
        annotation_count = len(reader.readAnnotations()[0])
    finally:
        reader.close()

    if annotation_count:
        logger.info(
            "[%s] %s carries %d EDF+ annotation(s); they are not imported as signals.",
            options_naming.DATASOURCE_NAME,
            file_path.name,
            annotation_count,
        )

    if not channels:
        return pd.DataFrame(index=pd.DatetimeIndex([], name=cst.DATETIME_INDEX_NAME))

    # Channels may run at different rates, so the union index carries NaN wherever a slower
    # channel has no sample. Identical indexes (the usual case) concatenate unchanged.
    df = pd.concat(channels, axis=1)
    df.index.name = cst.DATETIME_INDEX_NAME
    return df


class EDFDataSource(DataSourceBase):
    """EDF / EDF+ datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(
        cls,
        file_path_list: list[Path],
        path_output: Path | None,
        **kwargs: Any,  # noqa: ARG003
    ) -> pd.DataFrame:
        frames = [read_edf_file(file_path) for file_path in file_path_list]
        if not frames:
            return pd.DataFrame(index=pd.DatetimeIndex([], name=cst.DATETIME_INDEX_NAME))

        df = frames[0] if len(frames) == 1 else pd.concat(frames)
        df = deduplicate_then_sort_index(df)

        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df

    @classmethod
    def _anchor_undated_recording(cls, df: pd.DataFrame, patient_options: dict) -> pd.DataFrame:
        """
        Place a recording whose EDF header carried no start date, using `recording_start`.

        A file that states its own date always wins — `recording_start` only fills a gap. A
        date-only value keeps the file's own time of day, so a recording whose date alone was
        scrubbed does not have its clock time retyped; a full timestamp overrides both, which
        is the only way to place a file whose time was zeroed too.

        Lives in _format rather than _load because _load's output is the cached parquet: a
        start resolved there would outlive the option that produced it, and survive changing it.
        """
        if df.empty:
            return df

        sentinel = pd.Timestamp(options_naming.CANONICAL_UNKNOWN_START_DATE)
        if df.index[0].normalize() != sentinel:
            return df

        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        raw_start = patient_options_specific.get(
            options_naming.PatientOptionsDataSourceRelative.RecordingStart.NAME
        )
        if not raw_start:
            logger.warning(
                "EDF file carries no start date and no 'recording_start' was given — timestamps "
                "are kept relative to %s. Set 'recording_start' to place the recording in time.",
                sentinel.date(),
            )
            return df

        # A bare date is the "only the date was scrubbed" case: shift by whole days so the file's
        # own time of day survives. A value carrying a clock time places the first sample on it.
        recording_start = pd.Timestamp(raw_start)
        if ":" in str(raw_start):
            offset = recording_start - df.index[0]
        else:
            offset = recording_start - sentinel

        df = df.copy(deep=False)
        df.index = df.index + offset
        return df

    @classmethod
    @time_it
    def _format(
        cls,
        df: pd.DataFrame,
        patient_options: dict,
        database_options_specific: dict,
    ) -> pd.DataFrame:
        df = cls._anchor_undated_recording(df, patient_options)
        return super()._format(df, patient_options, database_options_specific)
