"""Pure-numpy spectral computation: grid validation, STFT, dB scaling."""

from dataclasses import dataclass

import numpy as np

import clinical_scope.constants as cst
from clinical_scope.sampling import TooFewSamplesError, build_uniform_grid


class SpectralRefusalError(ValueError):
    """A Signal's grid or configuration can't be safely turned into a spectral plot."""


@dataclass(frozen=True)
class SpectralParams:
    """
    The DSP knobs shared by :func:`spectrogram` and :func:`psd`.

    Bundled rather than passed one by one: they always travel together, they are all bare
    floats (so a transposed pair would silently return a different spectrum, not an error),
    and a new knob becomes one field here instead of an argument threaded through four
    signatures. Defaults come from ``cst.Spectral`` and ``cst.Sampling``; ``window_s`` alone
    defaults to *None*, meaning "derive it from ``freq_min``".
    """

    window_s: float | None = None
    overlap: float = cst.Spectral.OVERLAP_FRACTION
    window_cycles: float = cst.Spectral.WINDOW_CYCLES
    jitter_tolerance: float = cst.Sampling.JITTER_TOLERANCE
    gap_factor: float = cst.Sampling.GAP_FACTOR

    @classmethod
    def from_options(
        cls, window_s: float | None = None, overlap: float | None = None
    ) -> "SpectralParams":
        """Read the two configurable knobs, letting *None* mean "keep the default"."""
        return cls(
            window_s=window_s,
            overlap=overlap if overlap is not None else cls.overlap,
        )


def stft(
    y: np.ndarray,
    dt_seconds: float,
    window_s: float,
    overlap: float = cst.Spectral.OVERLAP_FRACTION,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Short-time Fourier transform via a sliding Hann-windowed FFT.

    Returns ``(frame_start_indices, freqs, power)``, ``power`` shaped
    ``(n_frames, len(freqs))`` as a one-sided **density** in ``unit²/Hz``. A frame
    containing any NaN sample (a masked recording gap) yields an all-NaN power row
    rather than being dropped, so the frame cadence — and the caller's derived time
    axis — stays regular.

    Windowing, normalisation and detrending follow ``scipy.signal.welch``'s defaults,
    so a reader can reproduce these numbers with the reference implementation.
    """
    n_window = max(round(window_s / dt_seconds), 2)
    n_step = max(round(n_window * (1 - overlap)), 1)
    window = np.hanning(n_window)

    n_frames = 1 + (len(y) - n_window) // n_step if len(y) >= n_window else 0
    if n_frames <= 0:
        msg = f"Signal too short for a {window_s:.3g}s window at this sample rate."
        raise SpectralRefusalError(msg)

    freqs = np.fft.rfftfreq(n_window, d=dt_seconds)
    frame_starts = np.arange(n_frames) * n_step
    power = np.empty((n_frames, len(freqs)), dtype=np.float64)

    # Density normalisation 1/(fs·Σw²). Without it the magnitude tracks window length —
    # a noise floor rising 3 dB per doubling — so two windows of the same signal could not
    # be compared, and an absolute db_range would slide out from under the data.
    density_scale = dt_seconds / np.sum(window**2)
    # One-sided: fold the negative frequencies back in. DC has no mirror partner, nor does
    # Nyquist when the window length is even.
    onesided_gain = np.full(len(freqs), 2.0)
    onesided_gain[0] = 1.0
    if n_window % 2 == 0:
        onesided_gain[-1] = 1.0

    for i, start in enumerate(frame_starts):
        segment = y[start : start + n_window]
        if np.isnan(segment).any():
            power[i, :] = np.nan
            continue
        # Demean per window: a DC offset otherwise leaks through the window's sidelobes
        # into the lowest bins, which is where clinical bands of interest sit.
        spectrum = np.fft.rfft((segment - segment.mean()) * window)
        power[i, :] = onesided_gain * density_scale * np.abs(spectrum) ** 2

    return frame_starts, freqs, power


def _framed_power(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None,
    params: SpectralParams,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Validate, grid, and frame one Signal, returning ``(x_uniform, frame_starts, freqs, power)``.

    Every refusal a spectral plot can raise lives here, so :func:`spectrogram` and :func:`psd`
    reject the same inputs for the same reasons. ``power`` is **linear**, shaped
    ``(n_frames, len(freqs))`` — each caller applies its own dB scaling last.
    """
    if period_resampling is not None and 0 < period_resampling < 1.0:
        # period_resampling step-decimates with no anti-alias filter, so the spectrum would
        # show aliased energy that looks like a real rhythm — refuse rather than render.
        msg = (
            f"Signal was decimated via period_resampling={period_resampling}. "
            "Drop period_resampling for this Signal to enable frequency analysis."
        )
        raise SpectralRefusalError(msg)

    freq_min, freq_max = freq_range
    if freq_min <= 0:
        msg = f"freq_range min must be > 0 Hz, got {freq_min}."
        raise SpectralRefusalError(msg)

    valid = ~np.isnan(y)
    try:
        x_uniform, y_uniform, dt_seconds = build_uniform_grid(
            x[valid], y[valid], params.jitter_tolerance, params.gap_factor
        )
    except TooFewSamplesError as exc:
        raise SpectralRefusalError(str(exc)) from exc

    nyquist = 0.5 / dt_seconds
    if freq_max > nyquist:
        msg = f"freq_range max {freq_max} Hz exceeds Nyquist {nyquist:.2f} Hz for this Signal."
        raise SpectralRefusalError(msg)

    window_s = params.window_s if params.window_s is not None else params.window_cycles / freq_min

    frame_starts, freqs, power = stft(y_uniform, dt_seconds, window_s, params.overlap)

    freq_mask = (freqs >= freq_min) & (freqs <= freq_max)
    return x_uniform, frame_starts, freqs[freq_mask], power[:, freq_mask]


def spectrogram(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None = 1.0,
    params: SpectralParams | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute a dB-scaled spectrogram for one Signal's raw ``x``/``y`` arrays.

    Pure numpy: takes arrays, returns ``(times, freqs, power_db)`` with
    ``power_db`` shaped ``(len(times), len(freqs))``. Refuses — raises
    ``SpectralRefusalError`` — rather than silently mis-rendering a decimated,
    too-short, or out-of-range Signal.
    """
    x_uniform, frame_starts, freqs, power = _framed_power(
        x, y, freq_range, period_resampling, params or SpectralParams()
    )
    power_db = 10 * np.log10(np.maximum(power, cst.Spectral.POWER_FLOOR))
    return x_uniform[frame_starts], freqs, power_db


def psd(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None = 1.0,
    params: SpectralParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute a dB-scaled power spectral density (Welch) for one Signal's ``x``/``y`` arrays.

    Same validation and framing as :func:`spectrogram`, then the mean periodogram over the
    whole series — so a PSD covers exactly the time range that was loaded. Returns
    ``(freqs, power_db)``, both 1-D.
    """
    _, _, freqs, power = _framed_power(
        x, y, freq_range, period_resampling, params or SpectralParams()
    )

    # A masked gap makes a whole frame NaN, so all-NaN means every window fell in a gap.
    if np.isnan(power).all():
        msg = "Every analysis window falls inside a recording gap."
        raise SpectralRefusalError(msg)

    # Average linear power, then take the log: averaging dB would give a geometric mean.
    mean_power = np.nanmean(power, axis=0)
    return freqs, 10 * np.log10(np.maximum(mean_power, cst.Spectral.POWER_FLOOR))
