import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
import clinical_data_visualizer.eit.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# ==================================================================================================
keyword_extension = options_naming.KEYWORD_FILE_EXTENSION
folder_name_visu = cst.FOLDER_NAME_VISU
file_name_df_loaded = options_naming.FILE_NAME_DATAFRAME_LOADED

if keyword_extension in file_name_df_loaded:
    raise ValueError(
        f"'KEYWORD_FILE_EXTENSION'({keyword_extension}) is in "
        f"'FILE_NAME_DATAFRAME_LOADED'({file_name_df_loaded}). "
        "This dangerous since we might override the raw data, or read the wrong one"
    )


# ==================================================================================================
def _find(folder_path: Path) -> list[Path] | None:
    eit_files = helper.find_file_list(
        folder_path,
        keyword_extension,
        "eit file",
    )

    return eit_files


# ==================================================================================================
# Loading functions
def _add_index_timestamp_to_eit_dataframe(
    df: pd.DataFrame,
    timezone: str | None = None,
    day: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Adds a timestamp index to an eit dataframe based on the 'time' column (fraction of day).

    Args:
        df: DataFrame with a column 'time' as float fraction of the day (0.0-1.0).
        day: Optional datetime specifying the day to use for the index.
             If None, defaults to 2000-01-01.

    Returns:
        DataFrame with datetime index based on 'time' column.
    """
    df = df.reset_index()  # In case 'Time' is already the index, or we want to keep the index
    if options_naming.Time_column_label not in df.columns:
        raise ValueError(f"DataFrame must contain a '{options_naming.Time_column_label}' column.")

    if day is not None:
        base_day = pd.Timestamp(day).normalize()  # sets hour, minute, second to 0
    else:
        logger.warning("Loading EIT data without giving a day is highly discouraged")
        base_day = pd.Timestamp("2000-01-01")

    # Convert fraction-of-day to timedelta
    df = df.copy()
    df.index = base_day + pd.to_timedelta(df[options_naming.Time_column_label], unit="D")
    if df.index.tz is None:
        if timezone is not None:
            df.index = df.index.tz_localize(timezone)
        else:
            raise ValueError(
                "'day.tz' and 'timezone' can't be None at the same time, otherwise we can't "
                "assign time zone to dataframe"
            )
    df = df[~df.index.duplicated(keep="first")]  # Remove duplicated index

    return df


# ==================================================================================================
def _parse_asc_selected_columns(lines: list[str], selected_cols=None) -> pd.DataFrame:
    """
    Parses only selected columns from a large ASC dataframe (line-by-line).

    Args:
        lines: list of strings (lines from Tidal Variations to EOF)
        selected_cols: list of column names to keep (must match header names)

    Returns:
        pandas.DataFrame with selected columns
    """
    header_line = lines[0].strip()
    all_columns = [x.replace("+", "").replace(",", ".").strip() for x in header_line.split("\t")]

    if selected_cols is None:
        # Keep all columns → indices 0..len(all_columns)-1
        col_indices = list(range(len(all_columns)))
        selected_cols = all_columns[:]  # also set the column names
    else:
        # Resolve patterns to actual column names
        resolved_cols = []
        for pattern in selected_cols:
            col = helper.get_column_name_from_pattern(all_columns, pattern)
            if col is not None:
                resolved_cols.append(col)

        index_map = {col: i for i, col in enumerate(all_columns)}
        selected_cols = [c for c in resolved_cols if c in index_map]
        col_indices = [index_map[c] for c in selected_cols]

    rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        values = [x.replace("+", "").replace(",", ".").strip() for x in line.split("\t")]
        # Pad row if too short
        if len(values) < len(all_columns):
            values += [None] * (len(all_columns) - len(values))
        # Keep only selected columns
        rows.append([values[i] for i in col_indices])

    df = pd.DataFrame(rows, columns=selected_cols)
    df[df.columns] = df[df.columns].apply(pd.to_numeric, errors="coerce")
    df = df.set_index(options_naming.Time_column_label)

    df["time_hours"] = pd.to_timedelta(df.index, unit="D")

    return df


# ==================================================================================================
def _parse_metadata_lines(lines: list[str]) -> dict:
    """
    Parse metadata lines from an ASC file into a structured dictionary.

    Args:
        lines (list of str): raw metadata lines

    Returns:
        dict: metadata with keys from lines containing ':', plus a 'notes' list for unstructured
                lines
    """
    metadata = {}
    notes = []

    for line in lines:
        line = line.strip()
        if not line:
            continue  # skip empty lines

        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
        else:
            notes.append(line)

    # Optionally, add notes as numbered entries
    for i, note in enumerate(notes, 1):
        metadata[f"Note_{i}"] = note

    return metadata


# ==================================================================================================
def _parse_matrix(lines: list[str]) -> np.ndarray:
    new_lines = [[float(x.replace(",", ".")) for x in line.split()] for line in lines]
    matrix = np.array(new_lines)

    return matrix


# ==================================================================================================
def _parse_eit_asc_file(
    path: str | Path, columns_to_extract: list[str] | None
) -> tuple[dict, np.ndarray, np.ndarray, pd.DataFrame, pd.DataFrame]:
    lines_metadata = []
    dynamic_image = False
    lines_dynamic_image_matrix = []
    tidal_image = False
    lines_tidal_image_matrix = []
    tidal_variations_summary = False
    lines_tidal_variation_summary_df = []
    tidal_variations_full = False
    lines_tidal_variation_full_df = []

    with Path.open(Path(path), "r", encoding="latin-1") as f:
        for _i, line in enumerate(f):
            line = line.strip()

            if "Dynamic Image" in line:
                dynamic_image = True

                tidal_image = False
                tidal_variations_summary = False
                tidal_variations_full = False
                continue

            elif "Tidal Image" in line:
                tidal_image = True

                dynamic_image = False
                tidal_variations_summary = False
                tidal_variations_full = False
                continue

            elif line == "Tidal Variations":
                tidal_variations_summary = True

                dynamic_image = False
                tidal_image = False
                tidal_variations_full = False
                continue

            elif not line and tidal_variations_summary:
                tidal_variations_full = True

                tidal_variations_summary = False
                dynamic_image = False
                tidal_image = False
                continue

            if dynamic_image and line:
                lines_dynamic_image_matrix.append(line)
            elif tidal_image and line:
                lines_tidal_image_matrix.append(line)
            elif tidal_variations_summary and line:
                lines_tidal_variation_summary_df.append(line)
            elif tidal_variations_full and line:
                lines_tidal_variation_full_df.append(line)
            else:
                lines_metadata.append(line)

    df_tidal_variation_summary_df = _parse_asc_selected_columns(lines_tidal_variation_summary_df)

    if columns_to_extract:
        selected_cols_tidal_variation_full_df = [
            options_naming.Time_column_label,
            *columns_to_extract,
        ]
    else:
        selected_cols_tidal_variation_full_df = None

    df_tidal_variation_full_df = _parse_asc_selected_columns(
        lines_tidal_variation_full_df,
        selected_cols_tidal_variation_full_df,  # Allows to divide by 4 the final python object, definitely helpfull  # noqa: E501
    )

    metadata = _parse_metadata_lines(lines_metadata)
    dynamic_image_matrix = _parse_matrix(lines_dynamic_image_matrix)
    tidal_image_matrix = _parse_matrix(lines_tidal_image_matrix)

    return (
        metadata,
        dynamic_image_matrix,
        tidal_image_matrix,
        df_tidal_variation_summary_df,
        df_tidal_variation_full_df,
    )


# ==================================================================================================
@helper.time_it
def _parse_eit_asc_file_list(
    asc_files: list[Path], columns_to_extract: list[str] | None
) -> tuple[
    list[dict],
    list[np.ndarray],
    list[np.ndarray],
    pd.DataFrame,
    pd.DataFrame,
]:
    """

    Returns:
        - List of metadata dicts (one per file)
        - List of dynamic_image matrices
        - List of tidal_image matrices
        - One merged tidal_variation_summary dataframe
        - One merged tidal_variation_full dataframe
    """

    all_metadata = []
    all_dynamic_images = []
    all_tidal_images = []
    all_tidal_variation_summary_dfs = []
    all_tidal_variation_full_dfs = []

    for file_path in asc_files:
        metadata, dynamic_img, tidal_img, df_summary, df_full = _parse_eit_asc_file(
            file_path, columns_to_extract
        )

        # Store file name in each DataFrame
        df_summary["source_file"] = file_path.name
        df_full["source_file"] = file_path.name

        all_metadata.append(metadata)
        all_dynamic_images.append(dynamic_img)
        all_tidal_images.append(tidal_img)
        all_tidal_variation_summary_dfs.append(df_summary)
        all_tidal_variation_full_dfs.append(df_full)

    # Merge everything
    df_tidal_variation_summary_merged = pd.concat(all_tidal_variation_summary_dfs, axis=0)
    df_tidal_variation_full_merged = pd.concat(all_tidal_variation_full_dfs, axis=0)

    # Sort by index in case of file not being in the right order
    df_tidal_variation_summary_merged = df_tidal_variation_summary_merged.sort_index()
    df_tidal_variation_full_merged = df_tidal_variation_full_merged.sort_index()

    return (
        all_metadata,
        all_dynamic_images,
        all_tidal_images,
        df_tidal_variation_summary_merged,
        df_tidal_variation_full_merged,
    )


# ==================================================================================================
@helper.time_it
def _load(
    file_path_list: list[Path], path_output: Path, database_options_specific: dict
) -> pd.DataFrame:
    (
        _list_metadata,
        _list_dynamic_images,
        _list_tidal_images,
        _df_tidal_variation_summary,
        df,
    ) = _parse_eit_asc_file_list(
        file_path_list, database_options_specific.get(cst.DatabaseOptions.FIELD_DISPLAY)
    )

    df = df[~df.index.duplicated(keep="first")]

    try:
        Path(path_output).parent.mkdir(parents=False, exist_ok=True)
        df.to_parquet(path_output)
    except Exception:
        logger.exception("Could not save the dataframe for future quick-reloading:")

    return df


# ==================================================================================================
def _quick_load(path_dataframe: Path) -> pd.DataFrame:
    df = pd.read_parquet(path_dataframe)
    return df


# ==================================================================================================
def _add_columns_percentage(df: pd.DataFrame, percentage_reference_column: str) -> pd.DataFrame:
    for column in df.columns:
        if column != percentage_reference_column and is_numeric_dtype(df[column]):
            df[f"%{column}"] = df[column] / df[percentage_reference_column]

    return df


# ==================================================================================================
@helper.time_it
def _format(
    df: pd.DataFrame, patient_options: dict, database_options_specific: dict
) -> pd.DataFrame:
    patient_options_eit = patient_options.get(datasource.DataSource.EIT.NAME, {})
    # Create datetime index col with the right timezone
    timezone = database_options_specific.get(cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}).get(
        options_naming.DatabaseOptionsAdditionalInformations.TIMEZONE,
        options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
    )

    day_str = patient_options_eit.get(options_naming.PatientOptionsDataSourceRelative.Day.NAME)
    day = pd.Timestamp(day_str) if day_str else None
    df = _add_index_timestamp_to_eit_dataframe(df, day=day, timezone=timezone)

    # Apply time-shift
    time_shift_second = patient_options_eit.get(
        options_naming.PatientOptionsDataSourceRelative.TimeShift.NAME, 0.0
    )
    helper.shift_data_by_seconds(df, time_shift_second)

    # Filter by datetime start and end
    datetime_start = patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
    datetime_end = patient_options.get(cst.PatientOptions.DatetimeEnd.NAME)
    datetime_start = pd.Timestamp(datetime_start) if datetime_start else None
    datetime_end = pd.Timestamp(datetime_end) if datetime_end else None
    df = helper.filter_data_by_timestamps(
        df, time_start=datetime_start, time_end=datetime_end, filter_date=False
    )

    reference_percentage_column = database_options_specific.get(
        cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
    ).get(options_naming.DatabaseOptionsAdditionalInformations.PERCENTAGE_REF_COLUMN)
    if reference_percentage_column is not None:
        df = _add_columns_percentage(df, reference_percentage_column)

    return df


# ==================================================================================================
@helper.time_it
def _extract_signals(
    df: pd.DataFrame, patient_options: dict, database_options_specific: dict
) -> list[Signal]:
    list_signals = database_options_specific.get(
        cst.DatabaseOptions.FIELD_DISPLAY, list(df.columns)
    )

    # Time-series
    list_signal_container = []
    for signal in list_signals:
        try:
            list_signal_container.append(
                Signal.time_series_from_dataframe(
                    df=df,
                    raw_signal_name=signal,
                    patient_options=patient_options,
                    database_options_specific=database_options_specific,
                )
            )
        except Exception:  # noqa: PERF203
            logger.exception("❌ Could not process the signal '%s' as Signal object", signal)

    return list_signal_container


# ==================================================================================================
@helper.time_it
def main(
    patient_options: dict,
    database_options_specific: dict | None,
) -> list[Signal]:
    database_options_eit = (
        database_options_specific if database_options_specific is not None else {}
    )

    patient_options_eit = patient_options.get(datasource.DataSource.EIT.NAME, {})

    folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
    dataframe_path = folder_path / folder_name_visu / file_name_df_loaded

    if patient_options.get(cst.PatientOptions.QuickLoad.NAME, False) and dataframe_path.is_file():
        df = _quick_load(dataframe_path)
    else:
        file_path = _find(folder_path)
        if file_path is None:
            return []
        df = _load(file_path, dataframe_path, database_options_eit)

    df = _format(df, patient_options, database_options_eit)

    list_signal_container = _extract_signals(df, patient_options_eit, database_options_eit)

    return list_signal_container
