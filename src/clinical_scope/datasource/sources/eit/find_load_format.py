import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

import clinical_scope.constants as cst
import clinical_scope.datasource.sources.eit.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.time_axis import deduplicate_then_sort_index

logger = logging.getLogger(__name__)


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


def _parse_asc_table(lines: list[str]) -> pd.DataFrame:
    """Parses a large tab-separated ASC table (line-by-line)."""
    header_line = lines[0].strip()
    all_columns = [
        token.replace("+", "").replace(",", ".").strip() for token in header_line.split("\t")
    ]

    rows = []
    for raw_line in lines[1:]:
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        values = [
            token.replace("+", "").replace(",", ".").strip() for token in stripped_line.split("\t")
        ]
        if len(values) < len(all_columns):
            values += [None] * (len(all_columns) - len(values))
        rows.append(values[: len(all_columns)])

    df = pd.DataFrame(rows, columns=all_columns)
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

    for note_index, note in enumerate(notes, 1):
        metadata[f"Note_{note_index}"] = note

    return metadata


def _parse_matrix(lines: list[str]) -> np.ndarray:
    """Parse matrix from lines."""
    new_lines = [[float(token.replace(",", ".")) for token in line.split()] for line in lines]
    return np.array(new_lines)


def _parse_eit_asc_file(
    path: str | Path,
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

    with Path.open(Path(path), "r", encoding="latin-1") as file:
        for _i, raw_line in enumerate(file):
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

    df_tidal_variation_summary_df = _parse_asc_table(lines_tidal_variation_summary_df)
    df_tidal_variation_full_df = _parse_asc_table(lines_tidal_variation_full_df)

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


@time_it
def _parse_eit_asc_file_list(
    asc_files: list[Path],
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
        metadata, dynamic_image, tidal_image, df_summary, df_full = _parse_eit_asc_file(file_path)
        df_summary["source_file"] = file_path.name
        df_full["source_file"] = file_path.name

        all_metadata.append(metadata)
        all_dynamic_images.append(dynamic_image)
        all_tidal_images.append(tidal_image)
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


def _add_columns_percentage_for_eit(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add percentage columns for EIT local* columns relative to global column.

    A ratio of two parsed columns resolves no option, so deriving it belongs to the
    transcription: ``_load`` calls this so the ratios reach the parquet cache, where
    ``field_display`` can select them. Returns *df* unchanged when there is no global
    column to divide by.
    """
    global_label = options_naming.Global_column_label.lower()
    local_prefix = options_naming.prefix_local.lower()
    try:
        global_column = next(
            (column for column in df.columns if column.lower() == global_label), None
        )
        if global_column is None:
            logger.debug(
                "No '%s' column found in EIT data - skipping percentage calculation",
                options_naming.Global_column_label,
            )
            return df

        local_columns = [column for column in df.columns if column.lower().startswith(local_prefix)]

        if not local_columns:
            logger.debug(
                "No columns starting with '%s' found in EIT data", options_naming.prefix_local
            )
            return df

        for local_column in local_columns:
            if is_numeric_dtype(df[local_column]):
                percentage_column = f"{options_naming.prefix_percentage}{local_column}"
                if percentage_column not in df.columns:
                    try:
                        df[percentage_column] = df[local_column] / df[global_column]
                        logger.debug(
                            "Created percentage column %s = %s / %s",
                            percentage_column,
                            local_column,
                            global_column,
                        )
                    except Exception:
                        logger.exception("Failed to create percentage column %s", percentage_column)
                else:
                    logger.debug("Percentage column %s already exists, skipping", percentage_column)
            else:
                logger.debug(
                    "Column %s is not numeric, skipping percentage calculation", local_column
                )

    except Exception:
        logger.exception("Error in EIT percentage calculation")

    return df


class EITDataSource(DataSourceBase):
    """EIT datasource processor."""

    OPTIONS_MODULE = options_naming

    @classmethod
    @time_it
    def _load(cls, file_path_list: list[Path]) -> pd.DataFrame:
        (
            _list_metadata,
            _list_dynamic_images,
            _list_tidal_images,
            _df_tidal_variation_summary,
            df,
        ) = _parse_eit_asc_file_list(file_path_list)

        df = deduplicate_then_sort_index(df)
        return _add_columns_percentage_for_eit(df)

    @classmethod
    @time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        patient_options_eit = patient_options.get(cls.DATASOURCE_NAME, {})

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
        # datetime_start may be tz-aware; strip the offset so "day" stays the typed calendar
        # day, which the branch below localizes into the device's own timezone.
        day = pd.Timestamp(day_str).tz_localize(None) if day_str else None
        df = _add_index_timestamp_to_eit_dataframe(df, day=day, timezone=timezone)

        df = cls._apply_time_shift(df, patient_options)
        return cls._filter_by_datetime(df, patient_options, filter_date=False)
