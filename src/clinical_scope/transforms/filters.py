"""
The v1 transform methods: four Butterworth filters and a centred moving average.

The filters are four names for one helper. Each runs as second-order sections, forwards then
backwards (``sosfiltfilt``): zero phase, so the filtered curve does not lag the raw one it is
drawn over, and numerically stable at the low cutoff-to-sampling ratios ICU data reaches
(0.05 Hz on a 125 Hz waveform), where the ``(b, a)`` form is not.
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import signal

import clinical_scope.constants as cst
from clinical_scope.transforms.base import (
    Param,
    SegmentTooShortError,
    TransformDefinition,
    register,
)

# --- Parameter names: the unit is in the name, and none is a sample count ---
CUTOFF_HZ = "cutoff_hz"
LOW_HZ = "low_hz"
HIGH_HZ = "high_hz"
ORDER = "order"
WINDOW_S = "window_s"

DEFAULT_ORDER = 4


def _butterworth(
    y: np.ndarray, dt_s: float, btype: str, critical_hz: float | list[float], order: int
) -> np.ndarray:
    nyquist = 0.5 / dt_s
    if np.max(critical_hz) >= nyquist:
        msg = (
            f"{btype} at {critical_hz} Hz needs a frequency below this signal's Nyquist "
            f"frequency ({nyquist:.3g} Hz, half its {1 / dt_s:.3g} Hz sampling rate)"
        )
        raise ValueError(msg)
    sos = signal.butter(order, critical_hz, btype=btype, fs=1 / dt_s, output="sos")
    # The padding sosfiltfilt uses by default, passed explicitly so a stretch too short for it
    # is caught here, by name, instead of surfacing as scipy's ValueError.
    padlen = 3 * (2 * len(sos) + 1)
    if len(y) <= padlen:
        msg = f"{btype} order {order} needs more than {padlen} samples"
        raise SegmentTooShortError(msg)
    return signal.sosfiltfilt(sos, y, padlen=padlen)


def lowpass(y: np.ndarray, dt_s: float, cutoff_hz: float, order: int) -> np.ndarray:
    return _butterworth(y, dt_s, "lowpass", cutoff_hz, order)


def highpass(y: np.ndarray, dt_s: float, cutoff_hz: float, order: int) -> np.ndarray:
    return _butterworth(y, dt_s, "highpass", cutoff_hz, order)


def bandpass(y: np.ndarray, dt_s: float, low_hz: float, high_hz: float, order: int) -> np.ndarray:
    return _butterworth(y, dt_s, "bandpass", [low_hz, high_hz], order)


def bandstop(y: np.ndarray, dt_s: float, low_hz: float, high_hz: float, order: int) -> np.ndarray:
    return _butterworth(y, dt_s, "bandstop", [low_hz, high_hz], order)


def moving_average(x: np.ndarray, y: np.ndarray, window_s: float) -> np.ndarray:
    """
    Mean over a time window centred on each sample, on the samples as recorded.

    Centred so it does not lag the raw curve, like the zero-phase filters. The window is a
    duration, never a sample count, so it never spans more than *window_s* and does not bridge
    a gap longer than that.
    """
    series = pd.Series(y, index=pd.DatetimeIndex(x))
    # Closed at both ends: pandas' default leaves the past end open, so the window, and the
    # average with it, would sit half a sample ahead.
    window = series.rolling(pd.Timedelta(seconds=window_s), center=True, closed="both")
    return window.mean().to_numpy()


def _band_is_ordered(params: dict[str, Any]) -> str | None:
    if params[LOW_HZ] >= params[HIGH_HZ]:
        return f"low_hz ({params[LOW_HZ]}) must be below high_hz ({params[HIGH_HZ]})"
    return None


_CUTOFF_PARAMS = (Param(CUTOFF_HZ, float), Param(ORDER, int, DEFAULT_ORDER))
_BAND_PARAMS = (Param(LOW_HZ, float), Param(HIGH_HZ, float), Param(ORDER, int, DEFAULT_ORDER))

register(
    TransformDefinition(
        name=cst.Transform.LOWPASS, params=_CUTOFF_PARAMS, needs_uniform_grid=True, fn=lowpass
    )
)
register(
    TransformDefinition(
        name=cst.Transform.HIGHPASS, params=_CUTOFF_PARAMS, needs_uniform_grid=True, fn=highpass
    )
)
register(
    TransformDefinition(
        name=cst.Transform.BANDPASS,
        params=_BAND_PARAMS,
        needs_uniform_grid=True,
        fn=bandpass,
        check=_band_is_ordered,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.BANDSTOP,
        params=_BAND_PARAMS,
        needs_uniform_grid=True,
        fn=bandstop,
        check=_band_is_ordered,
    )
)
# Native-irregular: a time window needs no grid, and keeps the timestamps as recorded.
register(
    TransformDefinition(
        name=cst.Transform.MOVING_AVERAGE,
        params=(Param(WINDOW_S, float),),
        needs_uniform_grid=False,
        fn=moving_average,
    )
)
