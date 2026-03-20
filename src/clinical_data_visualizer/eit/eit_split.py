#!/usr/bin/env python3
"""
Split a Draeger .eit file at a given time point.

Produces two .eit files from a single input, splitting at the specified time
(relative to recording start). Both output files retain the original binary
header so that Draeger software can read them.

Usage:
    python eit_split.py input.eit --at 01:30:00
    python eit_split.py input.eit --at auto
    python eit_split.py input.eit --at auto -o /output/dir/prefix
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

FRAME_SIZE = 5495  # bytes per frame for Format 51
CALIBRATION_FT = (0.00098242, 0.00019607)


def _parse_time(time_str: str) -> float | str:
    """Parse a time string (HH:MM:SS, seconds, or 'auto')."""
    if time_str.lower() == "auto":
        return "auto"
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        msg = f"Invalid time format: {time_str!r} (expected HH:MM:SS, MM:SS, or 'auto')"
        raise ValueError(msg)
    return float(time_str)


def _format_time(seconds: float) -> str:
    """Format seconds as HHhMMmSSs for filenames."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h:02d}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def _format_time_display(seconds: float) -> str:
    """Format seconds as HH:MM:SS for display."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _read_eit_file(path: Path) -> tuple[bytes, int, np.ndarray, np.ndarray]:
    """
    Read an .eit file and return (header_bytes, n_frames, timestamps, voltages).

    Voltages are raw (600 doubles per frame), not calibrated.
    """
    with open(path, "rb") as f:
        data = f.read(8)
        fmt_ver = struct.unpack("<I", data[:4])[0]
        if fmt_ver != 51:
            print(f"Error: unsupported format version {fmt_ver} (expected 51)", file=sys.stderr)
            sys.exit(1)
        header_offset = struct.unpack("<I", data[4:8])[0]

        f.seek(0)
        header_bytes = f.read(header_offset)

        file_size = path.stat().st_size
        n_frames = (file_size - header_offset) // FRAME_SIZE
        if n_frames == 0:
            print("Error: no frames found in file", file=sys.stderr)
            sys.exit(1)

        timestamps = np.zeros(n_frames, dtype=np.float64)
        voltages = np.zeros((n_frames, 600), dtype=np.float64)

        for i in range(n_frames):
            frame_start = header_offset + i * FRAME_SIZE
            f.seek(frame_start + 8)
            timestamps[i] = struct.unpack("<d", f.read(8))[0]
            f.seek(frame_start + 16)
            voltages[i] = np.frombuffer(f.read(600 * 8), dtype="<f8")

    return header_bytes, n_frames, timestamps, voltages


def detect_state_change(
    timestamps: np.ndarray,
    voltages: np.ndarray,
    framerate: float = 30.0,
    window_seconds: float = 30.0,
) -> tuple[int, float, np.ndarray]:
    """
    Detect the most likely patient state change in raw EIT voltages.

    Uses a sliding window comparison on calibrated voltage means.
    A state change (repositioning, electrode adjustment) causes a sudden step
    in the mean voltage that is much larger than breathing oscillations.

    Args:
        timestamps: (n_frames,) fraction-of-day timestamps
        voltages: (n_frames, 600) raw voltages
        framerate: frames per second
        window_seconds: comparison window size (should span several breaths)

    Returns:
        (best_frame, score_at_best, all_scores)

    """
    n_frames = len(timestamps)
    window = int(window_seconds * framerate)

    if n_frames < 2 * window:
        print(
            f"Error: recording too short ({n_frames} frames) for auto-detection "
            f"(need at least {2 * window} frames = {2 * window_seconds:.0f}s)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Calibrate: v_cal = ft0 * v[:,:208] - ft1 * v[:,322:530]
    ft0, ft1 = CALIBRATION_FT
    v_cal = ft0 * voltages[:, :208] - ft1 * voltages[:, 322:530]

    # Per-frame summary: mean across all 208 channels
    signal = v_cal.mean(axis=1)

    # Cumulative sum for fast window means
    cumsum = np.cumsum(signal)
    cumsum = np.insert(cumsum, 0, 0.0)  # prepend 0 for easier indexing

    # For each candidate split point t in [window, n_frames - window]:
    #   left_mean  = mean(signal[t-window : t])
    #   right_mean = mean(signal[t : t+window])
    #   score = |left_mean - right_mean|
    scores = np.zeros(n_frames)
    for t in range(window, n_frames - window):
        left_mean = (cumsum[t] - cumsum[t - window]) / window
        right_mean = (cumsum[t + window] - cumsum[t]) / window
        scores[t] = abs(right_mean - left_mean)

    best_frame = int(np.argmax(scores))
    return best_frame, scores[best_frame], scores


def split_eit(
    input_path: Path,
    split_frame: int,
    timestamps: np.ndarray,
    header_bytes: bytes,
    n_frames: int,
    output_prefix: Path | None = None,
) -> tuple[Path, Path, int, int]:
    """
    Split a .eit file at the given frame index.

    Returns (path1, path2, n_frames_part1, n_frames_part2).
    """
    header_offset = len(header_bytes)

    # Read all frame data
    with open(input_path, "rb") as f:
        f.seek(header_offset)
        all_frames = f.read(n_frames * FRAME_SIZE)

    # Determine output paths
    t0_seconds = timestamps[0] * 86400
    split_seconds = timestamps[split_frame] * 86400 - t0_seconds

    if output_prefix is not None:
        out_dir = output_prefix.parent
        out_stem = output_prefix.name
    else:
        out_dir = input_path.parent
        out_stem = input_path.stem

    split_time_str = _format_time(split_seconds)
    path1 = out_dir / f"{out_stem}_00m00s-{split_time_str}.eit"
    path2 = out_dir / f"{out_stem}_{split_time_str}-end.eit"

    # Write part 1: header + frames [0, split_frame)
    n1 = split_frame
    with open(path1, "wb") as f:
        f.write(header_bytes)
        f.write(all_frames[: n1 * FRAME_SIZE])

    # Write part 2: header + frames [split_frame, n_frames)
    n2 = n_frames - split_frame
    with open(path2, "wb") as f:
        f.write(header_bytes)
        f.write(all_frames[split_frame * FRAME_SIZE :])

    return path1, path2, n1, n2


def main():
    parser = argparse.ArgumentParser(
        description="Split a Draeger .eit file at a given time point",
    )
    parser.add_argument("input", type=Path, help="Input .eit file")
    parser.add_argument(
        "--at",
        required=True,
        help="Split time: HH:MM:SS, MM:SS, seconds, or 'auto' to detect state change",
    )
    parser.add_argument(
        "-o",
        "--output-prefix",
        type=Path,
        default=None,
        help="Output path prefix (default: input stem). "
        "Files will be named {prefix}_00m00s-{split}.eit and {prefix}_{split}-end.eit",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=30.0,
        help="Window size in seconds for auto-detection (default: 30s). "
        "Should span several breath cycles.",
    )
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="Only detect and report the split point, don't write files.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Read the .eit file
    print(f"Reading {args.input.name}...", file=sys.stderr)
    header_bytes, n_frames, timestamps, voltages = _read_eit_file(args.input)
    t0 = timestamps[0] * 86400
    total_duration = timestamps[-1] * 86400 - t0
    print(f"  {n_frames} frames, {total_duration:.1f}s", file=sys.stderr)

    split_time = _parse_time(args.at)

    if split_time == "auto":
        # Auto-detect state change
        print(f"Detecting state change (window={args.window:.0f}s)...", file=sys.stderr)
        best_frame, best_score, scores = detect_state_change(
            timestamps, voltages, window_seconds=args.window
        )
        split_seconds = timestamps[best_frame] * 86400 - t0

        # Compute relative score: how many times larger than the median non-zero score
        nonzero_scores = scores[scores > 0]
        if len(nonzero_scores) > 0:
            relative_score = best_score / np.median(nonzero_scores)
        else:
            relative_score = 0.0

        print(
            f"  Best split: frame {best_frame + 1} at {_format_time_display(split_seconds)} "
            f"(score: {relative_score:.1f}x median)",
            file=sys.stderr,
        )

        if relative_score < 3.0:
            print(
                "  Warning: low confidence — score is less than 3x the median. "
                "The recording may not contain a clear state change.",
                file=sys.stderr,
            )

        split_frame = best_frame
    else:
        # Manual split time
        split_seconds = split_time
        # Find the frame at or after split_seconds
        elapsed = timestamps * 86400 - t0
        candidates = np.where(elapsed >= split_seconds)[0]
        if len(candidates) == 0:
            print(
                f"Error: split time {split_seconds:.1f}s exceeds recording "
                f"duration ({total_duration:.1f}s)",
                file=sys.stderr,
            )
            sys.exit(1)
        split_frame = int(candidates[0])
        if split_frame == 0:
            print("Error: split time is at the very start, nothing to split", file=sys.stderr)
            sys.exit(1)

    if args.detect_only:
        print("Detect-only mode, no files written.", file=sys.stderr)
        return

    # Perform the split
    print(f"Splitting at frame {split_frame + 1}...", file=sys.stderr)
    path1, path2, n1, n2 = split_eit(
        args.input, split_frame, timestamps, header_bytes, n_frames, args.output_prefix
    )

    print(f"  Part 1: {path1.name} ({n1} frames, {n1 / 30:.1f}s)", file=sys.stderr)
    print(f"  Part 2: {path2.name} ({n2} frames, {n2 / 30:.1f}s)", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
