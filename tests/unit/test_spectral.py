"""
Tests for spectral.py: STFT-based spectrogram and PSD computation on plain numpy arrays.

No example data needed — synthetic arrays are enough to pin the grid-validation
policy (uniform passthrough, jittered-grid interpolation, gap masking, decimation
refusal) and the maths (a known sinusoid lands in the expected frequency bin).
"""

import numpy as np
import pytest

from clinical_scope.spectral import (
    SpectralParams,
    SpectralRefusalError,
    build_uniform_grid,
    psd,
    spectrogram,
    stft,
)


def _datetime_x(t_seconds: np.ndarray, start: str = "2024-01-01T00:00:00") -> np.ndarray:
    return np.datetime64(start) + (t_seconds * 1e9).astype(np.int64).astype("timedelta64[ns]")


def _uniform_series(fs: float, duration_s: float, freq_hz: float = 10.0):
    t_seconds = np.arange(int(fs * duration_s)) / fs
    y = np.sin(2 * np.pi * freq_hz * t_seconds)
    return _datetime_x(t_seconds), y


def _noise_series(fs: float, duration_s: float, sigma: float, seed: int = 0):
    t_seconds = np.arange(int(fs * duration_s)) / fs
    y = np.random.default_rng(seed).normal(0.0, sigma, t_seconds.size)
    return _datetime_x(t_seconds), y


def _linear_power(power_db: np.ndarray) -> np.ndarray:
    return 10 ** (power_db / 10)


def test_build_uniform_grid_passes_through_already_uniform_series():
    x, y = _uniform_series(fs=128.0, duration_s=5.0)

    x_out, y_out, dt_seconds = build_uniform_grid(x, y)

    assert x_out is x
    assert y_out is y
    assert dt_seconds == pytest.approx(1 / 128.0, rel=1e-6)


def test_build_uniform_grid_interpolates_jitter_beyond_tolerance():
    fs = 128.0
    x, y = _uniform_series(fs=fs, duration_s=5.0)
    x_ns = x.astype("datetime64[ns]").astype(np.int64)
    median_dt_ns = float(np.median(np.diff(x_ns)))

    # 20% jitter on every step, well past the 5% default tolerance.
    rng = np.random.default_rng(0)
    jitter_ns = (rng.uniform(-0.2, 0.2, size=len(x_ns) - 1) * median_dt_ns).astype(np.int64)
    x_ns[1:] += np.cumsum(jitter_ns)
    x_jittered = np.sort(x_ns).astype("datetime64[ns]")

    x_out, y_out, dt_seconds = build_uniform_grid(x_jittered, y)

    out_steps = np.diff(x_out.astype(np.int64))
    assert (out_steps == out_steps[0]).all()
    assert dt_seconds == pytest.approx(1 / fs, rel=0.05)


def test_build_uniform_grid_masks_gap_as_nan_rather_than_interpolating():
    fs = 128.0
    x, y = _uniform_series(fs=fs, duration_s=5.0)
    x_ns = x.astype("datetime64[ns]").astype(np.int64)
    median_dt_ns = float(np.median(np.diff(x_ns)))

    # Open up a gap 10x the median step partway through.
    gap_start_idx = len(x_ns) // 2
    x_ns[gap_start_idx:] += int(10 * median_dt_ns)
    x_gapped = x_ns.astype("datetime64[ns]")

    x_out, y_out, _ = build_uniform_grid(x_gapped, y)

    assert np.isnan(y_out).any()
    assert not np.isnan(y_out).all()


def test_stft_refuses_signal_shorter_than_window():
    y = np.zeros(10)
    with pytest.raises(SpectralRefusalError, match="too short"):
        stft(y, dt_seconds=1 / 128.0, window_s=5.0)


