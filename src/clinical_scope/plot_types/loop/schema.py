"""Leaf half of the ``loop`` plot type: one signal plotted against another, over time."""

import clinical_scope.constants as cst
from clinical_scope.plot_types.base import PlotTypeSchema


class LoopSchema(PlotTypeSchema):
    """
    A loop plots one signal's values against another's, e.g. a pressure-volume loop.

    Its x is a signal, not time, so it shares none of the time-series axis behaviour -- but
    every drawn point still knows when it was recorded, which is what the time slider and a
    point annotation's timestamp are read from.
    """

    NAME = cst.DatabaseOptions.LOOP
    SECTION_KEY = cst.DatabaseOptions.LOOP

    TIME_AXIS = False
    UNIFIED_HOVER = False
    RESAMPLED = False
    GRID_LAYOUT = True
    POINT_TIMESTAMPS = True
