"""
Annotation rendering benchmark: what a large annotation set costs, and what hiding it saves.

Measures the two callbacks that fire on *every* ``annotation-store`` change —
``render_annotations`` (which rebuilds ``layout.shapes`` / ``layout.annotations`` for every
visible graph) and ``update_annotation_list`` (which rebuilds the list panel) — across three
arms of the same fixture:

    visible      everything drawn: shape + text label
    labels_off   ``label_hidden`` on every annotation: shapes only
    hidden       ``hidden`` on every annotation: nothing drawn

Run it, read the table:

    python tests/benchmarks/bench_annotations.py
    python tests/benchmarks/bench_annotations.py --counts 100,1000,5000 --out after.json
    python tests/benchmarks/bench_annotations.py --diff before.json after.json

The headline number is **wire bytes**, not milliseconds. Python is not the bottleneck here —
a thousand annotations cost tens of milliseconds to build — but each one becomes a shape dict
serialised into a figure patch *per graph*, and then an SVG node plotly.js repaints on every
zoom and pan. The three arms exist to separate the two visibility controls: ``label_hidden``
removes the text, ``hidden`` removes everything.

What this does *not* measure, deliberately: the ``dcc.Store`` payload is unchanged by either
control. A hidden annotation is a flag, not a deletion — it still occupies browser memory and
is still hydrated on every callback. Hiding is a rendering saving only.

Design notes (why this is so much smaller than ``bench_pushdown.py``):

* The fixture is built in memory from ``Annotation`` objects, so there is nothing to generate
  on disk, nothing to clean up, and the whole run takes seconds rather than minutes.
* No subprocess isolation and no ``psutil``: the interesting resource is bytes on the wire,
  which ``Patch.to_plotly_json()`` reports exactly, not peak RSS. ``bench_pushdown`` needs
  both because pyarrow allocates its read buffers in C++, off the Python heap.
* It drives the real callbacks rather than the pure renderer functions, so the numbers include
  hydration and timezone normalisation exactly as a running app pays them.
* The fixture uses *global* time windows (``subplot_name is None``), matching the reported
  case that motivated the hide feature. Subplot-scoped annotations cost slightly more, since
  each one resolves its subplot by a linear scan of the row list.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from clinical_scope.dash_api.annotations.model import Annotation, AnnotationSet, AnnotationType
from clinical_scope.dash_api.callbacks.annotation_callbacks import (
    default_mode,
    render_annotations,
    update_annotation_list,
)

# --- arm names (a change here ripples into the JSON keys) ---------------------------------
ARM_VISIBLE = "visible"
ARM_LABELS_OFF = "labels_off"
ARM_HIDDEN = "hidden"
ARMS = (ARM_VISIBLE, ARM_LABELS_OFF, ARM_HIDDEN)

_ANNOTATED_PLOT = "time_series"  # the plot the fixture sits on
_GROUP_ID = "bench-group"
_GROUP_NAME = "Suctioning"
_DISPLAY_TZ = "Europe/Paris"
_WINDOW_SECONDS = 5  # each annotation spans this long
_WINDOW_SPACING = 10  # ... and starts this long after the previous one
_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


# ==================================================================================================
# Fixture
# ==================================================================================================
def _annotations(count: int, arm: str) -> list[dict]:
    """
    Build *count* global time windows in one group, flagged for *arm*.

    Returned as store dicts rather than objects: that is what the callbacks actually receive,
    so hydration cost lands inside the measurement where it belongs.
    """
    label_hidden = arm == ARM_LABELS_OFF
    hidden = arm == ARM_HIDDEN
    annotations = [
        Annotation(
            id=f"bench-{index}",
            type=AnnotationType.TIME_WINDOW,
            plot_name=_ANNOTATED_PLOT,
            data={
                "x0": (_BASE + timedelta(seconds=index * _WINDOW_SPACING)).isoformat(),
                "x1": (
                    _BASE + timedelta(seconds=index * _WINDOW_SPACING + _WINDOW_SECONDS)
                ).isoformat(),
                "xaxis": "x",
            },
            label=f"event {index}",
            subplot_name=None,  # global — the reported case
            group_id=_GROUP_ID,
            group_name=_GROUP_NAME,
            label_hidden=label_hidden,
            hidden=hidden,
        )
        for index in range(count)
    ]
    return AnnotationSet(annotations).to_dicts()


def _graph_inputs(graphs: int, subplots: int) -> tuple[list[dict], list[dict]]:
    """
    Return the ``graph_ids`` / ``subplots_list`` states for *graphs* plots on screen.

    Only the first carries the fixture: an annotation names one ``plot_name``, and a group of
    time windows lives on the time-series plot. The rest are the other plot types a run
    produces (loop, spectrogram, psd, …), which ``render_annotations`` still walks and patches
    on every store change even though none of them draws an annotation.
    """
    rows = [
        {"row": index + 1, "col": 1, "name": f"Signal {index}", "yaxis": f"y{index + 1}"}
        for index in range(subplots)
    ]
    graph_ids = [{"name": _ANNOTATED_PLOT}] + [
        {"name": f"other_plot_{index}"} for index in range(graphs - 1)
    ]
    subplots_list = [
        {"plot_type": "time_series", "rows": rows, "subplot_annotations": [], "n_cols": 1}
        for _ in range(graphs)
    ]
    return graph_ids, subplots_list


# ==================================================================================================
# Measurement
# ==================================================================================================
def _best_ms(call, repeat: int) -> float:
    """Best-of-*repeat* wall time in ms — best, not mean, to suppress scheduler noise."""
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - start)
    return best * 1000


def _patch_bytes(patches: list) -> int:
    """Total JSON bytes the figure patches put on the wire, as Dash serialises them."""
    return sum(len(json.dumps(patch.to_plotly_json(), default=str)) for patch in patches)


def _shape_count(patches: list) -> int:
    """How many shapes the patches assign in total — 0 for a fully hidden arm."""
    total = 0
    for patch in patches:
        for operation in patch.to_plotly_json()["operations"]:
            if operation["location"] == ["layout", "shapes"]:
                total += len(operation["params"]["value"])
    return total


def _measure_render(stored: list, graphs: int, subplots: int, repeat: int) -> dict:
    """Time one full ``render_annotations`` pass and size the patches it produces."""
    graph_ids, subplots_list = _graph_inputs(graphs, subplots)
    mode = default_mode()

    def _call() -> list:
        return render_annotations(stored, mode, graph_ids, subplots_list, _DISPLAY_TZ, {})

    elapsed = _best_ms(_call, repeat)
    patches = _call()
    return {
        "render_ms": elapsed,
        "wire_kib": _patch_bytes(patches) / 1024,
        "shapes": _shape_count(patches),
    }


def _measure_list(stored: list, repeat: int) -> dict:
    """Time the list panel collapsed and expanded — collapsing is the pre-existing mitigation."""
    results = {}
    for state, expanded in (("collapsed", []), ("expanded", [_GROUP_ID])):
        results[f"list_{state}_ms"] = _best_ms(
            lambda expanded=expanded: update_annotation_list(stored, expanded, _DISPLAY_TZ), repeat
        )
        panel, _ = update_annotation_list(stored, expanded, _DISPLAY_TZ)
        results[f"list_{state}_rows"] = len(panel.children)
    return results


def _store_kib(stored: list) -> float:
    """The ``dcc.Store`` payload — identical in every arm, which is the point of reporting it."""
    return len(json.dumps(stored, default=str)) / 1024


# ==================================================================================================
# Reporting
# ==================================================================================================
def _git_revision() -> str:
    """
    Best-effort ``<short-sha>[-dirty]`` so a saved run records which code produced it.

    Duplicated from ``bench_pushdown.py`` rather than shared: each benchmark is a standalone
    script that must keep running when checked out at an older revision.
    """
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        # S603: the git path comes from shutil.which and every argument is a literal.
        sha = subprocess.check_output(  # noqa: S603
            [git, "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.call(  # noqa: S603
            [git, "diff", "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def _print_render_table(results: list[dict], graphs: int) -> None:
    """Print the per-(count, arm) render metrics."""
    header = (
        f"{'count':>7}{'arm':>12}{'shapes':>9}{'render_ms':>11}"
        f"{'wire_KiB':>11}{'per_annot_B':>13}"
    )
    print(f"(wire_KiB is the total across all {graphs} graphs, as Dash serialises the patches.)")
    print(header)
    print("-" * len(header))
    for row in results:
        per_annotation = row["wire_kib"] * 1024 / row["count"]
        print(
            f"{row['count']:>7}{row['arm']:>12}{row['shapes']:>9}"
            f"{row['render_ms']:>11.1f}{row['wire_kib']:>11.1f}{per_annotation:>13.0f}"
        )


def _print_list_table(results: list[dict]) -> None:
    """Print the per-count list-panel metrics (identical across arms, so measured once)."""
    header = (
        f"{'count':>7}{'store_KiB':>11}{'collapsed_ms':>14}{'collapsed_rows':>16}"
        f"{'expanded_ms':>13}{'expanded_rows':>15}"
    )
    print(header)
    print("-" * len(header))
    for row in results:
        print(
            f"{row['count']:>7}{row['store_kib']:>11.1f}{row['list_collapsed_ms']:>14.1f}"
            f"{row['list_collapsed_rows']:>16}{row['list_expanded_ms']:>13.1f}"
            f"{row['list_expanded_rows']:>15}"
        )


def _run(args: argparse.Namespace) -> None:
    """Measure every (count, arm), print both tables, optionally save."""
    counts = [int(token) for token in args.counts.split(",")]
    print(
        f"Rendering {args.graphs} graph(s) of {args.subplots} subplots each, "
        f"best of {args.repeat} runs\n"
    )

    render_results: list[dict] = []
    list_results: list[dict] = []
    for count in counts:
        for arm in ARMS:
            stored = _annotations(count, arm)
            metrics = _measure_render(stored, args.graphs, args.subplots, args.repeat)
            render_results.append({"count": count, "arm": arm, **metrics})
        # The panel lists hidden annotations too, so its cost does not vary by arm.
        stored = _annotations(count, ARM_VISIBLE)
        list_results.append(
            {"count": count, "store_kib": _store_kib(stored), **_measure_list(stored, args.repeat)}
        )

    _print_render_table(render_results, args.graphs)
    print()
    _print_list_table(list_results)
    print(
        "\n(store_KiB is what the browser holds regardless of arm: hiding removes drawing, "
        "not storage.)"
    )

    if args.out:
        payload = {
            "git_revision": _git_revision(),
            "generated_at": datetime.now(UTC).isoformat(),
            "params": {
                "counts": counts,
                "graphs": args.graphs,
                "subplots": args.subplots,
                "repeat": args.repeat,
            },
            "render": render_results,
            "list": list_results,
        }
        Path(args.out).write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {args.out}")


def _diff(before_path: str, after_path: str) -> None:
    """Print time / payload ratios between two saved runs, aligned by (count, arm)."""
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    print(f"before: {before['git_revision']}   after: {after['git_revision']}\n")

    index = {(row["count"], row["arm"]): row for row in before["render"]}
    header = (
        f"{'count':>7}{'arm':>12}{'render x':>11}"
        f"{'wire x':>9}{'before_KiB':>12}{'after_KiB':>11}"
    )
    print(header)
    print("-" * len(header))
    for row in after["render"]:
        previous = index.get((row["count"], row["arm"]))
        if previous is None:
            continue
        # x > 1 means "after" is better (faster / smaller).
        render_x = previous["render_ms"] / row["render_ms"] if row["render_ms"] else float("nan")
        wire_x = previous["wire_kib"] / row["wire_kib"] if row["wire_kib"] else float("inf")
        print(
            f"{row['count']:>7}{row['arm']:>12}{render_x:>11.2f}{wire_x:>9.2f}"
            f"{previous['wire_kib']:>12.1f}{row['wire_kib']:>11.1f}"
        )
    print("\n(x > 1.0 = after is faster / lighter; inf = after puts nothing on the wire.)")


# ==================================================================================================
def main() -> None:
    """Parse arguments and dispatch to a measurement run or a diff of two saved runs."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--counts", default="100,500,1000,5000", help="comma-separated annotation counts"
    )
    parser.add_argument("--graphs", type=int, default=8, help="how many plots are on screen")
    parser.add_argument("--subplots", type=int, default=6, help="subplots per plot")
    parser.add_argument("--repeat", type=int, default=3, help="runs per measurement (best wins)")
    parser.add_argument("--out", help="write metrics JSON here (for later --diff)")
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
