import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from defusedxml.ElementTree import parse as parse_xml

import clinical_scope.datasource.sources.mindray_scope.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_reading import read_each
from clinical_scope.io.time_axis import deduplicate_then_sort_index

logger = logging.getLogger(__name__)


def _optimize_df_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame types using pandas nullable dtypes.

    Integer columns -> nullable integer dtypes (Int8, Int16, UInt8, etc.)
    Float columns -> downcast to float32 if possible
    Works with NaNs (missing values).
    """
    for column in df.columns:
        if pd.api.types.is_integer_dtype(df[column]) or pd.api.types.is_float_dtype(df[column]):
            is_integer_like = (df[column].dropna() % 1 == 0).all()
            column_min = df[column].min(skipna=True)
            column_max = df[column].max(skipna=True)

            if is_integer_like:
                if column_min >= 0:
                    if column_max <= np.iinfo(np.uint8).max:
                        df[column] = df[column].astype("UInt8")
                    elif column_max <= np.iinfo(np.uint16).max:
                        df[column] = df[column].astype("UInt16")
                    elif column_max <= np.iinfo(np.uint32).max:
                        df[column] = df[column].astype("UInt32")
                    else:
                        df[column] = df[column].astype("UInt64")
                elif column_min >= np.iinfo(np.int8).min and column_max <= np.iinfo(np.int8).max:
                    df[column] = df[column].astype("Int8")
                elif column_min >= np.iinfo(np.int16).min and column_max <= np.iinfo(np.int16).max:
                    df[column] = df[column].astype("Int16")
                elif column_min >= np.iinfo(np.int32).min and column_max <= np.iinfo(np.int32).max:
                    df[column] = df[column].astype("Int32")
                else:
                    df[column] = df[column].astype("Int64")
            else:
                df[column] = pd.to_numeric(df[column], downcast="float")
    return df


def _get_name_time_series(file_path: Path) -> str:
    """Extract signal name from filename."""
    full_name = file_path.name
    match = re.search(r"^([^-]+)", full_name)
    return match.group(1)


def _is_float(value: Any) -> bool:
    """
    Return True if float(*value*) succeeds.

    ValueError and TypeError give False; anything else (OverflowError) propagates.
    """
    try:
        float(value)
    except (ValueError, TypeError):
        return False
    else:
        return True


def _remove_polluted_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop columns holding a non-numeric cell or a device marker.

    Markers are SampleRate:, TimeStamp(, Beep_Pulse and HeartBeat_.
    """
    good_columns = [0]  # Keep timestamp column

    for column in df.columns[1:]:
        series = df[column].astype(str)
        numeric_mask = series.apply(_is_float)
        pattern_mask = series.str.contains(
            r"SampleRate:|TimeStamp\(|Beep_Pulse|HeartBeat_", regex=True, na=False
        )
        if numeric_mask.all() and not pattern_mask.any():
            good_columns.append(column)

    return df[good_columns]


