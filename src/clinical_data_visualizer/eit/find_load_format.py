import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.eit.options as options_naming
from clinical_data_visualizer import helper
from clinical_data_visualizer.datasource_base import DataSourceBase

logger = logging.getLogger(__name__)

# Safety check
if options_naming.KEYWORD_FILE_EXTENSION in options_naming.FILE_NAME_DATAFRAME_LOADED:
    msg = (
        f"'KEYWORD_FILE_EXTENSION'({options_naming.KEYWORD_FILE_EXTENSION}) is in "
        f"'FILE_NAME_DATAFRAME_LOADED'({options_naming.FILE_NAME_DATAFRAME_LOADED}). "
        "This dangerous since we might override the raw data, or read the wrong one"
    )
    raise ValueError(msg)


def _add_index_timestamp_to_eit_dataframe(
    df: pd.DataFrame,
    timezone: str | None = None,
    day: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Adds a timestamp index to an eit dataframe based on the 'time' column (fraction of day)."""
    df = df.reset_index()
    if options_naming.Time_column_label not in df.columns:
        msg = f"DataFrame must contain a '{options_naming.Time_column_label}' column."
        raise ValueError(msg)

    if day is not None:
        base_day = pd.Timestamp(day).normalize()
    else:
        msg = (
            "EIT day not provided and could not be inferred from datetime_start. "
            "Skipping EIT datasource."
        )
        raise ValueError(msg)

    df = df.copy()
    df.index = base_day + pd.to_timedelta(df[options_naming.Time_column_label], unit="D")
    if df.index.tz is None:
        if timezone is not None:
            df.index = df.index.tz_localize(timezone)
        else:
            msg = (
                "'day.tz' and 'timezone' can't be None at the same time, otherwise we can't "
                "assign time zone to dataframe"
            )
            raise ValueError(msg)
    return df[~df.index.duplicated(keep="first")]


def _parse_asc_selected_columns(
    lines: list[str], selected_cols: list[str] | None = None
) -> pd.DataFrame:
    """Parses only selected columns from a large ASC dataframe (line-by-line)."""
    header_line = lines[0].strip()
    all_columns = [x.replace("+", "").replace(",", ".").strip() for x in header_line.split("\t")]

    if selected_cols is None:
        col_indices = list(range(len(all_columns)))
        selected_cols = all_columns[:]
    else:
        resolved_cols = []
        for pattern in selected_cols:
            col = helper.get_column_name_from_pattern(all_columns, pattern)
            if col is not None:
                resolved_cols.append(col)

        index_map = {col: i for i, col in enumerate(all_columns)}
        selected_cols = [c for c in resolved_cols if c in index_map]
        col_indices = [index_map[c] for c in selected_cols]

    rows = []
    for raw_line in lines[1:]:
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        values = [x.replace("+", "").replace(",", ".").strip() for x in stripped_line.split("\t")]
        if len(values) < len(all_columns):
            values += [None] * (len(all_columns) - len(values))
        rows.append([values[i] for i in col_indices])

    df = pd.DataFrame(rows, columns=selected_cols)
    df[df.columns] = df[df.columns].apply(pd.to_numeric, errors="coerce")
    df = df.set_index(options_naming.Time_column_label)
    df["time_hours"] = pd.to_timedelta(df.index, unit="D")

    return df


def _parse_metadata_lines(lines: list[str]) -> dict:
    """Parse metadata lines from an ASC file into a structured dictionary."""
    metadata = {}
    notes = []

    for raw_line in lines:
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        if ":" in stripped_line:
            key, value = stripped_line.split(":", 1)
            metadata[key.strip()] = value.strip()
        else:
            notes.append(stripped_line)

    for i, note in enumerate(notes, 1):
        metadata[f"Note_{i}"] = note

    return metadata


def _parse_matrix(lines: list[str]) -> np.ndarray:
    """Parse matrix from lines."""
    new_lines = [[float(x.replace(",", ".")) for x in line.split()] for line in lines]
    return np.array(new_lines)


def _parse_eit_asc_file(
    path: str | Path, columns_to_extract: list[str] | None
) -> tuple[dict, np.ndarray, np.ndarray, pd.DataFrame, pd.DataFrame]:
    """Parse a single EIT ASC file."""
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
        for _i, raw_line in enumerate(f):
            stripped_line = raw_line.strip()

            if "Dynamic Image" in stripped_line:
                dynamic_image = True
                tidal_image = False
                tidal_variations_summary = False
                tidal_variations_full = False
                continue
            if "Tidal Image" in stripped_line:
                tidal_image = True
                dynamic_image = False
                tidal_variations_summary = False
                tidal_variations_full = False
                continue
            if stripped_line == "Tidal Variations":
                tidal_variations_summary = True
                dynamic_image = False
                tidal_image = False
                tidal_variations_full = False
                continue
            if not stripped_line and tidal_variations_summary:
                tidal_variations_full = True
                tidal_variations_summary = False
                dynamic_image = False
                tidal_image = False
                continue

            if dynamic_image and stripped_line:
                lines_dynamic_image_matrix.append(stripped_line)
            elif tidal_image and stripped_line:
                lines_tidal_image_matrix.append(stripped_line)
            elif tidal_variations_summary and stripped_line:
                lines_tidal_variation_summary_df.append(stripped_line)
            elif tidal_variations_full and stripped_line:
                lines_tidal_variation_full_df.append(stripped_line)
            else:
                lines_metadata.append(stripped_line)

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
        selected_cols_tidal_variation_full_df,
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
    """Parse multiple EIT ASC files and merge results."""
    all_metadata = []
    all_dynamic_images = []
    all_tidal_images = []
    all_tidal_variation_summary_dfs = []
    all_tidal_variation_full_dfs = []

    for file_path in asc_files:
        metadata, dynamic_img, tidal_img, df_summary, df_full = _parse_eit_asc_file(
            file_path, columns_to_extract
        )
        df_summary["source_file"] = file_path.name
        df_full["source_file"] = file_path.name

        all_metadata.append(metadata)
        all_dynamic_images.append(dynamic_img)
        all_tidal_images.append(tidal_img)
        all_tidal_variation_summary_dfs.append(df_summary)
        all_tidal_variation_full_dfs.append(df_full)

    df_tidal_variation_summary_merged = pd.concat(all_tidal_variation_summary_dfs, axis=0)
    df_tidal_variation_full_merged = pd.concat(all_tidal_variation_full_dfs, axis=0)

    df_tidal_variation_summary_merged = df_tidal_variation_summary_merged.sort_index()
    df_tidal_variation_full_merged = df_tidal_variation_full_merged.sort_index()

    return (
        all_metadata,
        all_dynamic_images,
        all_tidal_images,
        df_tidal_variation_summary_merged,
        df_tidal_variation_full_merged,
    )


def _add_columns_percentage(df: pd.DataFrame, percentage_reference_column: str) -> pd.DataFrame:
    """Add percentage columns relative to a reference column."""
    for column in df.columns:
        if column != percentage_reference_column and is_numeric_dtype(df[column]):
            df[f"%{column}"] = df[column] / df[percentage_reference_column]
    return df


class EITDataSource(DataSourceBase):
    """EIT datasource processor."""

    DATASOURCE_NAME = "eit"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | None:
        return helper.find_file_list(
            folder_path,
            options_naming.KEYWORD_FILE_EXTENSION,
            "eit file",
        )

    @classmethod
    @helper.time_it
    def _load(cls, file_path_list: list[Path], path_output: Path, **kwargs) -> pd.DataFrame:
        database_options_specific = kwargs.get("database_options_specific", {})
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
        cls._save_dataframe(df, path_output)
        return df

    @classmethod
    @helper.time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        patient_options_eit = patient_options.get(cls.DATASOURCE_NAME, {})

        # Create datetime index with the right timezone
        timezone = database_options_specific.get(
            cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
        ).get(
            options_naming.DatabaseOptionsAdditionalInformations.TIMEZONE,
            options_naming.DATA_SOURCE_DEFAULT_TIMEZONE,
        )

        day_str = patient_options_eit.get(options_naming.PatientOptionsDataSourceRelative.Day.NAME)
        if not day_str:
            day_str = patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
            if day_str:
                logger.info("EIT day not provided, inferring from datetime_start: %s", day_str)
        day = pd.Timestamp(day_str) if day_str else None
        df = _add_index_timestamp_to_eit_dataframe(df, day=day, timezone=timezone)

        # Apply time-shift
        df = cls._apply_time_shift(df, patient_options)

        # Filter by datetime (filter_date=False for EIT)
        df = cls._filter_by_datetime(df, patient_options, filter_date=False)

        # Add percentage columns if configured
        reference_percentage_column = database_options_specific.get(
            cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
        ).get(options_naming.DatabaseOptionsAdditionalInformations.PERCENTAGE_REF_COLUMN)
        if reference_percentage_column is not None:
            df = _add_columns_percentage(df, reference_percentage_column)

        return df


# Module-level main function for backward compatibility
def main(patient_options: dict, database_options_specific: dict | None) -> pd.DataFrame:
    return EITDataSource.main(patient_options, database_options_specific)
