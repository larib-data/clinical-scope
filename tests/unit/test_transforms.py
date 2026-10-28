"""
Tests for transforms/: the cell grammar, static validation, the v1 methods and the grid driver.

Synthetic arrays only. The filters are checked by what they do to known sinusoids, the driver
by where its output samples land -- never inside a gap, always on one uniform grid.
"""

import logging

import numpy as np
import pytest

from clinical_scope import transforms
from clinical_scope.sampling import contiguous_segments


def _datetime_x(t_seconds: np.ndarray) -> np.ndarray:
    return np.datetime64("2024-01-01T00:00:00", "ns") + (t_seconds * 1e9).astype(np.int64).astype(
        "timedelta64[ns]"
    )


def _tones(fs: float, duration_s: float, *freqs_hz: float) -> tuple[np.ndarray, np.ndarray]:
    t_seconds = np.arange(int(fs * duration_s)) / fs
    y = sum(np.sin(2 * np.pi * freq * t_seconds) for freq in freqs_hz)
    return _datetime_x(t_seconds), y


def _amplitude_at(x: np.ndarray, y: np.ndarray, freq_hz: float) -> float:
    """Amplitude of the *freq_hz* component of y, by projection onto that sinusoid."""
    t_seconds = (x - x[0]).astype("timedelta64[ns]").astype(np.int64) / 1e9
    return float(2 * np.abs(np.mean(y * np.exp(-2j * np.pi * freq_hz * t_seconds))))


