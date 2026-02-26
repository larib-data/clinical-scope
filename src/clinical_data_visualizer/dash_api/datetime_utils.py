"""
DateTime utilities for Dash API visualization.

This module contains functions for parsing and formatting datetime values
used in Plotly figures and Dash applications.
"""

from datetime import UTC, datetime

# ==================================================================================================
# DateTime Utilities
# ==================================================================================================


def parse_datetime(s: str) -> datetime:
    """
    Parse Plotly datetime string into datetime object.

    Args:
        s: Datetime string in ISO format or similar

    Returns:
        datetime: Parsed datetime object

    """
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        # fallback if milliseconds or tz are missing
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)


def format_datetime(dt: datetime) -> str:
    """
    Format datetime back to Plotly string format.

    Args:
        dt: Datetime object to format

    Returns:
        str: Datetime string in Plotly format (milliseconds precision)

    """
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # drop microseconds to milliseconds
