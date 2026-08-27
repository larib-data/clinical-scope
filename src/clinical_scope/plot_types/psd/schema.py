"""Leaf half of the ``psd`` plot type: power spectral density against frequency."""

import clinical_scope.constants as cst
from clinical_scope.plot_types.base import PlotTypeSchema


class PsdSchema(PlotTypeSchema):
    """
    A PSD plots power against frequency, several signals overlaid on one subplot.

    Frequency on x, so nothing about the time axis applies; one entry names several signals
    precisely so their spectra can be compared, which is what the shared subplot is for.
    """

    NAME = cst.DatabaseOptions.PSD
    SECTION_KEY = cst.DatabaseOptions.PSD

    TIME_AXIS = False
    UNIFIED_HOVER = False
    RESAMPLED = False
