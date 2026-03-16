#!/usr/bin/env python3
"""
Split a Draeger .eit file at a given time point.

Produces two .eit files from a single input, splitting at the specified time
(relative to recording start). Both output files retain the original binary
header so that Draeger software can read them.

Usage:
    python eit_split.py input.eit --at 01:30:00
    python eit_split.py input.eit --at 01:30:00 -o /output/dir/prefix
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

FRAME_SIZE = 5495  # bytes per frame for Format 51


def _parse_time(time_str: str) -> float:
    """Parse a time string (HH:MM:SS or seconds) to seconds."""
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        msg = f"Invalid time format: {time_str!r} (expected HH:MM:SS or MM:SS)"
        raise ValueError(msg)
    return float(time_str)


def _format_time(seconds: float) -> str:
    """Format seconds as HHhMMm for filenames."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h:02d}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def split_eit(
    input_path: Path,
    split_seconds: float,
    output_prefix: Path | None = None,
) -> tuple[Path, Path]:
    """
    Split a .eit file at the given time offset (seconds from recording start).

    Returns the two output file paths.
    """
    with open(input_path, "rb") as f:
        # Read format version and header offset
        data = f.read(8)
        fmt_ver = struct.unpack("<I", data[:4])[0]
        if fmt_ver != 51:
            print(f"Error: unsupported format version {fmt_ver} (expected 51)", file=sys.stderr)
            sys.exit(1)
        header_offset = struct.unpack("<I", data[4:8])[0]

        # Read full header
        f.seek(0)
        header_bytes = f.read(header_offset)

        # Count frames and read timestamps
        file_size = input_path.stat().st_size
        n_frames = (file_size - header_offset) // FRAME_SIZE
        if n_frames == 0:
            print("Error: no frames found in file", file=sys.stderr)
            sys.exit(1)

        # Read first timestamp to compute relative times
        f.seek(header_offset + 8)
        t0 = struct.unpack("<d", f.read(8))[0]
        t0_day_seconds = t0 * 86400  # timestamps are fraction-of-day

        # Find the split frame by scanning timestamps
        split_frame = None
        for i in range(n_frames):
            f.seek(header_offset + i * FRAME_SIZE + 8)
            t = struct.unpack("<d", f.read(8))[0]
            elapsed = t * 86400 - t0_day_seconds
            if elapsed >= split_seconds:
                split_frame = i
                break

        if split_frame is None:
            total_duration = n_frames / 30.0  # approximate
            # Read actual last timestamp
            f.seek(header_offset + (n_frames - 1) * FRAME_SIZE + 8)
            t_last = struct.unpack("<d", f.read(8))[0]
            total_duration = t_last * 86400 - t0_day_seconds
            print(
                f"Error: split time {split_seconds:.1f}s exceeds recording duration "
                f"({total_duration:.1f}s, {n_frames} frames)",
                file=sys.stderr,
            )
            sys.exit(1)

        if split_frame == 0:
            print("Error: split time is at the very start, nothing to split", file=sys.stderr)
            sys.exit(1)

        # Read all frame data
        f.seek(header_offset)
        all_frames = f.read(n_frames * FRAME_SIZE)

    # Determine output paths
    stem = input_path.stem
    if output_prefix is not None:
        out_dir = output_prefix.parent
        out_stem = output_prefix.name
    else:
        out_dir = input_path.parent
        out_stem = stem

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
        help="Split time relative to recording start (HH:MM:SS, MM:SS, or seconds)",
    )
    parser.add_argument(
        "-o",
        "--output-prefix",
        type=Path,
        default=None,
        help="Output path prefix (default: input stem). "
        "Files will be named {prefix}_00m00s-{split}.eit and {prefix}_{split}-end.eit",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    split_seconds = _parse_time(args.at)
    print(f"Splitting {args.input.name} at {split_seconds:.1f}s...", file=sys.stderr)

    path1, path2, n1, n2 = split_eit(args.input, split_seconds, args.output_prefix)

    print(f"  Part 1: {path1.name} ({n1} frames, {n1 / 30:.1f}s)", file=sys.stderr)
    print(f"  Part 2: {path2.name} ({n2} frames, {n2 / 30:.1f}s)", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
