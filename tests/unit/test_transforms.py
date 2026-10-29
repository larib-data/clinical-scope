"""
Tests for transforms/: the cell grammar, static validation, the v1 methods and the grid driver.

Synthetic arrays only. The filters are checked by what they do to known sinusoids, the driver
by where its output samples land -- never inside a gap, always on one uniform grid.
"""

import logging
import tracemalloc

import numpy as np
import pytest

from clinical_scope import transforms
from clinical_scope.sampling import contiguous_segments, gap_free_runs


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
            # Literals, but not ones a JSON store can hold: the upload would fail on them.
            "lowpass(cutoff_hz={5})",
            "lowpass(cutoff_hz=5j)",
            "lowpass(cutoff_hz=b'5')",
            "lowpass(cutoff_hz=...)",
            "lowpass(cutoff_hz=[5])",
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
            {"method": "moving_median", "window_s": 5},
            {"method": "savgol", "window_s": 1},
            {"method": "savgol", "window_s": 1, "polyorder": 0},
            {"method": "derivative"},
            {"method": "derivative", "window_s": 0},
            {"method": "derivative", "window_s": 0.05},
            {"method": "minmax", "low_pct": 1, "high_pct": 99},
            {"method": "minmax", "low_pct": 0, "high_pct": 100},
            {"method": "log10"},
            {"method": "zscore"},
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

    @pytest.mark.parametrize("method", ["savgol", "moving_median"])
    def test_a_window_of_zero_is_refused_where_it_means_nothing(self, method):
        assert _issues({"method": method, "window_s": 0}) == [("error", "t.window_s")]

    @pytest.mark.parametrize(
        ("spec", "path"),
        [
            ({"method": "savgol", "window_s": 1, "polyorder": -1}, "t.polyorder"),
            ({"method": "savgol", "window_s": 1, "polyorder": 1.5}, "t.polyorder"),
            ({"method": "derivative", "window_s": -1}, "t.window_s"),
            ({"method": "minmax", "high_pct": 101}, "t.high_pct"),
            ({"method": "minmax", "low_pct": -1}, "t.low_pct"),
            ({"method": "minmax", "low_pct": 50, "high_pct": 50}, "t"),
            ({"method": "minmax", "low_pct": 100}, "t"),
            ({"method": "minmax", "low_pct": 99, "high_pct": 1}, "t"),
        ],
    )
    def test_a_zero_bounded_or_ordered_parameter_is_checked(self, spec, path):
        assert _issues(spec) == [("error", path)]

    def test_messages_say_what_is_wrong(self):
        def message(spec):
            return transforms.validate_transform(spec, "t")[0].message

        assert message({"method": "lowpass", "cutoff_hz": 0}) == "Must be positive, got 0"
        assert (
            message({"method": "derivative", "window_s": -1})
            == "Must be zero or positive, got -1"
        )
        assert message({"method": "minmax", "high_pct": 101}) == "Must be at most 100, got 101"

    @pytest.mark.parametrize("method", ["log10", "ln", "exp", "abs", "negate", "zscore"])
    def test_a_parameterless_method_refuses_a_parameter(self, method):
        assert _issues({"method": method, "window_s": 1}) == [("error", "t")]

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

    def test_memory_follows_the_samples_not_the_time_they_span(self):
        """Two 10 s bursts a day apart: a grid across the day would hold 10.8 M points."""
        x, y, _ = _with_gap(125.0, 10.0, 86_400.0, 10.0)

        tracemalloc.start()
        try:
            x_out, _ = _run({"method": "lowpass", "cutoff_hz": 5}, x, y)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert len(x_out) == len(x)
        assert peak_bytes < 20e6

    def test_each_stretch_between_gaps_keeps_its_own_sampling(self):
        """A recording resumed at another rate is gridded at that rate, not the first one's."""
        t_fast = np.arange(0, 10, 1 / 125)
        t_slow = 20 + np.arange(0, 10, 1 / 50)
        t_seconds = np.concatenate([t_fast, t_slow])
        x = _datetime_x(t_seconds)

        x_out, _ = _run({"method": "lowpass", "cutoff_hz": 5}, x, np.sin(2 * np.pi * t_seconds))

        steps_s = np.diff(x_out.astype(np.int64)) / 1e9
        assert np.allclose(steps_s[: len(t_fast) - 1], 1 / 125)
        assert np.allclose(steps_s[-(len(t_slow) - 1) :], 1 / 50)

    def test_when_every_stretch_is_too_short_the_transform_fails(self):
        x, y = _tones(125.0, 10 / 125.0, 1.0)

        with pytest.raises(ValueError, match="too short"):
            _run({"method": "lowpass", "cutoff_hz": 5}, x, y)


