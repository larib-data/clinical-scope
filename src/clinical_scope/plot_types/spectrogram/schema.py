"""Leaf half of the ``spectrogram`` plot type: one signal's spectrum over time."""

import clinical_scope.constants as cst
from clinical_scope.plot_types.base import PlotTypeSchema


class SpectrogramSchema(PlotTypeSchema):
    """
    A spectrogram is a heatmap of one signal's power spectrum against time.

    Time on x like a time-series, but a colour scale rather than a line: it carries a
    colorbar, and a unified hover panel is meaningless when each pixel is its own cell.
    """

    NAME = cst.DatabaseOptions.SPECTROGRAM
    SECTION_KEY = cst.DatabaseOptions.SPECTROGRAM

    UNIFIED_HOVER = False
    RESAMPLED = False
    HAS_COLORBAR = True
