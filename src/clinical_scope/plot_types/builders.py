"""
The builders behind each derived plot type -- the render halves, collected.

Kept apart from ``registry`` so the two layers stay separable: ``registry`` holds schemas and
is what the config readers import, while every ``plot.py`` here pulls numpy, plotly and
``signal_container``. Only ``plot_assembly`` reads this module.

Registering a schema without a builder here raises at import; the reverse cannot happen, since
a builder is keyed by the schema itself.
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