def _run(spec: dict, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return transforms.resolve(spec).apply(x, y, name="test")


# ---------------------------------------------------------------------------------------------
# The spreadsheet cell grammar
# ---------------------------------------------------------------------------------------------


class TestParseTransformCell:
    def test_a_call_becomes_the_canonical_dict(self):
        assert transforms.parse_transform_cell("lowpass(cutoff_hz=5, order=4)") == {
            "method": "lowpass",
            "cutoff_hz": 5,
            "order": 4,
        }

    def test_a_bare_name_is_a_method_with_no_parameters(self):
        assert transforms.parse_transform_cell("moving_average") == {"method": "moving_average"}

    def test_surrounding_whitespace_and_float_literals_are_fine(self):
        assert transforms.parse_transform_cell("  bandpass(low_hz=0.5, high_hz=4e1) ") == {
            "method": "bandpass",
            "low_hz": 0.5,
            "high_hz": 40.0,
        }

    @pytest.mark.parametrize(
        "cell",
        [
            "lowpass(",  # not Python
            "lowpass(5)",  # positional: which parameter is 5?
            "signal.lowpass(cutoff_hz=5)",  # not a bare name
            "lowpass(cutoff_hz=five)",  # not a literal
            "lowpass(cutoff_hz=__import__('os'))",  # nor anything that would run
            "lowpass(**options)",
            "lowpass(cutoff_hz=1, cutoff_hz=2)",  # which one?
            "lowpass(method='highpass')",  # would overwrite the method
            "5",
        ],
    )
    def test_anything_else_is_kept_as_text_for_validation_to_report(self, cell):
        assert transforms.parse_transform_cell(cell) == cell


# ---------------------------------------------------------------------------------------------
# Static validation
# ---------------------------------------------------------------------------------------------


def _issues(spec) -> list[tuple[str, str]]:
    return [(issue.severity, issue.path) for issue in transforms.validate_transform(spec, "t")]


class TestValidateTransform:
    @pytest.mark.parametrize(
        "spec",
        [
            {"method": "lowpass", "cutoff_hz": 5},
            {"method": "lowpass", "cutoff_hz": 0.05, "order": 2},
            {"method": "highpass", "cutoff_hz": 1},
            {"method": "bandpass", "low_hz": 1, "high_hz": 40},
            {"method": "bandstop", "low_hz": 49, "high_hz": 51, "order": 2},
            {"method": "moving_average", "window_s": 60},
        ],
    )
    def test_a_valid_spec_raises_nothing(self, spec):
        assert transforms.validate_transform(spec, "t") == []

    def test_an_unreadable_cell_is_an_error_that_shows_the_syntax(self):
        issues = transforms.validate_transform("lowpass(5)", "t")

        assert [(issue.severity, issue.path) for issue in issues] == [("error", "t")]
        assert "lowpass(cutoff_hz=5" in issues[0].message

    def test_a_non_dict_is_an_error(self):
        assert _issues(["lowpass"]) == [("error", "t")]

    @pytest.mark.parametrize("method", ["nope", None, 3])
    def test_an_unknown_method_is_an_error(self, method):
        assert _issues({"method": method}) == [("error", "t.method")]

    def test_a_missing_required_parameter_is_an_error(self):
        assert _issues({"method": "bandpass", "low_hz": 1}) == [("error", "t.high_hz")]

    def test_a_parameter_with_a_default_may_be_left_out(self):
        assert _issues({"method": "lowpass", "cutoff_hz": 5}) == []

    def test_an_unknown_parameter_is_an_error(self):
        """A misspelled parameter left unused would leave the default in force, unseen."""
        issues = transforms.validate_transform(
            {"method": "lowpass", "cutoff_hz": 5, "oder": 2}, "t"
        )

        assert [(issue.severity, issue.path) for issue in issues] == [("error", "t")]
        assert "oder" in issues[0].message
        assert "order" in issues[0].message

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("cutoff_hz", "5"),
            ("cutoff_hz", True),
            ("cutoff_hz", 0),
            ("cutoff_hz", -1),
            ("cutoff_hz", float("nan")),
            ("order", 2.5),
            ("order", 0),
        ],
    )
    def test_a_mistyped_or_non_positive_parameter_is_an_error(self, param, value):
        spec = {"method": "lowpass", "cutoff_hz": 5, param: value}

        assert _issues(spec) == [("error", f"t.{param}")]

    @pytest.mark.parametrize("method", ["bandpass", "bandstop"])
    @pytest.mark.parametrize(("low", "high"), [(10, 1), (5, 5)])
    def test_a_band_must_run_low_to_high(self, method, low, high):
        assert _issues({"method": method, "low_hz": low, "high_hz": high}) == [("error", "t")]

    def test_resolve_refuses_what_validation_calls_an_error(self):
        with pytest.raises(ValueError, match="cutoff_hz"):
            transforms.resolve({"method": "lowpass"})

    def test_resolve_fills_in_defaults(self):
        resolved = transforms.resolve({"method": "lowpass", "cutoff_hz": 5})

        assert resolved.spec == {"method": "lowpass", "cutoff_hz": 5, "order": 4}

    def test_resolve_refuses_an_unknown_parameter(self):
        with pytest.raises(ValueError, match="oder"):
            transforms.resolve({"method": "lowpass", "cutoff_hz": 5, "oder": 2})


# ---------------------------------------------------------------------------------------------
# The Butterworth filters
# ---------------------------------------------------------------------------------------------


