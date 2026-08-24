"""
Parquet read-pruning benchmark harness: datetime row pushdown and column pruning.

Measures wall-time and process memory of an ``other.main`` run on large synthetic
parquet fixtures. Each ``(shape, scenario)`` case is one run: the datetime-window
scenarios exercise row pushdown, and the ``partial_cols`` scenario exercises column pruning
(no window, ~1/4 of the columns configured). Validate a change before vs. after by a manual
``git stash`` A/B:

    python tests/benchmarks/bench_pushdown.py --size-gb 2 --out before.json   # git-stash state (HEAD)
    git stash pop                                                    # bring pruning back
    python tests/benchmarks/bench_pushdown.py --size-gb 2 --out after.json
    python tests/benchmarks/bench_pushdown.py --diff before.json after.json

The A/B — not a cold cache — is what makes the numbers trustworthy. Both runs execute the
identical script and regenerate identical fixtures, so every ``(shape, scenario)`` cell sits
at the same point in the same file-access sequence and therefore carries the *same* OS
page-cache temperature in both arms; that nuisance term cancels in the before/after ratio, so
no cache drop (``sudo purge``) is needed. The tradeoff: with the file warm in both arms the
ratio counts CPU + memory-bandwidth savings but omits the disk-read savings of a true cold
first load, so it is a conservative *lower bound* on the real-world win.

Design constraints (do not break these — they are what makes the stash A/B valid):

* It drives only ``DataSource.main(patient_options, database_options)`` — the public entry
  point, never a pruning internal (``read_parquet_pruned``, ``_pruned_columns``,
  ``compute_bounds``, ``ALLOW_DATETIME_PUSHDOWN``), so the same script runs unchanged
  against an older baseline. ``other`` is the only datasource left that pushes a window
  and a column set into a *source* parquet read on every run; it has no ``extract()``, so
  the measurement necessarily includes Signal materialization on top of the read. That
  overhead is identical in both arms of an A/B, and moves in the same direction as the
  read itself (fewer rows read = fewer points materialized).
* Each case is measured in a fresh ``spawn`` subprocess, so peak RSS starts from a clean
  interpreter and pyarrow's memory pool from one case can't bleed into the next. (It does
  *not* reset the OS page cache, which is process-independent — hence the A/B note above.)
* Peak memory is sampled from process RSS (psutil), not ``tracemalloc`` — pyarrow allocates
  its read buffers in C++ off the Python heap, which ``tracemalloc`` never sees.

``psutil`` is a dev-only dependency (see the ``dev`` extra); it is never bundled into the
shipped executable, whose venv is built separately.
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# --- fixture shape / scenario names (a change here ripples into the JSON keys) -------------
SHAPE_STORED_INDEX = "stored_index"  # materialized DatetimeIndex → fast pushdown path
SHAPE_DETECT_COLUMN = "detect_column"  # RangeIndex + datetime column → detection path
SHAPES = (SHAPE_STORED_INDEX, SHAPE_DETECT_COLUMN)

SCENARIO_NO_WINDOW = "no_window"  # regression sentinel: pushdown can only add overhead here
SCENARIO_LARGE_WINDOW = "large_window"  # testing if detection is efficient
SCENARIO_TIGHT = "tight"  # ~5% two-sided window: where pruning should pay off most
SCENARIO_OUTSIDE = "outside_range"  # window before all data: everything prunes away
SCENARIO_PARTIAL_COLS = "partial_cols"  # no-window column-pruning case
SCENARIOS = (
    SCENARIO_PARTIAL_COLS,
    SCENARIO_NO_WINDOW,
    SCENARIO_LARGE_WINDOW,
    SCENARIO_TIGHT,
    SCENARIO_OUTSIDE,
)

_COLUMN_KEEP_FRACTION = 4  # partial_cols configures 1/this of the value columns

_DATASOURCE = "other"  # no quick-load cache, reads the raw file every run
_FIXTURE_STEM = "bench"  # the other::<stem> token the fixture file is configured under
_DT_COLUMN = "timestamp"  # detect_column shape: the column detection must discover
_BYTES_PER_CELL = 8  # float64 value cells and the int64 timestamp


# ==================================================================================================
# Fixture generation
# ==================================================================================================
def _rows_for_size(size_gb: float, num_columns: int) -> int:
    """Row count whose fully-read in-memory footprint is ~*size_gb* (on-disk is smaller)."""
    bytes_per_row = (num_columns + 1) * _BYTES_PER_CELL
    return max(1, int(size_gb * 1e9 / bytes_per_row))


def _generate_fixture(
    path: Path,
    *,
    shape: str,
    total_rows: int,
    num_columns: int,
    row_group_size: int,
    freq: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Write a time-sorted parquet fixture, one row group per *row_group_size* rows.

    Generated in chunks via a single ``ParquetWriter`` so a multi-GB file never has to
    exist in memory at once, and so row-group count (the granularity pushdown prunes at)
    is controlled rather than left to pandas' default. Returns the ``(min, max)``
    timestamps, used to place the benchmark windows inside the real data range.
    """
    rng = np.random.default_rng(0)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer: pq.ParquetWriter | None = None
    start = pd.Timestamp("2020-01-01", tz="UTC")
    t_min = t_max = start
    written = 0
    try:
        while written < total_rows:
            n = min(row_group_size, total_rows - written)
            ts = pd.date_range(start, periods=n, freq=freq)
            values = {f"col_{c}": rng.random(n) for c in range(num_columns)}
            if shape == SHAPE_STORED_INDEX:
                chunk = pd.DataFrame(values, index=pd.DatetimeIndex(ts, name=_DT_COLUMN))
                table = pa.Table.from_pandas(chunk, preserve_index=True)
            else:
                chunk = pd.DataFrame({_DT_COLUMN: ts, **values})
                table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema)
            writer.write_table(table, row_group_size=row_group_size)

            if written == 0:
                t_min = ts[0]
            t_max = ts[-1]
            start = ts[-1] + (ts[1] - ts[0])  # continue monotonically into the next chunk
            written += n
    finally:
        if writer is not None:
            writer.close()
    return t_min, t_max


