import csv
import logging
import random
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.colors
import plotly.graph_objects as go

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def is_timestamp(value: object) -> bool:
    """Check if the value is a pandas Timestamp or can be converted to one."""
    return isinstance(value, (pd.Timestamp, np.datetime64)) or (
        isinstance(value, str) and is_convertible_to_timestamp(value)
    )


# ==================================================================================================
def is_convertible_to_timestamp(value: str) -> bool:
    """Check if a string can be converted to a pandas Timestamp."""
    if not is_numeric(value):
        try:
            pd.Timestamp(value)
            return True
        except Exception:
            return False
    return False


# ==================================================================================================
def is_numeric(value: object) -> bool:
    """Check if the value is a numeric type (int, float, or convertible)."""
    return isinstance(value, (int, float, np.number)) or (
        isinstance(value, str) and value.replace(".", "", 1).isdigit()
    )


# ==================================================================================================
def convert_to_timestamp(value: object) -> pd.Timestamp | None:
    """Convert a valid timestamp input to a pandas Timestamp."""
    if isinstance(value, (pd.Timestamp, np.datetime64, str)):
        return pd.Timestamp(value)
    return None


# ==================================================================================================
def convert_to_numeric(value: object) -> float | None:
    """Convert a valid numeric input to a float."""
    try:
        return float(value)
    except ValueError:
        return None


# ==================================================================================================
def calculate_range_with_padding(
    data: list | np.ndarray, padding_percentage: float = 0.1
) -> list[float]:
    data_range = max(data) - min(data)
    padding = data_range * padding_percentage

    return [min(data) - padding, max(data) + padding]


# ==================================================================================================
def print_out_figure(path_output: str | Path, figures: list | go.Figure) -> None:
    path_output = Path(path_output)
    path_output.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(figures, go.Figure):
        figures = [figures]

    with path_output.open("w") as file_out:
        for fig in figures:
            file_out.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))


# ==================================================================================================
def compute_integral(signal: list | np.ndarray, time_step: float) -> float:
    integral = time_step * (0.5 * signal[0] + np.sum(signal[1:-1]) + 0.5 * signal[-1])

    return integral


# ==================================================================================================
def compute_rolling_average(
    data: pd.DataFrame, name: str, period: float, time_step: float
) -> np.ndarray:
    """
    Be careful, this function assumes that the heart rate is constant
    """

    signal = data[name].to_numpy()

    n_data = len(signal)
    n_data_period = round(period / time_step)

    avg = np.zeros(n_data)

    for i in range(n_data):
        if i < n_data_period:
            avg[i] = np.nan
        else:
            avg[i] = 1.0 / period * compute_integral(signal[i - n_data_period : i], time_step)
            # alternative implementation: avg[i] = data.loc[data.index[i - n_data_period:i+1], name].mean()  # noqa: E501

    return avg


# ==================================================================================================
def colors_generator(n, color_scale=None, seed=29):
    random.seed(seed)

    # Define the color scale, and if one is provided, avoid basic colors
    if color_scale is not None:
        n_colors_left = n
        colors = []
    else:
        color_scale = "plasma"
        n_colors_left = n - 10
        # Color-blind friendly palette for n < 11
        colors = [
            "#0072b2",
            "#e69f00",
            "#cc79a7",
            "#56b4e9",
            "#d55e00",
            "#009eaa",
            "#999999",
            "#9f4a96",
            "#7e2954",
            "#9DFF00",
        ]

    if n_colors_left > 0:
        colors_colorscale = list(
            plotly.colors.sample_colorscale(
                color_scale, [i / (n_colors_left) for i in range(n_colors_left)]
            )
        )
        random.shuffle(colors_colorscale)
        colors = colors + colors_colorscale

    return colors


# ==================================================================================================
def patient_data_color():
    return "#000000"


# ==================================================================================================
def downsample_dataframe(df: pd.DataFrame, downsample_ratio: float) -> pd.DataFrame:
    if downsample_ratio != 1:
        step = int(1 / downsample_ratio)

        df = df.iloc[::step]

    return df


# ==================================================================================================
def hex_to_rgb(hex_color: str) -> tuple:
    if (len(hex_color) != 7) and (not hex_color.startswith("#")):
        raise ValueError("invalid input, hex_color must start with '#' and have 6 digits")

    hex_color = hex_color.lstrip("#")

    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


# ==================================================================================================
def find_delimiter(path_file: str | Path) -> str:
    sniffer = csv.Sniffer()

    path_file = Path(path_file)
    with Path.open(path_file) as fp:
        delimiter = sniffer.sniff(fp.readline()).delimiter

    return delimiter
