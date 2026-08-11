"""Pure-numpy spectral computation: grid validation, STFT, dB scaling."""

import numpy as np

import clinical_scope.constants as cst


class SpectralRefusalError(ValueError):
    """A Signal's grid or configuration can't be safely turned into a spectral plot."""


def build_uniform_grid(
    x: np.ndarray,
    y: np.ndarray,
    jitter_tolerance: float = cst.Spectral.JITTER_TOLERANCE,
    gap_factor: float = cst.Spectral.GAP_FACTOR,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Return ``(x_uniform, y_uniform, dt_seconds)`` on a grid ready for FFT.

    ``x`` must already be sorted, unique datetime64 values with ``y`` NaN-free
    (callers drop NaNs before this). Gaps (a step past ``gap_factor`` times the
    median) are masked as NaN rather than interpolated across, so the STFT doesn't
    fabricate data over e.g. a lead disconnect. Jitter within ``jitter_tolerance``
    of the median step is treated as already uniform and returned unchanged; beyond
    that, the whole series is linearly interpolated onto a grid at the median step.
    """
    if len(x) < 2:  # noqa: PLR2004
        msg = "Need at least 2 samples to build a uniform grid."
        raise SpectralRefusalError(msg)

    x_ns = x.astype("datetime64[ns]").astype(np.int64)
    origin_ns = x_ns[0]
    # Relative to origin, not raw epoch ns: epoch ns (~1.7e18) exceeds float64's 2^53
    # exact-integer range, so np.interp's internal float64 cast would round grid steps
    # to ~hundreds of ns instead of the true dt.
    x_rel_ns = x_ns - origin_ns
    dt_ns_steps = np.diff(x_ns)
    median_dt_ns = float(np.median(dt_ns_steps))
    dt_ns_int = round(median_dt_ns)
    dt_seconds = median_dt_ns / 1e9

    jitter = np.abs(dt_ns_steps - median_dt_ns) / median_dt_ns
    is_gap = dt_ns_steps > gap_factor * median_dt_ns

    if not is_gap.any() and (jitter <= jitter_tolerance).all():
        return x, y, dt_seconds

    n_samples = round(x_rel_ns[-1] / dt_ns_int) + 1
    x_uniform_rel_ns = np.arange(n_samples, dtype=np.int64) * dt_ns_int
    y_uniform = np.interp(x_uniform_rel_ns, x_rel_ns, y)

    if is_gap.any():
        for start, end in zip(x_rel_ns[:-1][is_gap], x_rel_ns[1:][is_gap], strict=True):
            y_uniform[(x_uniform_rel_ns > start) & (x_uniform_rel_ns < end)] = np.nan

    x_uniform = (origin_ns + x_uniform_rel_ns).astype("datetime64[ns]")
    return x_uniform, y_uniform, dt_seconds


def stft(
    y: np.ndarray,
    dt_seconds: float,
    window_s: float,
    overlap: float = cst.Spectral.OVERLAP_FRACTION,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Short-time Fourier transform via a sliding Hann-windowed FFT.

    Returns ``(frame_start_indices, freqs, power)``, ``power`` shaped
    ``(n_frames, len(freqs))``. A frame containing any NaN sample (a masked
    recording gap) yields an all-NaN power row rather than being dropped, so the
    frame cadence — and the caller's derived time axis — stays regular.
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

    for i, start in enumerate(frame_starts):
        segment = y[start : start + n_window]
        if np.isnan(segment).any():
            power[i, :] = np.nan
            continue
        spectrum = np.fft.rfft(segment * window)
        power[i, :] = np.abs(spectrum) ** 2

    return frame_starts, freqs, power


def _framed_power(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None,
    window_s: float | None,
    overlap: float,
    window_cycles: float,
    jitter_tolerance: float,
    gap_factor: float,
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
    x_uniform, y_uniform, dt_seconds = build_uniform_grid(
        x[valid], y[valid], jitter_tolerance, gap_factor
    )

    nyquist = 0.5 / dt_seconds
    if freq_max > nyquist:
        msg = f"freq_range max {freq_max} Hz exceeds Nyquist {nyquist:.2f} Hz for this Signal."
        raise SpectralRefusalError(msg)

    if window_s is None:
        window_s = window_cycles / freq_min

    frame_starts, freqs, power = stft(y_uniform, dt_seconds, window_s, overlap)

    freq_mask = (freqs >= freq_min) & (freqs <= freq_max)
    return x_uniform, frame_starts, freqs[freq_mask], power[:, freq_mask]


def spectrogram(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None = 1.0,
    window_s: float | None = None,
    overlap: float = cst.Spectral.OVERLAP_FRACTION,
    window_cycles: float = cst.Spectral.WINDOW_CYCLES,
    jitter_tolerance: float = cst.Spectral.JITTER_TOLERANCE,
    gap_factor: float = cst.Spectral.GAP_FACTOR,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute a dB-scaled spectrogram for one Signal's raw ``x``/``y`` arrays.

    Pure numpy: takes arrays, returns ``(times, freqs, power_db)`` with
    ``power_db`` shaped ``(len(times), len(freqs))``. Refuses — raises
    ``SpectralRefusalError`` — rather than silently mis-rendering a decimated,
    too-short, or out-of-range Signal.
    """
    x_uniform, frame_starts, freqs, power = _framed_power(
        x,
        y,
        freq_range,
        period_resampling,
        window_s,
        overlap,
        window_cycles,
        jitter_tolerance,
        gap_factor,
    )
    power_db = 10 * np.log10(np.maximum(power, cst.Spectral.POWER_FLOOR))
    return x_uniform[frame_starts], freqs, power_db


def psd(
    x: np.ndarray,
    y: np.ndarray,
    freq_range: tuple[float, float],
    period_resampling: float | None = 1.0,
    window_s: float | None = None,
    overlap: float = cst.Spectral.OVERLAP_FRACTION,
    window_cycles: float = cst.Spectral.WINDOW_CYCLES,
    jitter_tolerance: float = cst.Spectral.JITTER_TOLERANCE,
    gap_factor: float = cst.Spectral.GAP_FACTOR,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute a dB-scaled power spectral density (Welch) for one Signal's ``x``/``y`` arrays.

    Same validation and framing as :func:`spectrogram`, then the mean periodogram over the
    whole series — so a PSD covers exactly the time range that was loaded. Returns
    ``(freqs, power_db)``, both 1-D.
    """
    _, _, freqs, power = _framed_power(
        x,
        y,
        freq_range,
        period_resampling,
        window_s,
        overlap,
        window_cycles,
        jitter_tolerance,
        gap_factor,
    )

    # A masked gap makes a whole frame NaN, so all-NaN means every window fell in a gap.
    if np.isnan(power).all():
        msg = "Every analysis window falls inside a recording gap."
        raise SpectralRefusalError(msg)

    # Average linear power, then take the log: averaging dB would give a geometric mean.
    mean_power = np.nanmean(power, axis=0)
    return freqs, 10 * np.log10(np.maximum(mean_power, cst.Spectral.POWER_FLOOR))
