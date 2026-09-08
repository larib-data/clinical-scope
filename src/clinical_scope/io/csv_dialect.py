"""Detecting how a CSV export is delimited before reading it."""

import csv
from pathlib import Path

# Enough of a CSV to expose its delimiter without reading a multi-gigabyte export.
_CSV_SNIFF_SAMPLE_BYTES = 4096


# ==================================================================================================
def sniff_csv_delimiter(file_path: str | Path, default: str = ",") -> str:
    """
    Return the delimiter *file_path* uses, or *default* when it cannot be detected.

    Device exports are routinely re-saved through a locale-configured Excel, which turns a
    comma-separated export into a semicolon-separated one without changing its name.
    """
    with Path(file_path).open("r", newline="") as file:
        sample = file.read(_CSV_SNIFF_SAMPLE_BYTES)
    try:
        return csv.Sniffer().sniff(sample).delimiter
    except csv.Error:
        return default