def _build_patient_folder(
    root: Path,
    *,
    shape: str,
    total_rows: int,
    num_columns: int,
    row_group_size: int,
    freq: str,
) -> tuple[Path, pd.Timestamp, pd.Timestamp]:
    """Lay out a ``<patient>/other/bench.parquet`` fixture that the pipeline can find."""
    patient_dir = root / f"patient_{shape}"
    fixture = patient_dir / _DATASOURCE / f"{_FIXTURE_STEM}.parquet"
    t_min, t_max = _generate_fixture(
        fixture,
        shape=shape,
        total_rows=total_rows,
        num_columns=num_columns,
        row_group_size=row_group_size,
        freq=freq,
    )
    return patient_dir, t_min, t_max


def _window_for_scenario(scenario: str, t_min: pd.Timestamp, t_max: pd.Timestamp) -> dict[str, str]:
    """Return the ``datetime_start``/``datetime_end`` patient-option keys for *scenario*."""
    # Both read the full row range; partial_cols carries no window so it isolates column pruning.
    if scenario in (SCENARIO_NO_WINDOW, SCENARIO_PARTIAL_COLS):
        return {}
    span = t_max - t_min
    if scenario == SCENARIO_LARGE_WINDOW:
        start = t_min + span * 0.005
        end = t_min + span * 0.9
    elif scenario == SCENARIO_TIGHT:
        start = t_min + span * 0.475
        end = t_min + span * 0.525
    elif scenario == SCENARIO_OUTSIDE:  # fully before the data → everything prunes away
        start = t_min - pd.Timedelta(days=10)
        end = t_min - pd.Timedelta(days=5)
    else:
        msg = f"unknown scenario: {scenario!r}"
        raise ValueError(msg)
    # Naive wall-clock strings + display_timezone=UTC, mirroring the real UI/config path.
    fmt = "%Y-%m-%d %H:%M:%S"
    return {
        "datetime_start": start.tz_convert("UTC").strftime(fmt),
        "datetime_end": end.tz_convert("UTC").strftime(fmt),
    }


