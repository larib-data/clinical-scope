import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from defusedxml.ElementTree import parse as parse_xml

import clinical_data_visualizer.mindray_scope.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)


def _optimize_df_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame types using pandas nullable dtypes.

    Integer columns -> nullable integer dtypes (Int8, Int16, UInt8, etc.)
    Float columns -> downcast to float32 if possible
    Works with NaNs (missing values).
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


def _is_float(x: Any) -> bool:
    """Check if x is a valid float."""
    try:
        float(x)
    except (ValueError, TypeError):
        return False
    else:
        return True


def _remove_polluted_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove polluted columns where at least one cell contains non-numeric data."""
    good_cols = [0]  # Keep timestamp column

    for col in df.columns[1:]:
        series = df[col].astype(str)
        numeric_mask = series.apply(_is_float)
        pattern_mask = series.str.contains(
            r"SampleRate:|TimeStamp\(|Beep_Pulse|HeartBeat_", regex=True, na=False
        )
        if numeric_mask.all() and not pattern_mask.any():
            good_cols.append(col)

    return df[good_cols]


def _load_xml(path_xml: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load and parse XML file containing waveform data.

    Args:
        path_xml: Path to the XML file

    Returns:
        Tuple of (df_waveform, df_patient)

    """
    tree = parse_xml(path_xml)
    root = tree.getroot()

    # Extract patient info (elements may be absent in some file variants)
    def _safe_text(elem: Any) -> str | None:
        return elem.text if elem is not None else None

    patient = {
        "Gender": _safe_text(root.find(".//Patient/Demographics/Gender")),
        "Bed": _safe_text(root.find(".//Patient/AssignedLocation/Bed")),
        "PointOfCare": _safe_text(root.find(".//Patient/AssignedLocation/PointOfCare")),
        "Paced": _safe_text(root.find(".//Patient/Paced")),
    }

    # Extract waveform data
    waveform_data = []
    for snapshot in root.findall(".//WaveformSnapshot"):
        trigger = snapshot.find("TriggerEvent")
        trigger = trigger.text if trigger is not None else None

        for waveform in snapshot.findall(".//Waveform"):
            wf_type = waveform.attrib.get("Type", None)
            wf_unit = waveform.attrib.get("Units", None)

            for segment in waveform.findall("WaveformSegment"):
                time = segment.attrib.get("Time", None)

                sample_rate_elem = segment.find("SampleRate")
                sample_rate = sample_rate_elem.text if sample_rate_elem is not None else None

                resolution_elem = segment.find("DataResolution")
                resolution = float(resolution_elem.text) if resolution_elem is not None else 1.0

                data_elem = segment.find("Data")
                data = data_elem.text.split(",") if data_elem is not None and data_elem.text else []

                for i, value in enumerate(data):
                    try:
                        # Convert value to float and apply resolution
                        numeric_value = float(value.strip()) * resolution
                    except (ValueError, AttributeError):
                        # If conversion fails, store None or the raw value
                        numeric_value = None

                    waveform_data.append(
                        {
                            "TriggerEvent": trigger,
                            "WaveformType": wf_type,
                            "WaveformUnit": wf_unit,
                            "Time": time,
                            "SampleRate": sample_rate,
                            "DataResolution": resolution,
                            "SampleIndex": i,
                            "Value": numeric_value,
                        }
                    )

    # Convert to DataFrames
    df_waveform = pd.DataFrame(waveform_data)
    df_patient = pd.DataFrame([patient])

    return df_waveform, df_patient


def _format_xml_waveform_data(df_waveform: pd.DataFrame) -> pd.DataFrame:
    """
    Format waveform data with proper dtypes and precise timestamps.

    Args:
        df_waveform: Raw waveform DataFrame

    Returns:
        Formatted DataFrame with precise timestamps

    """
    df = df_waveform.copy()

    # Convert to correct dtypes
    df["SampleRate"] = df["SampleRate"].astype(int)
    df["SampleIndex"] = df["SampleIndex"].astype(int)
    df["Time"] = pd.to_datetime(df["Time"])

    # Calculate precise timestamp based on sample index and rate
    time_offset = df["SampleIndex"] / df["SampleRate"]
    df["Time"] = df["Time"] + pd.to_timedelta(time_offset, unit="s")

    waveform_type_value_counts = df["WaveformType"].value_counts()
    waveform_unit_value_counts = df["WaveformUnit"].value_counts()

    if len(waveform_type_value_counts) > 1 or len(waveform_unit_value_counts) > 1:
        msg = "Unit and value type should be unique in xml file"
        raise ValueError(msg)

    wf_unit = waveform_unit_value_counts.index[0]
    wf_type = waveform_type_value_counts.index[0]

    return pd.DataFrame({f"{wf_type}({wf_unit})": df["Value"].to_numpy()}, index=df["Time"])


class MindRayScopeDataSource(DataSourceBase):
    """MindRay scope datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @helper.time_it
    def _load(
        cls, file_path_list: list[Path], path_output: Path | None, **kwargs: Any
    ) -> pd.DataFrame:
        database_options_specific = kwargs.get("database_options_specific", {})
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

        # Use deduplicated file list
        file_path_list = list(file_dict.values())
        logger.debug("After deduplication: %d files to process", len(file_path_list))

        optimize_storage_dtypes = True
        df_list = []

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
                for t in time_rows:
                    row_times = np.linspace(
                        t.value,
                        (t + pd.Timedelta(seconds=1)).value,
                        samples_per_row,
                        endpoint=False,
                    )
                    timestamps.extend(pd.to_datetime(row_times))
                df_local = pd.DataFrame({name: signal}, index=timestamps)
                df_local = helper.apply_timezone_to_dataframe(
                    df_local,
                    database_options_specific,
                    options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
                    options_naming,
                )

                df_list.append(df_local)

            elif file_path.suffix == ".xml":
                # .xml seems tz aware
                df_waveform, _df_patient = _load_xml(file_path)
                df_local = _format_xml_waveform_data(df_waveform)

                df_list.append(df_local)

        df_list = [df.sort_index() for df in df_list]
        df = pd.concat(df_list, axis=1)
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        if optimize_storage_dtypes:
            df = _optimize_df_types(df)

        if path_output is not None:
            cls._save_dataframe(df, path_output)
        return df
