from pathlib import Path

import pandas as pd

from clinical_data_visualizer import utilities as utl


# ==================================================================================================
def read_waves_data(
    path: str | Path,
    delimiter=None,
    decimal='.'
) -> pd.DataFrame:

    path = Path(path)

    if path.name.endswith("parquet"):
        data_df = pd.read_parquet(path)

    elif path.name.endswith("csv"):

        data_df = pd.read_csv(
            path,
            sep=delimiter,
            engine="python",
            decimal=decimal,
            encoding='utf-8',
            encoding_errors='ignore',
        ) # no dtype specify, to use pandas guessing capabilities

    else:
        raise ValueError("invalid data_type -> 'csv' and 'parquet' are the allowed values.")

    return data_df

# ==================================================================================================
def filter_dataframe_by_time(
    data: pd.DataFrame, time_start: object, time_end: object
) -> pd.DataFrame:
    """Filter DataFrame based on the provided time_start and time_end."""
    if time_start is not None:
        if utl.is_timestamp(time_start):
            time_start = utl.convert_to_timestamp(time_start)
            data = data[data.index >= time_start]
        elif utl.is_numeric(time_start):
            time_start = utl.convert_to_numeric(time_start)
            data = data[data["time"] >= time_start]

    if time_end is not None:
        if utl.is_timestamp(time_end):
            time_end = utl.convert_to_timestamp(time_end)
            data = data[data.index <= time_end]
        elif utl.is_numeric(time_end):
            time_end = utl.convert_to_numeric(time_end)
            data = data[data["time"] <= time_end]

    return data