class TestNoOutputAtAll:
    def test_a_method_yielding_no_finite_value_fails_with_its_own_reason(self):
        diverging = transforms.TransformDefinition(
            name="diverging",
            params=(),
            needs_uniform_grid=True,
            fn=lambda y, dt_s: np.full_like(y, np.inf),  # noqa: ARG005
            unit_rule=transforms.base.unchanged,
        )
        x, y = _tones(125.0, 10.0, 1.0)

        with pytest.raises(ValueError, match="no finite value"):
            transforms.ResolvedTransform(diverging, {}).apply(x, y)


class TestGapFreeRuns:
    def test_splits_where_a_step_exceeds_three_median_steps(self):
        x = _datetime_x(np.array([0.0, 1.0, 2.0, 3.0, 10.0, 11.0, 12.0]))

        assert gap_free_runs(x) == [slice(0, 4), slice(4, 7)]

    def test_jitter_below_the_gap_factor_is_one_run(self):
        x = _datetime_x(np.array([0.0, 1.0, 3.5, 4.0, 5.0]))

        assert gap_free_runs(x) == [slice(0, 5)]

    def test_an_empty_series_has_no_run(self):
        assert gap_free_runs(_datetime_x(np.array([]))) == []


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

    def test_is_centred_so_it_neither_lags_nor_leads(self):
        """A trailing average of a ramp lags it by half the window; a centred one sits on it."""
        t_seconds = np.arange(0, 100, 1.0)
        x = _datetime_x(t_seconds)

        _, y_out = _run({"method": "moving_average", "window_s": 2}, x, t_seconds.copy())

        interior = slice(2, -2)
        assert np.allclose(y_out[interior], t_seconds[interior])

    def test_does_not_bridge_a_gap_longer_than_its_window(self):
        t_seconds = np.concatenate([np.arange(0, 10, 1.0), np.arange(110, 120, 1.0)])
        y = np.where(t_seconds < 50, 0.0, 10.0)

        _, y_out = _run({"method": "moving_average", "window_s": 60}, _datetime_x(t_seconds), y)

        assert np.array_equal(y_out, y)


# ---------------------------------------------------------------------------------------------
# The v2 methods
# ---------------------------------------------------------------------------------------------


class TestParseNewCells:
    def test_a_bare_parameterless_method_name_parses(self):
        assert transforms.parse_transform_cell("log10") == {"method": "log10"}

    def test_minmax_percentiles_parse_as_keywords(self):
        assert transforms.parse_transform_cell("minmax(low_pct=1, high_pct=99)") == {
            "method": "minmax",
            "low_pct": 1,
            "high_pct": 99,
        }


class TestSavgol:
    def test_a_quadratic_is_preserved_at_any_window(self):
        t_seconds = np.arange(0, 20, 0.04)
        y = 3.0 * t_seconds**2 - 2.0 * t_seconds + 5.0

        for window_s in (0.5, 1.0, 2.2):
            _, y_out = _run(
                {"method": "savgol", "window_s": window_s, "polyorder": 2},
                _datetime_x(t_seconds),
                y,
            )

            assert np.allclose(y_out, y, rtol=1e-9, atol=1e-6)

    def test_it_smooths_noise(self):
        t_seconds = np.arange(0, 20, 0.04)
        noise = np.random.default_rng(0).normal(0, 1, len(t_seconds))

        _, y_out = _run({"method": "savgol", "window_s": 1}, _datetime_x(t_seconds), noise)

        assert np.std(y_out) < 0.5 * np.std(noise)

    def test_the_window_handed_to_scipy_is_never_even(self, monkeypatch):
        seen = []
        real = transforms.filters.signal.savgol_filter

        def spy(y, window_length, *args, **kwargs):
            seen.append(window_length)
            return real(y, window_length, *args, **kwargs)

        monkeypatch.setattr(transforms.filters.signal, "savgol_filter", spy)
        t_seconds = np.arange(0, 20, 0.04)

        # 25 Hz: 0.4 s is 10 samples, 0.5 s is 12.5 -> 12, 0.2 s is 5.
        for window_s in (0.4, 0.5, 0.2):
            _run({"method": "savgol", "window_s": window_s}, _datetime_x(t_seconds), t_seconds)

        assert seen == [11, 13, 5]

    def test_a_window_no_longer_than_the_polynomial_returns_the_input_and_says_so(self, caplog):
        t_seconds = np.arange(0, 20, 1.0)
        y = np.random.default_rng(1).normal(0, 1, len(t_seconds))

        with caplog.at_level(logging.INFO, logger="clinical_scope.transforms.filters"):
            _, y_out = _run({"method": "savgol", "window_s": 0.5}, _datetime_x(t_seconds), y)

        assert np.array_equal(y_out, y)
        assert "savgol" in caplog.text
        assert "unsmoothed" in caplog.text

    def test_polyorder_one_with_a_three_sample_window_still_smooths(self):
        """The window is long enough for the polynomial, so only n <= polyorder is skipped."""
        t_seconds = np.arange(0, 20, 1.0)
        y = np.random.default_rng(2).normal(0, 1, len(t_seconds))

        _, y_out = _run({"method": "savgol", "window_s": 3, "polyorder": 1}, _datetime_x(t_seconds), y)

        assert not np.allclose(y_out, y)

    def test_a_stretch_shorter_than_the_window_is_left_out(self):
        t_seconds = np.arange(0, 3, 0.04)

        with pytest.raises(ValueError, match="too short"):
            _run({"method": "savgol", "window_s": 10}, _datetime_x(t_seconds), t_seconds)