def _database_options_for_scenario(scenario: str, num_columns: int) -> dict:
    """
    Return the ``database_options`` (2nd ``main`` arg) for *scenario*.

    Only ``partial_cols`` configures a ``field_display`` — ~1/``_COLUMN_KEEP_FRACTION`` of the
    value columns, by bare name (``col_0 … col_{N-1}``, both shapes), mirroring a real signal
    config. The datetime axis is never listed; the reader re-adds it, so the time column always
    survives. A baseline predating column pruning ignores this key and reads every column —
    which is exactly what makes the before/after a valid A/B for column pruning.
    """
    if scenario != SCENARIO_PARTIAL_COLS:
        return {}
    keep = max(1, num_columns // _COLUMN_KEEP_FRACTION)
    # 'other' reads per-file config from the "files" slot, keyed by file stem.
    return {"files": {_FIXTURE_STEM: {"field_display": [f"col_{i}" for i in range(keep)]}}}


# ==================================================================================================
# Measurement (one fresh subprocess per case → clean peak RSS)
# ==================================================================================================
def _measure_worker(
    queue: mp.Queue, patient_dir: str, window: dict[str, str], database_options: dict
) -> None:
    """Run a single windowed load, reporting time + RSS back through *queue*."""
    # Worker-local so the parent process and `--diff` mode stay light: no psutil (dev-only dep)
    # and no clinical_scope import until a case is actually measured in this spawned subprocess.
    import psutil  # noqa: PLC0415

    from clinical_scope.datasource.registry import DataSource  # noqa: PLC0415

    # main() logs a full traceback when a file yields nothing (e.g. a window that prunes every
    # row on the detect_column shape); silence it so the benchmark's output stays readable.
    logging.getLogger("clinical_scope").setLevel(logging.CRITICAL)

    proc = psutil.Process()
    baseline = proc.memory_info().rss
    peak = baseline
    stop = threading.Event()

    def _sample() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, proc.memory_info().rss)
            time.sleep(0.005)

    sampler = threading.Thread(target=_sample, daemon=True)
    sampler.start()

    datasource = DataSource.get_subclass_by_name(_DATASOURCE).DATASOURCE_CLASS
    patient_options = {
        "data_folder": patient_dir,
        "display_timezone": "UTC",
        "quick_load": False,
        **window,
    }
    t0 = time.perf_counter()
    signals = datasource.main(patient_options, database_options)
    elapsed = time.perf_counter() - t0
    retained = proc.memory_info().rss

    stop.set()
    sampler.join()
    queue.put(
        {
            "time_s": elapsed,
            "peak_mb": peak / 1e6,
            "retained_mb": retained / 1e6,
            "baseline_mb": baseline / 1e6,
            "rows": max((len(sig.data.x) for sig in signals), default=0),
            "ok": bool(signals),  # empty = the window pruned every row, not "0 rows read"
        }
    )


def _measure_case(patient_dir: Path, window: dict[str, str], database_options: dict) -> dict:
    """Measure one (shape x scenario) case in an isolated spawn subprocess."""
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    worker = ctx.Process(
        target=_measure_worker, args=(queue, str(patient_dir), window, database_options)
    )
    worker.start()
    result = queue.get()  # blocks until the worker reports (or dies → surfaces as an error)
    worker.join()
    return result


