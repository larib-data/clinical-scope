"""
The smoothing and differentiating transform methods.

Four Butterworth filters, a centred moving average and median, a Savitzky-Golay smoother and
a derivative.

The filters are four names for one helper. Each runs as second-order sections, forwards then
backwards (``sosfiltfilt``): zero phase, so the filtered curve does not lag the raw one it is
drawn over, and numerically stable at the low cutoff-to-sampling ratios ICU data reaches
(0.05 Hz on a 125 Hz waveform), where the ``(b, a)`` form is not.

Windows are durations, and a window too short for a signal's sampling never fails: it means no
smoothing, so one config row runs on a 500 Hz waveform and on 1 Hz numerics alike.
"""

import logging
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
    unchanged,
)

logger = logging.getLogger(__name__)

# --- Parameter names: the unit is in the name, and none is a sample count ---
CUTOFF_HZ = "cutoff_hz"
LOW_HZ = "low_hz"
HIGH_HZ = "high_hz"
ORDER = "order"
WINDOW_S = "window_s"
POLYORDER = "polyorder"

DEFAULT_ORDER = 4
DEFAULT_POLYORDER = 2
# The quadratic derivative over three samples is the central difference: the raw derivative.
DERIVATIVE_POLYORDER = 2
DERIVATIVE_MIN_WINDOW = 3


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


def moving_median(x: np.ndarray, y: np.ndarray, window_s: float) -> np.ndarray:
    """
    Median over a time window centred on each sample, on the samples as recorded.

    Windowed like :func:`moving_average`, so a window shorter than the sample spacing holds
    one sample and returns the input.
    """
    series = pd.Series(y, index=pd.DatetimeIndex(x))
    window = series.rolling(pd.Timedelta(seconds=window_s), center=True, closed="both")
    return window.median().to_numpy()


def _odd_window(window_s: float, dt_s: float) -> int:
    """Samples spanned by *window_s*, made odd: scipy centres an even window half a sample off."""
    n = round(window_s / dt_s)
    return n + 1 if n % 2 == 0 else n


def savgol(y: np.ndarray, dt_s: float, window_s: float, polyorder: int) -> np.ndarray:
    """
    Savitzky-Golay smoothing: a polynomial fitted in a sliding window, which keeps peaks.

    A window of no more samples than the polynomial has coefficients reproduces the input, so
    that is returned as is rather than approximated.
    """
    n = _odd_window(window_s, dt_s)
    if n <= polyorder:
        logger.info(
            "savgol window_s=%g holds %d sample(s) at %.3g Hz sampling, not more than polyorder "
            "%d: signal left unsmoothed.",
            window_s,
            n,
            1 / dt_s,
            polyorder,
        )
        return y.copy()
    if len(y) < n:
        msg = f"savgol over {window_s:g} s ({n} samples) needs at least {n} samples"
        raise SegmentTooShortError(msg)
    return signal.savgol_filter(y, n, polyorder)


def derivative(y: np.ndarray, dt_s: float, window_s: float) -> np.ndarray:
    """
    Rate of change per second; *window_s* smooths it, and 0 gives the raw derivative.

    The window is floored at three samples, where a quadratic Savitzky-Golay derivative is the
    central difference, so no separate unsmoothed code path exists.
    """
    requested = _odd_window(window_s, dt_s)
    n = max(DERIVATIVE_MIN_WINDOW, requested)
    if window_s > 0 and requested < DERIVATIVE_MIN_WINDOW:
        logger.info(
            "derivative window_s=%g is under three samples at %.3g Hz sampling: using three.",
            window_s,
            1 / dt_s,
        )
    if len(y) < n:
        msg = f"derivative over {n} samples needs at least {n} samples"
        raise SegmentTooShortError(msg)
    return signal.savgol_filter(y, n, DERIVATIVE_POLYORDER, deriv=1, delta=dt_s)


def _per_second(unit: str) -> str:
    return "/s" if unit == cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT else f"{unit}/s"


def _band_is_ordered(params: dict[str, Any]) -> str | None:
    if params[LOW_HZ] >= params[HIGH_HZ]:
        return f"low_hz ({params[LOW_HZ]}) must be below high_hz ({params[HIGH_HZ]})"
    return None


_CUTOFF_PARAMS = (Param(CUTOFF_HZ, float), Param(ORDER, int, DEFAULT_ORDER))
_BAND_PARAMS = (Param(LOW_HZ, float), Param(HIGH_HZ, float), Param(ORDER, int, DEFAULT_ORDER))

register(
    TransformDefinition(
        name=cst.Transform.LOWPASS,
        params=_CUTOFF_PARAMS,
        needs_uniform_grid=True,
        fn=lowpass,
        unit_rule=unchanged,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.HIGHPASS,
        params=_CUTOFF_PARAMS,
        needs_uniform_grid=True,
        fn=highpass,
        unit_rule=unchanged,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.BANDPASS,
        params=_BAND_PARAMS,
        needs_uniform_grid=True,
        fn=bandpass,
        unit_rule=unchanged,
        check=_band_is_ordered,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.BANDSTOP,
        params=_BAND_PARAMS,
        needs_uniform_grid=True,
        fn=bandstop,
        unit_rule=unchanged,
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
        unit_rule=unchanged,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.MOVING_MEDIAN,
        params=(Param(WINDOW_S, float),),
        needs_uniform_grid=False,
        fn=moving_median,
        unit_rule=unchanged,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.SAVGOL,
        params=(
            Param(WINDOW_S, float),
            Param(POLYORDER, int, DEFAULT_POLYORDER, allow_zero=True),
        ),
        needs_uniform_grid=True,
        fn=savgol,
        unit_rule=unchanged,
    )
)
register(
    TransformDefinition(
        name=cst.Transform.DERIVATIVE,
        params=(Param(WINDOW_S, float, 0, allow_zero=True),),
        needs_uniform_grid=True,
        fn=derivative,
        unit_rule=_per_second,
    )
)
