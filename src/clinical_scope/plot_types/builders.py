"""
The builders behind each derived plot type -- the half only the top of the stack may import.

Kept apart from ``registry`` because every ``plot.py`` imports ``signal_container``, and
``signal_container`` imports ``registry``: folding the two together would make importing a
Signal depend on Signal already existing. Only ``plot_assembly`` reads this module.
"""

from clinical_scope.plot_types import registry
from clinical_scope.plot_types.base import PlotBuilder, PlotTypeSchema
from clinical_scope.plot_types.loop import plot as _loop
from clinical_scope.plot_types.psd import plot as _psd
from clinical_scope.plot_types.spectrogram import plot as _spectrogram

BUILDERS: dict[type[PlotTypeSchema], PlotBuilder] = {
    registry.LoopSchema: _loop.BUILDER,
    registry.SpectrogramSchema: _spectrogram.BUILDER,
    registry.PsdSchema: _psd.BUILDER,
}

_missing = [schema.NAME for schema in registry.DERIVED if schema not in BUILDERS]
if _missing:
    msg = f"Plot type(s) {_missing} are registered but have no builder here."
    raise NotImplementedError(msg)
