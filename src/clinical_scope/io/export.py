"""
Writing the terminal output of a pipeline run to disk.

Unlike the parquet cache or the app's own state files, an export is output the user asked
for, so a failure here is raised rather than logged and swallowed.
"""

import logging
from pathlib import Path

import pandas as pd

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


def save_df(df: pd.DataFrame, path: str | Path) -> None:
    """
    Save *df* to *path* as CSV (``.csv``) or parquet (any other recognised extension).

    Args:
        path: Destination path.  Extension must be ``.csv`` or ``.parquet``.

    Raises:
        ValueError: If *path* has an unsupported extension.

    """
    path = Path(path)
    if path.suffix == ".csv":
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
    elif path.suffix == ".parquet":
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    else:
        msg = f"Unsupported file format '{path.suffix}'. Use '.csv' or '.parquet'."
        raise ValueError(msg)
    logger.info("Saved %d rows to %s", len(df), path)


def print_out_figure(path_output: Path, fig_list: list, self_contained: bool = False) -> None:
    """
    Export Plotly figures to a single HTML file.

    With *self_contained*, plotly.js is embedded once (in the first figure; the rest reuse it)
    so the file renders on a machine with no network — at ~3.5 MB. Otherwise it is fetched
    from a CDN, which keeps the file small but shows a blank page offline.
    """
    path_output.parent.mkdir(parents=True, exist_ok=True)
    with Path.open(path_output, "w") as file_out:
        for figure_index, fig in enumerate(fig_list):
            if self_contained:
                # Embedding the ~3.5 MB bundle once per file, not once per figure.
                include_plotlyjs = (
                    cst.HtmlExport.INLINE if figure_index == 0 else cst.HtmlExport.OMIT
                )
            else:
                include_plotlyjs = cst.HtmlExport.CDN
            file_out.write(fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs))
