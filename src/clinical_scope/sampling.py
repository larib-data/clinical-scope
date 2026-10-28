"""
Putting a time series on a uniform grid, and finding the stretches of it that hold data.

Shared by spectral plots and transforms: both need evenly spaced samples, and neither may
fabricate data across a recording gap.
"""

import numpy as np

import clinical_scope.constants as cst


class TooFewSamplesError(ValueError):
    """A series too short to infer a sampling step from."""


def build_uniform_grid(
    x: np.ndarray,
    y: np.ndarray,
    jitter_tolerance: float = cst.Sampling.JITTER_TOLERANCE,
    gap_factor: float = cst.Sampling.GAP_FACTOR,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Return ``(x_uniform, y_uniform, dt_seconds)`` on a grid ready for an FFT or a filter.

    ``x`` must already be sorted, unique datetime64 values with ``y`` NaN-free
    (callers drop NaNs before this). Gaps (a step past ``gap_factor`` times the
    median) are masked as NaN rather than interpolated across, so nothing downstream
    fabricates data over e.g. a lead disconnect. Jitter within ``jitter_tolerance``
    of the median step is treated as already uniform and returned unchanged; beyond
    that, the whole series is linearly interpolated onto a grid at the median step.
    """
    if len(x) < 2:  # noqa: PLR2004
        msg = "Need at least 2 samples to build a uniform grid."
        raise TooFewSamplesError(msg)

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


def contiguous_segments(y: np.ndarray) -> list[slice]:
    """
    The runs of non-NaN values in *y*, in order, as slices into it.

    A gap :func:`build_uniform_grid` masked splits the series here, so each stretch can be
    processed on its own and nothing on one side of a gap shapes the other.
    """
    # Padded with False at both ends so every run has a rising and a falling edge.
    has_data = np.concatenate(([False], ~np.isnan(y), [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(has_data))
    return [slice(start, stop) for start, stop in zip(edges[::2], edges[1::2], strict=True)]