def test_spectrogram_finds_known_sinusoid_in_expected_bin():
    x, y = _uniform_series(fs=128.0, duration_s=20.0, freq_hz=10.0)

    times, freqs, power_db = spectrogram(x, y, freq_range=(1.0, 30.0))

    peak_freq = freqs[np.nanargmax(power_db[len(power_db) // 2])]
    assert peak_freq == pytest.approx(10.0, abs=0.5)
    assert len(times) == power_db.shape[0]
    assert len(freqs) == power_db.shape[1]


def test_spectrogram_refuses_decimated_signal():
    x, y = _uniform_series(fs=128.0, duration_s=5.0)

    with pytest.raises(SpectralRefusalError, match="decimated"):
        spectrogram(x, y, freq_range=(1.0, 10.0), period_resampling=0.5)


def test_spectrogram_refuses_freq_range_above_nyquist():
    x, y = _uniform_series(fs=10.0, duration_s=5.0, freq_hz=2.0)

    with pytest.raises(SpectralRefusalError, match="Nyquist"):
        spectrogram(x, y, freq_range=(1.0, 20.0))


def test_spectrogram_derives_window_from_freq_min():
    # window_cycles=5 (default) / freq_min=2Hz -> window_s=2.5s -> 320 samples @128Hz.
    x, y = _uniform_series(fs=128.0, duration_s=20.0, freq_hz=10.0)

    times, freqs, power_db = spectrogram(x, y, freq_range=(2.0, 30.0))

    freq_resolution = freqs[1] - freqs[0]
    assert freq_resolution == pytest.approx(1 / 2.5, rel=1e-6)


def test_psd_finds_known_sinusoid_in_expected_bin():
    x, y = _uniform_series(fs=128.0, duration_s=20.0, freq_hz=10.0)

    freqs, power_db = psd(x, y, freq_range=(1.0, 30.0))

    assert power_db.shape == freqs.shape
    assert freqs[np.argmax(power_db)] == pytest.approx(10.0, abs=0.5)


def test_psd_averages_linear_power_not_decibels():
    """
    A half-quiet, half-loud series must average its periodograms in linear power.

    Amplitudes 1 then 3 give frame powers P and 9P in equal numbers, so the mean is 5P
    (+6.99 dB over a reference of amplitude 1). Averaging the dB values instead would
    give the geometric mean 3P (+4.77 dB) — the bug this test exists to catch.
    """
    fs, half_duration_s, freq_hz = 128.0, 10.0, 10.0
    t_seconds = np.arange(int(fs * half_duration_s * 2)) / fs
    amplitude = np.where(t_seconds < half_duration_s, 1.0, 3.0)
    wave = np.sin(2 * np.pi * freq_hz * t_seconds)
    x = _datetime_x(t_seconds)

    # A whole number of non-overlapping windows per half, so no frame straddles the step.
    kwargs = {"freq_range": (1.0, 30.0), "params": SpectralParams(window_s=1.0, overlap=0.0)}
    _, reference_db = psd(x, wave, **kwargs)
    _, mixed_db = psd(x, amplitude * wave, **kwargs)

    gain_db = mixed_db.max() - reference_db.max()
    assert gain_db == pytest.approx(10 * np.log10(5.0), abs=0.2)


def test_psd_refuses_decimated_signal():
    x, y = _uniform_series(fs=128.0, duration_s=5.0)

    with pytest.raises(SpectralRefusalError, match="decimated"):
        psd(x, y, freq_range=(1.0, 10.0), period_resampling=0.5)


def test_psd_refuses_when_every_window_falls_in_a_gap():
    # Two one-second clusters an hour apart: on the uniform grid every 5s window straddles
    # the masked gap, so no frame has real data to average.
    fs, cluster_s, gap_s = 128.0, 1.0, 3600.0
    cluster = np.arange(int(fs * cluster_s)) / fs
    t_seconds = np.concatenate([cluster, cluster + gap_s])
    x = _datetime_x(t_seconds)
    y = np.sin(2 * np.pi * 10.0 * t_seconds)

    with pytest.raises(SpectralRefusalError, match="gap"):
        psd(x, y, freq_range=(1.0, 30.0), params=SpectralParams(window_s=5.0))


class TestDensityScaling:
    """
    Physics invariants of a one-sided power spectral density.

    These assert properties of the transform itself — hand-computed from the input
    signal, never from ``cst.Spectral`` — so they hold against any correct
    implementation and fail against a normalisation that drifts.
    """

    def test_psd_integrates_to_signal_variance(self):
        """
        Parseval: a sinusoid of amplitude A has variance A²/2, so its PSD must integrate
        to A²/2 over the full band. Catches every scaling factor at once.
        """
        amplitude, fs = 2.0, 128.0
        x, y = _uniform_series(fs=fs, duration_s=60.0)

        freqs, power_db = psd(
            x, amplitude * y, freq_range=(0.1, fs / 2), params=SpectralParams(window_s=4.0)
        )

        integral = np.sum(_linear_power(power_db)) * (freqs[1] - freqs[0])
        assert integral == pytest.approx(amplitude**2 / 2, rel=1e-3)

    def test_psd_white_noise_floor_matches_variance_over_nyquist(self):
        """
        Gaussian noise of variance σ² spreads flat over 0..f_nyquist, so a one-sided
        density sits at σ²/f_nyquist. Halve it and the ×2 fold-in has been dropped.
        """
        sigma, fs = 3.0, 128.0
        x, y = _noise_series(fs=fs, duration_s=200.0, sigma=sigma)

        _, power_db = psd(x, y, freq_range=(1.0, 50.0), params=SpectralParams(window_s=4.0))

        assert np.mean(_linear_power(power_db)) == pytest.approx(sigma**2 / (fs / 2), rel=0.05)

    def test_psd_noise_floor_is_invariant_to_window_length(self):
        """
        The same noise read through a 2 s and an 8 s window must give the same floor.

        Without density normalisation these sit 6 dB apart — a longer window simply
        accumulated more samples — which makes the documented window comparison, and any
        absolute db_range, meaningless.
        """
        x, y = _noise_series(fs=128.0, duration_s=200.0, sigma=3.0)

        kwargs = {"freq_range": (1.0, 50.0)}
        _, narrow_db = psd(x, y, params=SpectralParams(window_s=2.0), **kwargs)
        _, wide_db = psd(x, y, params=SpectralParams(window_s=8.0), **kwargs)

        assert np.mean(narrow_db) == pytest.approx(np.mean(wide_db), abs=0.5)

    def test_psd_tone_power_is_invariant_to_sample_rate(self):
        """
        Two channels digitised at different rates must be readable on one axis: the same
        tone integrates to the same power whether sampled at 128 Hz or 256 Hz.
        """
        amplitude = 2.0

        integrals = []
        for fs in (128.0, 256.0):
            x, y = _uniform_series(fs=fs, duration_s=60.0)
            freqs, power_db = psd(
                x, amplitude * y, freq_range=(0.1, fs / 2), params=SpectralParams(window_s=4.0)
            )
            integrals.append(np.sum(_linear_power(power_db)) * (freqs[1] - freqs[0]))

        assert integrals[0] == pytest.approx(integrals[1], rel=1e-3)

    def test_stft_demeans_each_window(self):
        """
        A constant offset carries no frequency content, so it must not reach the spectrum.

        Undemeaned it leaks through the window's sidelobes into the lowest bins — exactly
        where the clinical bands of interest sit.
        """
        x, y = _noise_series(fs=128.0, duration_s=200.0, sigma=3.0)

        kwargs = {"freq_range": (1.0, 50.0), "params": SpectralParams(window_s=4.0)}
        _, centered_db = psd(x, y, **kwargs)
        _, offset_db = psd(x, y + 5000.0, **kwargs)

        assert np.abs(centered_db - offset_db).max() == pytest.approx(0.0, abs=1e-6)