def _load_xml(path_xml: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load and parse XML file containing waveform data.

    Returns:
        Tuple of (df_waveform, df_patient)

    """
    tree = parse_xml(path_xml)
    root = tree.getroot()

    # Elements may be absent in some file variants.
    def _safe_text(element: Any) -> str | None:
        return element.text if element is not None else None

    patient = {
        "Gender": _safe_text(root.find(".//Patient/Demographics/Gender")),
        "Bed": _safe_text(root.find(".//Patient/AssignedLocation/Bed")),
        "PointOfCare": _safe_text(root.find(".//Patient/AssignedLocation/PointOfCare")),
        "Paced": _safe_text(root.find(".//Patient/Paced")),
    }

    waveform_data = []
    for snapshot in root.findall(".//WaveformSnapshot"):
        trigger = snapshot.find("TriggerEvent")
        trigger = trigger.text if trigger is not None else None

        for waveform in snapshot.findall(".//Waveform"):
            waveform_type = waveform.attrib.get("Type", None)
            waveform_unit = waveform.attrib.get("Units", None)

            for segment in waveform.findall("WaveformSegment"):
                time = segment.attrib.get("Time", None)

                sample_rate_elem = segment.find("SampleRate")
                sample_rate = sample_rate_elem.text if sample_rate_elem is not None else None

                # Missing or empty: values stay unscaled; database_options can convert them.
                resolution_text = (_safe_text(segment.find("DataResolution")) or "").strip()
                resolution = float(resolution_text) if resolution_text else 1.0

                data_elem = segment.find("Data")
                data = data_elem.text.split(",") if data_elem is not None and data_elem.text else []

                for sample_index, value in enumerate(data):
                    try:
                        numeric_value = float(value.strip()) * resolution
                    except (ValueError, AttributeError):
                        numeric_value = None

                    waveform_data.append(
                        {
                            "TriggerEvent": trigger,
                            "WaveformType": waveform_type,
                            "WaveformUnit": waveform_unit,
                            "Time": time,
                            "SampleRate": sample_rate,
                            "DataResolution": resolution,
                            "SampleIndex": sample_index,
                            "Value": numeric_value,
                        }
                    )

    df_waveform = pd.DataFrame(waveform_data)
    df_patient = pd.DataFrame([patient])

    return df_waveform, df_patient


def _format_xml_waveform_data(df_waveform: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse the long-form XML frame into a single value column, indexed per sample.

    Sample time is the segment Time plus SampleIndex / SampleRate. Raises if the file
    carries more than one waveform type or unit.
    """
    df = df_waveform.copy()

    df["SampleRate"] = df["SampleRate"].astype(int)
    df["SampleIndex"] = df["SampleIndex"].astype(int)
    df["Time"] = pd.to_datetime(df["Time"])

    time_offset = df["SampleIndex"] / df["SampleRate"]
    df["Time"] = df["Time"] + pd.to_timedelta(time_offset, unit="s")

    waveform_type_value_counts = df["WaveformType"].value_counts()
    waveform_unit_value_counts = df["WaveformUnit"].value_counts()

    if len(waveform_type_value_counts) > 1 or len(waveform_unit_value_counts) > 1:
        msg = "Unit and value type should be unique in xml file"
        raise ValueError(msg)

    waveform_unit = waveform_unit_value_counts.index[0]
    waveform_type = waveform_type_value_counts.index[0]

    return pd.DataFrame(
        {f"{waveform_type}({waveform_unit})": df["Value"].to_numpy()}, index=df["Time"]
    )


def _read_csv_recording(file_path: Path) -> pd.DataFrame:
    """
    Read one tz-naive .csv recording.

    Each row is one second: a start time, then samples spread evenly across that second.
    """
    name = _get_name_time_series(file_path)
    data = pd.read_csv(file_path, delimiter=",", decimal=".", header=None)
    data = _remove_polluted_columns(data)
    time_rows = pd.to_datetime(data.iloc[:, 0])
    signal = data.iloc[:, 1:].to_numpy().flatten()
    samples_per_row = data.shape[1] - 1
    timestamps = []
    for row_start_time in time_rows:
        row_times = np.linspace(
            row_start_time.value,
            (row_start_time + pd.Timedelta(seconds=1)).value,
            samples_per_row,
            endpoint=False,
        )
        timestamps.extend(pd.to_datetime(row_times))
    return pd.DataFrame({name: signal}, index=timestamps)


def _read_xml_recording(file_path: Path) -> pd.DataFrame | None:
    """
    Read one tz-aware .xml recording.

    Returns None when the file parses but holds no waveform samples.
    """
    df_waveform, _df_patient = _load_xml(file_path)
    if df_waveform.empty:
        return None
    return _format_xml_waveform_data(df_waveform)


def _read_recording(file_path: Path) -> pd.DataFrame | None:
    """Read one recording, dispatching on its extension."""
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_recording(file_path)
    if suffix == ".xml":
        return _read_xml_recording(file_path)
    msg = f"Unsupported extension: '{file_path.suffix}'"
    raise NotImplementedError(msg)


def _reject_mixed_timezone_awareness(df_list: list[pd.DataFrame], file_names: list[str]) -> None:
    """
    Raise when *df_list* mixes tz-naive (.csv) and tz-aware (.xml) frames.

    Without this check the mix reaches pd.concat and fails there instead, with a
    pandas message naming neither offending file.
    """
    awareness = [
        (name, getattr(df.index, "tz", None) is not None)
        for name, df in zip(file_names, df_list, strict=True)
    ]
    naive = [name for name, is_aware in awareness if not is_aware]
    aware = [name for name, is_aware in awareness if is_aware]
    if naive and aware:
        msg = (
            f"Mixed timezone awareness in one mindray_scope folder: {naive[0]!r} is tz-naive "
            f"while {aware[0]!r} carries a UTC offset ({len(naive)} naive, {len(aware)} aware). "
            "Keep .csv and .xml recordings in separate patient folders."
        )
        raise ValueError(msg)


class MindRayScopeDataSource(DataSourceBase):
    """MindRay scope datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path_list: list[Path]) -> pd.DataFrame:
        optimize_storage_dtypes = True
        recordings = read_each(file_path_list, _read_recording, cls.DATASOURCE_NAME)
        df_list = [df_local for _path, df_local in recordings]
        loaded_file_names = [path.name for path, _df_local in recordings]

        _reject_mixed_timezone_awareness(df_list, loaded_file_names)

        # concat(axis=1) aligns by label and the merged frame is sorted below, so a
        # per-frame pre-sort here is wasted copies.
        df = pd.concat(df_list, axis=1)
        df = deduplicate_then_sort_index(df)
        if optimize_storage_dtypes:
            df = _optimize_df_types(df)

        return df