class TestMovingMedian:
    def test_removes_an_isolated_spike_and_keeps_the_timestamps(self):
        t_seconds = np.arange(0, 30, 1.0)
        x = _datetime_x(t_seconds)
        y = np.ones(len(t_seconds))
        y[15] = 100.0

        x_out, y_out = _run({"method": "moving_median", "window_s": 4}, x, y)

        assert np.array_equal(x_out, x)
        assert np.array_equal(y_out, np.ones(len(t_seconds)))

    def test_a_window_shorter_than_the_spacing_returns_the_input(self):
        t_seconds = np.arange(0, 30, 1.0)
        y = np.random.default_rng(3).normal(0, 1, len(t_seconds))

        _, y_out = _run({"method": "moving_median", "window_s": 0.1}, _datetime_x(t_seconds), y)

        assert np.array_equal(y_out, y)

    def test_does_not_bridge_a_gap_longer_than_its_window(self):
        t_seconds = np.concatenate([np.arange(0, 10, 1.0), np.arange(110, 120, 1.0)])
        y = np.where(t_seconds < 50, 0.0, 10.0)

        _, y_out = _run({"method": "moving_median", "window_s": 60}, _datetime_x(t_seconds), y)

        assert np.array_equal(y_out, y)

    def test_is_centred_so_it_neither_lags_nor_leads(self):
        t_seconds = np.arange(0, 100, 1.0)

        _, y_out = _run(
            {"method": "moving_median", "window_s": 2}, _datetime_x(t_seconds), t_seconds.copy()
        )

        assert np.allclose(y_out[2:-2], t_seconds[2:-2])


class TestDerivative:
    def test_a_ramp_has_its_slope_as_derivative(self):
        t_seconds = np.arange(0, 20, 0.04)

        _, y_out = _run(
            {"method": "derivative", "window_s": 0.5}, _datetime_x(t_seconds), 3.0 * t_seconds
        )

        assert np.allclose(y_out, 3.0)

    def test_window_zero_is_central_differences_edges_included(self):
        t_seconds = np.arange(0, 20, 0.04)
        y = np.sin(t_seconds) + 0.1 * t_seconds**2

        _, y_out = _run({"method": "derivative"}, _datetime_x(t_seconds), y)

        assert np.allclose(y_out, np.gradient(y, 0.04, edge_order=2))

    def test_the_default_window_is_zero(self):
        assert transforms.resolve({"method": "derivative"}).spec == {
            "method": "derivative",
            "window_s": 0,
        }

    def test_the_derivative_of_a_cosine_is_minus_a_sine(self):
        t_seconds = np.arange(0, 20, 0.01)

        _, y_out = _run(
            {"method": "derivative", "window_s": 0.1},
            _datetime_x(t_seconds),
            np.cos(t_seconds),
        )

        assert np.allclose(y_out[10:-10], -np.sin(t_seconds)[10:-10], atol=1e-3)

    def test_a_window_under_three_samples_is_raised_to_three_and_says_so(self, caplog):
        t_seconds = np.arange(0, 20, 1.0)

        with caplog.at_level(logging.INFO, logger="clinical_scope.transforms.filters"):
            _, y_out = _run(
                {"method": "derivative", "window_s": 0.5}, _datetime_x(t_seconds), 2.0 * t_seconds
            )

        assert np.allclose(y_out, 2.0)
        assert "derivative" in caplog.text
        assert "three" in caplog.text

    def test_no_output_exists_inside_a_gap_and_no_slope_crosses_it(self):
        t_seconds = np.concatenate([np.arange(0, 10, 0.1), np.arange(30, 40, 0.1)])
        y = np.where(t_seconds < 20, 0.0, 1000.0)

        x_out, y_out = _run({"method": "derivative"}, _datetime_x(t_seconds), y)

        t_out = (x_out - x_out[0]).astype("timedelta64[ms]").astype(np.int64) / 1000.0
        assert not np.any((t_out > 10) & (t_out < 30))
        assert np.allclose(y_out, 0.0)

    def test_a_stretch_shorter_than_the_window_is_left_out(self):
        t_seconds = np.arange(0, 2, 0.04)

        with pytest.raises(ValueError, match="too short"):
            _run({"method": "derivative", "window_s": 10}, _datetime_x(t_seconds), t_seconds)


