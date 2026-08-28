"""Top half of the fake plot type: copy one signal's data and install a hover of its own."""

from typing import Any

from clinical_scope.plot_types.base import PlotBuilder, RenderSpec, require_time_series
from clinical_scope.signal_container import Data, Metadata, PlotOptions, Signal, TraceOptions
from clinical_scope.signal_reference import resolve_one

from tests.plot_types.fake.schema import FakeSchema


def build(all_signals: list[Signal], fake_name: str, config: Any) -> Signal:
    source = resolve_one(config, all_signals)
    require_time_series(source)
    return Signal(
        raw_name=fake_name,
        name=fake_name,
        data=Data(x=source.data.x, y=source.data.y, timezone=source.data.timezone),
        trace_options=TraceOptions(
            plot_options=PlotOptions(
                schema=FakeSchema,
                display_timezone=source.trace_options.plot_options.display_timezone,
            )
        ),
        metadata=Metadata(),
        display_fallbacks=source.display_fallbacks,
        render=RenderSpec(hover_template=f"<b>{fake_name}</b> fake<extra></extra>"),
    )


BUILDER = PlotBuilder(build=build)
