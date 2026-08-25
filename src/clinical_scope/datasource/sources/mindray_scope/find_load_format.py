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
from clinical_scope.io.file_utils import deduplicate_then_sort_index

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
    """Check if value is a valid float."""
    try:
        float(value)
    except (ValueError, TypeError):
        return False
    else:
        return True


def _remove_polluted_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove polluted columns where at least one cell contains non-numeric data."""
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

    # Extract patient info (elements may be absent in some file variants)
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

                resolution_elem = segment.find("DataResolution")
                resolution = float(resolution_elem.text) if resolution_elem is not None else 1.0

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
    """Format waveform data with proper dtypes and precise timestamps."""
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
        extension_preference = options_naming.FILE_EXTENSIONS

        file_dict = {}
        for file_path in file_path_list:
            base_name = file_path.stem
            current_ext = file_path.suffix.lower()

            if base_name not in file_dict:
                file_dict[base_name] = file_path
            else:
                # Compare extensions by preference order
                existing_ext = file_dict[base_name].suffix.lower()

                try:
                    current_priority = extension_preference.index(current_ext)
                except ValueError:
                    current_priority = len(extension_preference)

                try:
                    existing_priority = extension_preference.index(existing_ext)
                except ValueError:
                    existing_priority = len(extension_preference)

                # Keep file with higher priority (lower index)
                if current_priority < existing_priority:
                    logger.debug(
                        "Replacing '%s' with '%s' (higher priority extension)",
                        file_dict[base_name].name,
                        file_path.name,
                    )
                    file_dict[base_name] = file_path

        file_path_list = list(file_dict.values())
        logger.debug("After deduplication: %d files to process", len(file_path_list))

        optimize_storage_dtypes = True
        df_list = []
        loaded_file_names = []

        for file_path in file_path_list:
            if file_path.suffix == ".csv":
                # .csv are tz naive
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
                df_local = pd.DataFrame({name: signal}, index=timestamps)

                df_list.append(df_local)
                loaded_file_names.append(file_path.name)

            elif file_path.suffix == ".xml":
                # .xml seems tz aware
                df_waveform, _df_patient = _load_xml(file_path)
                df_local = _format_xml_waveform_data(df_waveform)

                df_list.append(df_local)
                loaded_file_names.append(file_path.name)

        _reject_mixed_timezone_awareness(df_list, loaded_file_names)

        # concat(axis=1) aligns by label and the merged frame is sorted below, so a
        # per-frame pre-sort here is wasted copies.
        df = pd.concat(df_list, axis=1)
        df = deduplicate_then_sort_index(df)
        if optimize_storage_dtypes:
            df = _optimize_df_types(df)

        return df