class TestElementwise:
    def test_log10_keeps_only_positive_samples_at_their_timestamps(self):
        x = _datetime_x(np.arange(4.0))

        x_out, y_out = _run({"method": "log10"}, x, np.array([-1.0, 0.0, 10.0, 100.0]))

        assert np.array_equal(x_out, x[2:])
        assert y_out.tolist() == [1.0, 2.0]

    def test_ln(self):
        x = _datetime_x(np.arange(3.0))

        _, y_out = _run({"method": "ln"}, x, np.array([1.0, np.e, np.e**2]))

        assert np.allclose(y_out, [0.0, 1.0, 2.0])

    def test_exp_overflow_leaves_a_gap(self):
        x = _datetime_x(np.arange(3.0))

        x_out, y_out = _run({"method": "exp"}, x, np.array([0.0, 1.0, 1000.0]))

        assert np.array_equal(x_out, x[:2])
        assert np.allclose(y_out, [1.0, np.e])

    def test_abs_and_negate(self):
        x = _datetime_x(np.arange(3.0))
        y = np.array([-2.0, 0.0, 3.0])

        assert _run({"method": "abs"}, x, y)[1].tolist() == [2.0, 0.0, 3.0]
        assert _run({"method": "negate"}, x, y)[1].tolist() == [2.0, -0.0, -3.0]

    def test_no_numpy_warning_escapes(self):
        x = _datetime_x(np.arange(3.0))

        with np.errstate(all="raise"):
            _run({"method": "log10"}, x, np.array([-1.0, 0.0, 1.0]))
            _run({"method": "exp"}, x, np.array([0.0, 1.0, 1000.0]))

    def test_a_signal_with_no_positive_sample_fails_naming_the_method(self):
        x = _datetime_x(np.arange(3.0))

        with pytest.raises(ValueError, match="log10 produced no finite value"):
            _run({"method": "log10"}, x, np.array([-1.0, 0.0, -5.0]))


class TestNormalisation:
    def test_zscore_has_mean_zero_and_unit_deviation(self):
        y = np.random.default_rng(4).normal(50, 7, 500)

        x_out, y_out = _run({"method": "zscore"}, _datetime_x(np.arange(500.0)), y)

        assert len(x_out) == 500
        assert y_out.mean() == pytest.approx(0.0, abs=1e-12)
        assert y_out.std() == pytest.approx(1.0)

    def test_zscore_of_a_known_series(self):
        _, y_out = _run({"method": "zscore"}, _datetime_x(np.arange(2.0)), np.array([1.0, 3.0]))

        assert y_out.tolist() == [-1.0, 1.0]

    def test_bare_minmax_spans_exactly_zero_to_one(self):
        y = np.array([10.0, 20.0, 15.0, 30.0])

        _, y_out = _run({"method": "minmax"}, _datetime_x(np.arange(4.0)), y)

        assert y_out.min() == 0.0
        assert y_out.max() == 1.0
        assert y_out.tolist() == [0.0, 0.5, 0.25, 1.0]

    def test_minmax_percentiles_do_not_clip_a_spike(self):
        y = np.concatenate([np.linspace(0.0, 1.0, 200), [50.0]])

        _, y_out = _run(
            {"method": "minmax", "low_pct": 1, "high_pct": 99},
            _datetime_x(np.arange(len(y), dtype=float)),
            y,
        )

        assert y_out[-1] > 10.0
        assert np.percentile(y_out, 1) == pytest.approx(0.0, abs=1e-12)
        assert np.percentile(y_out, 99) == pytest.approx(1.0, abs=1e-12)

    @pytest.mark.parametrize("method", ["zscore", "minmax"])
    def test_a_constant_signal_fails_naming_the_method(self, method):
        with pytest.raises(ValueError, match=method):
            _run({"method": method}, _datetime_x(np.arange(5.0)), np.full(5, 7.0))

    def test_the_statistics_come_from_the_samples_it_receives(self):
        """Shorten the series and the same row draws a different curve."""
        y = np.arange(10.0)
        x = _datetime_x(np.arange(10.0))

        full = _run({"method": "minmax"}, x, y)[1]
        half = _run({"method": "minmax"}, x[:5], y[:5])[1]

        assert full[4] == pytest.approx(4 / 9)
        assert half[4] == 1.0