# ==================================================================================================
# Reporting
# ==================================================================================================
def _git_revision() -> str:
    """Best-effort ``<short-sha>[-dirty]`` so a saved run records which code produced it."""
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        sha = subprocess.check_output(  # noqa: S603 — git path from shutil.which, args are literals
            [git, "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.call(  # noqa: S603
            [git, "diff", "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def _print_table(results: list[dict]) -> None:
    """Print the per-case metrics as an aligned text table."""
    header = (
        f"{'shape':<14}{'scenario':<15}{'rows':>12}{'time_s':>10}{'peak_MB':>11}{'final_MB':>11}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        rows = f"{r['rows']:,}" if r.get("ok", True) else "None"
        print(
            f"{r['shape']:<14}{r['scenario']:<15}{rows:>12}"
            f"{r['time_s']:>10.3f}{r['peak_mb']:>11.1f}{r['retained_mb']:>11.1f}"
        )
    if any(not r.get("ok", True) for r in results):
        print("\n('None' = no signal survived; see the detect_column empty-window note.)")


def _run(args: argparse.Namespace) -> None:
    """Generate fixtures, measure every (shape x scenario), print + optionally save."""
    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    total_rows = _rows_for_size(args.size_gb, args.num_columns)

    print(
        f"Generating fixtures in {workdir} "
        f"(~{args.size_gb} GB in-memory each, {total_rows:,} rows x "
        f"{args.num_columns} cols, row_group_size={args.row_group_size:,})",
        flush=True,
    )

    results: list[dict] = []
    for shape in SHAPES:
        patient_dir, t_min, t_max = _build_patient_folder(
            workdir,
            shape=shape,
            total_rows=total_rows,
            num_columns=args.num_columns,
            row_group_size=args.row_group_size,
            freq=args.freq,
        )
        for scenario in SCENARIOS:
            window = _window_for_scenario(scenario, t_min, t_max)
            db_options = _database_options_for_scenario(scenario, args.num_columns)
            print(f"  measuring {shape} / {scenario} ...", flush=True)
            metrics = _measure_case(patient_dir, window, db_options)
            results.append({"shape": shape, "scenario": scenario, **metrics})

    print()
    _print_table(results)

    if args.out:
        payload = {
            "git_revision": _git_revision(),
            "generated_at": datetime.now(UTC).isoformat(),
            "params": {
                "size_gb": args.size_gb,
                "num_columns": args.num_columns,
                "row_group_size": args.row_group_size,
                "freq": args.freq,
            },
            "results": results,
        }
        Path(args.out).write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {args.out}")

    if not args.keep_fixtures:
        for shape in SHAPES:
            shutil.rmtree(workdir / f"patient_{shape}", ignore_errors=True)


def _diff(before_path: str, after_path: str) -> None:
    """Print speedup / memory-ratio between two saved runs, aligned by (shape, scenario)."""
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    print(f"before: {before['git_revision']}   after: {after['git_revision']}\n")

    idx = {(r["shape"], r["scenario"]): r for r in before["results"]}
    header = (
        f"{'shape':<14}{'scenario':<15}{'time x':>9}{'peak x':>9}{'before_MB':>11}{'after_MB':>10}"
    )
    print(header)
    print("-" * len(header))
    for a in after["results"]:
        b = idx.get((a["shape"], a["scenario"]))
        if b is None:
            continue
        # x > 1 means "after" is better (faster / less memory).
        time_x = b["time_s"] / a["time_s"] if a["time_s"] else float("nan")
        peak_x = b["peak_mb"] / a["peak_mb"] if a["peak_mb"] else float("nan")
        print(
            f"{a['shape']:<14}{a['scenario']:<15}{time_x:>9.2f}{peak_x:>9.2f}"
            f"{b['peak_mb']:>11.1f}{a['peak_mb']:>10.1f}"
        )
    print(
        "\n(x > 1.0 = after is faster / lighter; row pruning wins on 'tight', "
        "column pruning on 'partial_cols'.)"
    )


# ==================================================================================================
def main() -> None:
    """Parse arguments and dispatch to a measurement run or a diff of two saved runs."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--size-gb", type=float, default=0.5, help="approx in-memory size per fixture"
    )
    parser.add_argument(
        "--num-columns", type=int, default=8, help="value columns besides the timestamp"
    )
    parser.add_argument(
        "--row-group-size", type=int, default=128_000, help="rows per parquet row group"
    )
    parser.add_argument("--freq", default="100ms", help="sample spacing (pandas offset alias)")
    parser.add_argument("--out", help="write metrics JSON here (for later --diff)")
    parser.add_argument(
        "--workdir",
        default=str(Path(tempfile.gettempdir()) / "clinical_scope_bench"),
        help="where the (multi-GB) fixtures are generated; kept out of the repo by default",
    )
    parser.add_argument(
        "--keep-fixtures", action="store_true", help="do not delete fixtures afterwards"
    )
    parser.add_argument(
        "--diff", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two saved runs and exit"
    )
    args = parser.parse_args()

    if args.diff:
        _diff(*args.diff)
        return
    _run(args)


if __name__ == "__main__":
    main()