class TestButterworth:
    def test_lowpass_keeps_the_slow_tone_and_removes_the_fast_one(self):
        x, y = _tones(125.0, 20.0, 1.0, 20.0)

        x_out, y_out = _run({"method": "lowpass", "cutoff_hz": 5}, x, y)

        assert _amplitude_at(x_out, y_out, 1.0) == pytest.approx(1.0, abs=0.02)
        assert _amplitude_at(x_out, y_out, 20.0) < 0.01

    def test_highpass_keeps_the_fast_tone_and_removes_the_slow_one(self):
        x, y = _tones(125.0, 20.0, 1.0, 20.0)

        x_out, y_out = _run({"method": "highpass", "cutoff_hz": 5}, x, y)

        assert _amplitude_at(x_out, y_out, 20.0) == pytest.approx(1.0, abs=0.02)
        assert _amplitude_at(x_out, y_out, 1.0) < 0.01

    def test_bandpass_keeps_only_the_tone_inside_the_band(self):
        x, y = _tones(125.0, 20.0, 1.0, 20.0, 50.0)

        x_out, y_out = _run({"method": "bandpass", "low_hz": 10, "high_hz": 30}, x, y)

        assert _amplitude_at(x_out, y_out, 20.0) == pytest.approx(1.0, abs=0.02)
        assert _amplitude_at(x_out, y_out, 1.0) < 0.01
        assert _amplitude_at(x_out, y_out, 50.0) < 0.01

    def test_bandstop_removes_only_the_tone_inside_the_band(self):
        x, y = _tones(125.0, 20.0, 1.0, 20.0, 50.0)

        x_out, y_out = _run({"method": "bandstop", "low_hz": 10, "high_hz": 30}, x, y)

        assert _amplitude_at(x_out, y_out, 20.0) < 0.01
        assert _amplitude_at(x_out, y_out, 1.0) == pytest.approx(1.0, abs=0.02)
        assert _amplitude_at(x_out, y_out, 50.0) == pytest.approx(1.0, abs=0.02)

    def test_zero_phase_the_kept_tone_does_not_lag(self):
        x, y = _tones(125.0, 20.0, 1.0)

        _, y_out = _run({"method": "lowpass", "cutoff_hz": 5}, x, y)

        interior = slice(250, -250)  # clear of the edge transients
        assert np.max(np.abs(y_out[interior] - y[interior])) < 0.01

    def test_a_low_cutoff_on_fast_sampling_stays_stable(self):
        """0.05 Hz on 125 Hz is where the (b, a) form loses precision; SOS must not."""
        x, y = _tones(125.0, 120.0, 0.01, 5.0)

        x_out, y_out = _run({"method": "lowpass", "cutoff_hz": 0.05}, x, y)

        assert np.isfinite(y_out).all()
        assert _amplitude_at(x_out, y_out, 5.0) < 0.01

    @pytest.mark.parametrize("cutoff_hz", [5.0, 8.0])
    def test_a_cutoff_at_or_above_nyquist_raises(self, cutoff_hz):
        x, y = _tones(10.0, 20.0, 1.0)

        with pytest.raises(ValueError, match="Nyquist"):
            _run({"method": "lowpass", "cutoff_hz": cutoff_hz}, x, y)


# ---------------------------------------------------------------------------------------------
# The grid driver: gaps, irregular timestamps, short stretches
# ---------------------------------------------------------------------------------------------


def _with_gap(
    fs: float, before_s: float, gap_s: float, after_s: float
) -> tuple[np.ndarray, np.ndarray, tuple[np.datetime64, np.datetime64]]:
    """A 1 Hz tone recorded for *before_s*, interrupted for *gap_s*, then for *after_s*."""
    t_before = np.arange(int(fs * before_s)) / fs
    t_after = t_before[-1] + gap_s + np.arange(int(fs * after_s)) / fs
    t_seconds = np.concatenate([t_before, t_after])
    x = _datetime_x(t_seconds)
    gap_edges = (x[len(t_before) - 1], x[len(t_before)])
    return x, np.sin(2 * np.pi * t_seconds), gap_edges


class TestGridDriver:
    def test_no_sample_is_produced_inside_a_gap(self):
        x, y, (gap_start, gap_end) = _with_gap(125.0, 10.0, 5.0, 10.0)

        x_out, _ = _run({"method": "lowpass", "cutoff_hz": 5}, x, y)

        assert not ((x_out > gap_start) & (x_out < gap_end)).any()
        assert (x_out <= gap_start).any()
        assert (x_out >= gap_end).any()

    def test_each_side_of_a_gap_is_filtered_on_its_own(self):
        """A step across the gap would ring into both sides if the filter spanned it."""
        x, _, (gap_start, _) = _with_gap(125.0, 10.0, 5.0, 10.0)
        y = np.where(x <= gap_start, 0.0, 100.0)

        x_out, y_out = _run({"method": "lowpass", "cutoff_hz": 1}, x, y)

        assert np.allclose(y_out[x_out <= gap_start], 0.0, atol=1e-6)
        assert np.allclose(y_out[x_out > gap_start], 100.0, atol=1e-6)

    def test_irregular_timestamps_come_out_on_a_uniform_grid(self):
        fs = 125.0
        t_seconds = np.arange(int(fs * 10)) / fs
        # 20% jitter on every step, well past the 5% the grid treats as already uniform.
        t_seconds[1:-1] += np.random.default_rng(0).uniform(-0.2, 0.2, len(t_seconds) - 2) / fs
        x = _datetime_x(t_seconds)

        x_out, _ = _run({"method": "lowpass", "cutoff_hz": 5}, x, np.sin(2 * np.pi * t_seconds))

        steps = np.diff(x_out.astype(np.int64))
        assert (steps == steps[0]).all()
        assert steps[0] / 1e9 == pytest.approx(1 / fs, rel=0.05)

    def test_a_stretch_too_short_for_the_filter_is_left_out_and_logged(self, caplog):
        x, y, (gap_start, _) = _with_gap(125.0, 10.0, 5.0, 10 / 125.0)  # 10 samples after

        with caplog.at_level(logging.WARNING, logger="clinical_scope.transforms.base"):
            x_out, _ = _run({"method": "lowpass", "cutoff_hz": 5}, x, y)

        assert x_out.max() <= gap_start, "the short stretch yields no output"
        assert (x_out <= gap_start).sum() > 1000, "the long stretch is still filtered"
        assert "too short" in caplog.text

    def test_when_every_stretch_is_too_short_the_transform_fails(self):
        x, y = _tones(125.0, 10 / 125.0, 1.0)

        with pytest.raises(ValueError, match="too short"):
            _run({"method": "lowpass", "cutoff_hz": 5}, x, y)


class TestContiguousSegments:
    def test_runs_of_data_between_nans(self):
        y = np.array([np.nan, 1.0, 2.0, np.nan, np.nan, 3.0, np.nan])

        assert contiguous_segments(y) == [slice(1, 3), slice(5, 6)]

    def test_a_series_without_nan_is_one_segment(self):
        assert contiguous_segments(np.ones(4)) == [slice(0, 4)]

    def test_an_all_nan_series_has_none(self):
        assert contiguous_segments(np.full(3, np.nan)) == []


# ---------------------------------------------------------------------------------------------
# The moving average: native irregular sampling
# ---------------------------------------------------------------------------------------------


class TestMovingAverage:
    def test_keeps_the_original_timestamps(self):
        t_seconds = np.cumsum(np.random.default_rng(0).uniform(0.5, 1.5, 200))
        x = _datetime_x(t_seconds)

        x_out, y_out = _run({"method": "moving_average", "window_s": 10}, x, np.sin(t_seconds))

        assert np.array_equal(x_out, x)
        assert len(y_out) == len(x)

    def test_is_centred_so_it_does_not_lag(self):
        t_seconds = np.arange(0, 100, 0.1)
        x = _datetime_x(t_seconds)

        _, y_out = _run({"method": "moving_average", "window_s": 2}, x, t_seconds.copy())

        interior = slice(20, -20)
        # A trailing average of a ramp lags it by half the window: 1 s here.
        assert np.max(np.abs(y_out[interior] - t_seconds[interior])) < 0.1

    def test_does_not_bridge_a_gap_longer_than_its_window(self):
        t_seconds = np.concatenate([np.arange(0, 10, 1.0), np.arange(110, 120, 1.0)])
        y = np.where(t_seconds < 50, 0.0, 10.0)

        _, y_out = _run({"method": "moving_average", "window_s": 60}, _datetime_x(t_seconds), y)

        assert np.array_equal(y_out, y)
