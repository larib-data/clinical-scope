#!/usr/bin/env python3
"""Convert Draeger .eit files to .asc format.

Self-contained script that reads raw EIT voltage data from Draeger .eit files
(Format 51), performs linearized image reconstruction, and writes a Draeger-
compatible .asc file.

Usage:
    python eit_to_asc.py input1.eit [input2.eit ...] -o output.asc
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import Delaunay
from scipy.sparse import csr_matrix, lil_matrix
from scipy.sparse.linalg import spsolve


# ---------------------------------------------------------------------------
# 1. EIT File Parser
# ---------------------------------------------------------------------------

FRAME_SIZE = 5495  # bytes per frame for Format 51
CALIBRATION_FT = (0.00098242, 0.00019607)


@dataclass
class EITHeader:
    format_version: int
    header_offset: int
    framerate: float
    device_serial: str
    filename: str
    date: str
    time: str
    patient_id: str


@dataclass
class EITData:
    header: EITHeader
    timestamps: NDArray[np.float64]
    voltages: NDArray[np.float64]  # (n_frames, 600)
    medibus: NDArray[np.float32]  # (n_frames, 67)
    events: list[str]
    counters: NDArray[np.uint16]


def parse_header(path: Path) -> EITHeader:
    """Parse .eit file header."""
    with open(path, "rb") as f:
        data = f.read(8)
        fmt_ver = struct.unpack("<I", data[:4])[0]
        if fmt_ver != 51:
            raise ValueError(f"Unsupported format version {fmt_ver} (expected 51)")
        header_offset = struct.unpack("<I", data[4:8])[0]

        f.seek(0)
        header_bytes = f.read(min(header_offset, 4096))
        header_text = header_bytes.decode("latin-1", errors="replace")

    def _extract(text: str, key: str) -> str:
        for line in text.split("\r\n"):
            if line.strip().startswith(key):
                return line.split(":", 1)[1].strip() if ":" in line else ""
        return ""

    return EITHeader(
        format_version=fmt_ver,
        header_offset=header_offset,
        framerate=float(_extract(header_text, "Framerate [Hz]") or "30"),
        device_serial=_extract(header_text, "Device Serial Nr."),
        filename=_extract(header_text, "Filename"),
        date=_extract(header_text, "Date"),
        time=_extract(header_text, "Time"),
        patient_id=_extract(header_text, "Patient ID"),
    )


def read_frames(path: Path, header: EITHeader) -> EITData:
    """Read all frames from a .eit file."""
    file_size = path.stat().st_size
    n_frames = (file_size - header.header_offset) // FRAME_SIZE

    timestamps = np.zeros(n_frames, dtype=np.float64)
    voltages = np.zeros((n_frames, 600), dtype=np.float64)
    medibus = np.zeros((n_frames, 67), dtype=np.float32)
    events = []
    counters = np.zeros(n_frames, dtype=np.uint16)

    with open(path, "rb") as f:
        for i in range(n_frames):
            frame_start = header.header_offset + i * FRAME_SIZE
            # Timestamp at +8
            f.seek(frame_start + 8)
            timestamps[i] = struct.unpack("<d", f.read(8))[0]
            # 600 voltage doubles at +16
            f.seek(frame_start + 16)
            voltages[i] = np.frombuffer(f.read(600 * 8), dtype="<f8")
            # 67 medibus singles at +5169
            f.seek(frame_start + 5169)
            medibus[i] = np.frombuffer(f.read(67 * 4), dtype="<f4")
            # Event text at +5437
            f.seek(frame_start + 5437)
            events.append(f.read(30).decode("latin-1", errors="replace").rstrip("\x00"))
            # Counter at +5491
            f.seek(frame_start + 5491)
            counters[i] = struct.unpack("<H", f.read(2))[0]

    return EITData(
        header=header,
        timestamps=timestamps,
        voltages=voltages,
        medibus=medibus,
        events=events,
        counters=counters,
    )


def load_eit_files(paths: list[Path]) -> EITData:
    """Load and concatenate multiple .eit files."""
    datasets = []
    for p in paths:
        header = parse_header(p)
        data = read_frames(p, header)
        datasets.append(data)
        print(f"  Loaded {p.name}: {len(data.timestamps)} frames", file=sys.stderr)

    if len(datasets) == 1:
        return datasets[0]

    return EITData(
        header=datasets[0].header,
        timestamps=np.concatenate([d.timestamps for d in datasets]),
        voltages=np.concatenate([d.voltages for d in datasets]),
        medibus=np.concatenate([d.medibus for d in datasets]),
        events=sum((d.events for d in datasets), []),
        counters=np.concatenate([d.counters for d in datasets]),
    )


def calibrate_voltages(voltages: NDArray) -> NDArray:
    """Apply EIDORS calibration: v_cal[i] = ft[0]*vv[i] - ft[1]*vv[322+i]."""
    ft0, ft1 = CALIBRATION_FT
    return ft0 * voltages[:, :208] - ft1 * voltages[:, 322 : 322 + 208]


# ---------------------------------------------------------------------------
# 2. Forward Model & Reconstruction
# ---------------------------------------------------------------------------


def _generate_mesh(n_points_per_ring: int = 8, n_rings: int = 6) -> tuple[NDArray, NDArray, NDArray]:
    """Generate a 2D circular mesh with electrode nodes.

    Returns (nodes, elements, electrode_indices).
    """
    n_elec = 16
    points = [(0.0, 0.0)]

    # Interior rings
    for ring in range(1, n_rings + 1):
        r = ring / n_rings * 0.85  # keep interior points away from boundary
        n_pts = n_points_per_ring * ring
        for j in range(n_pts):
            theta = 2 * np.pi * j / n_pts
            points.append((r * np.cos(theta), r * np.sin(theta)))

    # Boundary ring (dense, includes electrode positions)
    n_boundary = max(64, n_elec * 4)
    electrode_angles = np.array([2 * np.pi * k / n_elec for k in range(n_elec)])
    boundary_angles = np.linspace(0, 2 * np.pi, n_boundary, endpoint=False)
    # Merge electrode angles into boundary
    all_boundary = np.sort(np.unique(np.concatenate([boundary_angles, electrode_angles])))

    electrode_indices = []
    for angle in all_boundary:
        x, y = np.cos(angle), np.sin(angle)
        points.append((x, y))
        # Check if this is an electrode
        for ea in electrode_angles:
            if abs(angle - ea) < 1e-10:
                electrode_indices.append(len(points) - 1)
                break

    nodes = np.array(points)
    tri = Delaunay(nodes)
    elements = tri.simplices

    # Filter elements outside unit circle (centroid check)
    centroids = nodes[elements].mean(axis=1)
    r2 = centroids[:, 0] ** 2 + centroids[:, 1] ** 2
    mask = r2 < 1.05  # slight tolerance
    elements = elements[mask]

    electrode_indices = np.array(electrode_indices[:n_elec])
    return nodes, elements, electrode_indices


def _compute_element_matrices(nodes: NDArray, elements: NDArray) -> tuple[list[NDArray], NDArray]:
    """Compute per-element stiffness matrix contributions and areas."""
    n_elem = len(elements)
    ke_list = []
    areas = np.zeros(n_elem)

    for e_idx in range(n_elem):
        n0, n1, n2 = elements[e_idx]
        x = nodes[[n0, n1, n2], 0]
        y = nodes[[n0, n1, n2], 1]

        # Area of triangle
        area = 0.5 * abs((x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0]))
        areas[e_idx] = area

        if area < 1e-15:
            ke_list.append(np.zeros((3, 3)))
            continue

        # Gradient of basis functions
        b = np.array([y[1] - y[2], y[2] - y[0], y[0] - y[1]])
        c = np.array([x[2] - x[1], x[0] - x[2], x[1] - x[0]])

        # Element stiffness: Ke = (1/(4*area)) * (b*b' + c*c')
        ke = (np.outer(b, b) + np.outer(c, c)) / (4 * area)
        ke_list.append(ke)

    return ke_list, areas


def _assemble_stiffness(
    nodes: NDArray,
    elements: NDArray,
    ke_list: list[NDArray],
    conductivity: NDArray,
) -> csr_matrix:
    """Assemble global stiffness matrix K for given conductivity distribution."""
    n_nodes = len(nodes)
    K = lil_matrix((n_nodes, n_nodes))

    for e_idx, elem in enumerate(elements):
        sigma = conductivity[e_idx]
        ke = ke_list[e_idx] * sigma
        for i in range(3):
            for j in range(3):
                K[elem[i], elem[j]] += ke[i, j]

    return K.tocsr()


def _solve_forward(
    K: csr_matrix,
    n_nodes: int,
    drive_node_a: int,
    drive_node_b: int,
    gnd_node: int,
) -> NDArray:
    """Solve forward problem: K @ u = I for given drive pattern."""
    # Current vector
    I_vec = np.zeros(n_nodes)
    I_vec[drive_node_a] = 1.0
    I_vec[drive_node_b] = -1.0

    # Ground node: fix voltage at gnd_node to 0
    # Modify system: replace gnd_node row with identity
    K_mod = K.tolil()
    K_mod[gnd_node, :] = 0
    K_mod[gnd_node, gnd_node] = 1.0
    I_vec[gnd_node] = 0.0

    u = spsolve(K_mod.tocsr(), I_vec)
    return u


def _compute_measurements(u: NDArray, electrode_indices: NDArray) -> NDArray:
    """Extract adjacent-pair voltage measurements from potential field.

    Returns 13 measurements (16 adjacent pairs minus 3 excluded).
    """
    n_elec = len(electrode_indices)
    meas = []
    for m in range(n_elec):
        m_a = electrode_indices[m]
        m_b = electrode_indices[(m + 1) % n_elec]
        meas.append(u[m_a] - u[m_b])
    return np.array(meas)


def build_reconstruction_matrix(
    regularization: float = 0.01,
) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Build the complete reconstruction pipeline.

    Returns (recon_matrix, pixel_map, nodes, elements).
    recon_matrix: (n_elements, 208) maps calibrated voltages to element conductivities
    pixel_map: (1024, n_elements) maps element values to 32x32 pixels
    """
    print("  Building FEM mesh...", file=sys.stderr)
    nodes, elements, electrode_indices = _generate_mesh(n_points_per_ring=10, n_rings=8)
    n_elem = len(elements)
    n_nodes = len(nodes)
    n_elec = 16
    print(f"  Mesh: {n_nodes} nodes, {n_elem} elements", file=sys.stderr)

    ke_list, areas = _compute_element_matrices(nodes, elements)

    # Homogeneous conductivity
    sigma0 = np.ones(n_elem)
    K0 = _assemble_stiffness(nodes, elements, ke_list, sigma0)

    # Ground node: first electrode
    gnd_node = electrode_indices[0]

    # Compute Jacobian via perturbation
    print("  Computing Jacobian...", file=sys.stderr)

    # First: get reference measurements for homogeneous case
    # Drive patterns: adjacent pairs
    # For each drive pattern, measure all adjacent pairs except:
    #   - the drive pair itself
    #   - pairs sharing an electrode with the drive pair
    # This gives 13 measurements per drive pattern, 16*13=208 total

    # Compute reference voltages for all drive patterns
    ref_voltages = []
    for d in range(n_elec):
        d_a = electrode_indices[d]
        d_b = electrode_indices[(d + 1) % n_elec]
        u = _solve_forward(K0, n_nodes, d_a, d_b, gnd_node)
        # All 16 adjacent measurements
        all_meas = _compute_measurements(u, electrode_indices)
        # Exclude: drive pair d, and pairs d-1, d+1 (sharing electrode)
        valid = []
        for m in range(n_elec):
            # Exclude if measurement pair shares an electrode with drive pair
            m_elecs = {m, (m + 1) % n_elec}
            d_elecs = {d, (d + 1) % n_elec}
            if m_elecs & d_elecs:
                continue
            valid.append(all_meas[m])
        ref_voltages.extend(valid)
    v_ref_model = np.array(ref_voltages)

    # Jacobian by column perturbation
    delta_sigma = 0.001
    J = np.zeros((len(v_ref_model), n_elem))

    for e in range(n_elem):
        if e % 100 == 0:
            print(f"  Jacobian: element {e}/{n_elem}", file=sys.stderr, end="\r")
        sigma_pert = sigma0.copy()
        sigma_pert[e] += delta_sigma
        K_pert = _assemble_stiffness(nodes, elements, ke_list, sigma_pert)

        pert_voltages = []
        for d in range(n_elec):
            d_a = electrode_indices[d]
            d_b = electrode_indices[(d + 1) % n_elec]
            u = _solve_forward(K_pert, n_nodes, d_a, d_b, gnd_node)
            all_meas = _compute_measurements(u, electrode_indices)
            for m in range(n_elec):
                m_elecs = {m, (m + 1) % n_elec}
                d_elecs = {d, (d + 1) % n_elec}
                if m_elecs & d_elecs:
                    continue
                pert_voltages.append(all_meas[m])

        J[:, e] = (np.array(pert_voltages) - v_ref_model) / delta_sigma

    print("  Jacobian complete.                    ", file=sys.stderr)

    # Reconstruction matrix: Tikhonov regularization
    # R = (J^T J + λ * diag(J^T J))^{-1} J^T
    print("  Computing reconstruction matrix...", file=sys.stderr)
    JtJ = J.T @ J
    reg = regularization * np.diag(np.diag(JtJ) + 1e-10)
    R = np.linalg.solve(JtJ + reg, J.T)

    # Element-to-pixel mapping (32x32 grid)
    print("  Building pixel map...", file=sys.stderr)
    pixel_map = _build_pixel_map(nodes, elements)

    return R, pixel_map, nodes, elements


def _build_pixel_map(nodes: NDArray, elements: NDArray) -> NDArray:
    """Map mesh elements to 32x32 pixel grid.

    Returns (1024, n_elements) matrix.
    """
    n_elem = len(elements)
    centroids = nodes[elements].mean(axis=1)

    # Pixel centers: map [0,31] to [-1,1]
    # Column i -> x = -1 + (2*i+1)/32
    # Row j -> y = 1 - (2*j+1)/32  (top row = y=+1)
    pixel_map = np.zeros((1024, n_elem))

    for j in range(32):
        for i in range(32):
            px = -1.0 + (2 * i + 1) / 32
            py = 1.0 - (2 * j + 1) / 32

            # Skip pixels outside circle
            if px * px + py * py > 1.0:
                continue

            # Find nearest element centroid
            dists = (centroids[:, 0] - px) ** 2 + (centroids[:, 1] - py) ** 2
            nearest = np.argmin(dists)
            pixel_map[j * 32 + i, nearest] = 1.0

    return pixel_map


# ---------------------------------------------------------------------------
# 2.4 Measurement Untwist (EIDORS permutation)
# ---------------------------------------------------------------------------


def _build_untwist() -> tuple[NDArray, NDArray]:
    """Build the EIDORS untwist permutation.

    Returns (valid_indices, twist_indices) both 0-indexed.
    valid_indices: which of the 256 positions are valid measurements (208 of them)
    twist_indices: permutation to reorder from Draeger device order
    """
    elec = 16
    pos_i = np.array([0, 1])

    # ELS: valid measurement positions (exclude drive electrodes)
    indices = np.arange(elec**2)
    els_val = (indices % elec - indices // elec + elec) % elec

    # Excluded values: [-1, 0, 0, 1] mod 16 = [15, 0, 0, 1]
    exclude = set(((elec + v) % elec) for v in [-1, 0, 0, 1])
    valid_mask = np.array([v not in exclude for v in els_val])

    # Build twist array (MATLAB 1-indexed, convert to 0-indexed)
    twist_1idx = []
    twist_1idx.extend(range(1, 14))  # 0+(1:13)
    twist_1idx.extend(range(14, 27))  # 13+(1:13)
    # Pattern: for drive d (0-indexed from 2 to 15):
    #   prefix: reversed range of d indices, suffix: ascending range
    for d in range(2, 16):
        prefix_start = 13 * d + 13  # = 13*(d+1)
        n_prefix = d - 1 if d < 14 else (d - 1)
        n_suffix = 13 - n_prefix if d < 14 else 0

        if d < 14:
            # prefix: reversed
            for k in range(d - 1, -1, -1):
                twist_1idx.append(13 * d - k)
            # suffix: ascending
            for k in range(1, 14 - d):
                twist_1idx.append(13 * d + k)
        elif d == 14:
            for k in range(12, -1, -1):
                twist_1idx.append(13 * 14 - k)
        elif d == 15:
            for k in range(12, -1, -1):
                twist_1idx.append(13 * 15 - k)

    twist_0idx = np.array(twist_1idx) - 1  # to 0-indexed
    valid_indices = np.where(valid_mask)[0]

    return valid_indices, twist_0idx


# Build once at module level
_VALID_INDICES, _TWIST_INDICES = _build_untwist()


def untwist_voltages(v_cal: NDArray) -> NDArray:
    """Reorder 208 calibrated voltages from Draeger order to model order.

    Input: (n_frames, 208) calibrated voltages in Draeger device order
    Output: (n_frames, 208) reordered voltages
    """
    # The twist maps device position -> model position
    # vv[valid] = dd[twist]
    return v_cal[:, _TWIST_INDICES]


def reconstruct_images(
    v_cal: NDArray,
    R: NDArray,
    pixel_map: NDArray,
) -> NDArray:
    """Reconstruct 32x32 images for all frames.

    Args:
        v_cal: (n_frames, 208) calibrated voltages
        R: (n_elements, 208) reconstruction matrix
        pixel_map: (1024, n_elements) element-to-pixel mapping

    Returns:
        (n_frames, 32, 32) pixel impedance images
    """
    n_frames = v_cal.shape[0]

    # Reference: temporal mean
    v_ref = v_cal.mean(axis=0)

    # Untwist
    v_reordered = untwist_voltages(v_cal)
    v_ref_reordered = untwist_voltages(v_ref.reshape(1, -1)).ravel()

    # Reconstruct all frames: delta_sigma = R @ (v - v_ref)
    dv = v_reordered - v_ref_reordered
    # element_values: (n_frames, n_elements)
    element_values = dv @ R.T
    # pixel_values: (n_frames, 1024)
    pixel_values = element_values @ pixel_map.T

    return pixel_values.reshape(n_frames, 32, 32)


# ---------------------------------------------------------------------------
# 3. Impedance Analysis
# ---------------------------------------------------------------------------

ROI_DEFAULTS = [
    ("Local 1", 10, 23),
    ("Local 2", 22, 23),
    ("Local 3", 10, 11),
    ("Local 4", 22, 11),
]
ROI_SIZE = 12


def compute_global_impedance(images: NDArray) -> NDArray:
    """Sum of all pixels per frame."""
    return images.reshape(images.shape[0], -1).sum(axis=1)


def compute_roi_impedance(
    images: NDArray,
    rois: list[tuple[str, int, int]] | None = None,
) -> NDArray:
    """Compute ROI impedance for each frame.

    Returns (n_frames, n_rois) array.
    """
    if rois is None:
        rois = ROI_DEFAULTS

    n_frames = images.shape[0]
    result = np.zeros((n_frames, len(rois)))
    half = ROI_SIZE // 2

    for r_idx, (name, cx, cy) in enumerate(rois):
        x0 = max(0, cx - half)
        x1 = min(32, cx + half)
        y0 = max(0, cy - half)
        y1 = min(32, cy + half)
        result[:, r_idx] = images[:, y0:y1, x0:x1].reshape(n_frames, -1).sum(axis=1)

    return result


def detect_breaths(
    global_imp: NDArray,
    framerate: float,
    min_breath_seconds: float = 1.0,
) -> NDArray:
    """Detect breathing cycles and assign MinMax flags.

    Returns (n_frames,) array with -1 (min), +1 (max), 0 (neither).
    """
    from scipy.signal import find_peaks

    min_distance = max(1, int(min_breath_seconds * framerate))

    # Find maxima (end-inspiration)
    maxima, _ = find_peaks(global_imp, distance=min_distance)
    # Find minima (end-expiration)
    minima, _ = find_peaks(-global_imp, distance=min_distance)

    flags = np.zeros(len(global_imp), dtype=np.int32)
    flags[maxima] = 1
    flags[minima] = -1

    return flags


@dataclass
class TidalVariation:
    frame_idx: int  # frame index of the end-inspiration peak
    time: float
    global_var: float
    local_vars: list[float]
    local_pcts: list[float]


def compute_tidal_variations(
    global_imp: NDArray,
    roi_imp: NDArray,
    timestamps: NDArray,
    minmax_flags: NDArray,
) -> list[TidalVariation]:
    """Compute tidal impedance variations per breath cycle."""
    maxima = np.where(minmax_flags == 1)[0]
    minima = np.where(minmax_flags == -1)[0]

    if len(maxima) == 0 or len(minima) == 0:
        return []

    variations = []
    for max_idx in maxima:
        # Find the preceding minimum
        prev_mins = minima[minima < max_idx]
        if len(prev_mins) == 0:
            continue
        min_idx = prev_mins[-1]

        g_var = global_imp[max_idx] - global_imp[min_idx]
        if abs(g_var) < 1e-10:
            continue

        l_vars = []
        l_pcts = []
        for r in range(roi_imp.shape[1]):
            lv = roi_imp[max_idx, r] - roi_imp[min_idx, r]
            l_vars.append(lv)
            l_pcts.append(100.0 * lv / g_var if abs(g_var) > 1e-10 else 0.0)

        variations.append(
            TidalVariation(
                frame_idx=max_idx,
                time=timestamps[max_idx],
                global_var=g_var,
                local_vars=l_vars,
                local_pcts=l_pcts,
            )
        )

    return variations


# ---------------------------------------------------------------------------
# 4. ASC File Writer
# ---------------------------------------------------------------------------


def _fmt_value(v: float, decimals: int = 6) -> str:
    """Format a float with sign prefix and comma decimal separator."""
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}".replace(".", ",")


def _fmt_time(t: float) -> str:
    """Format timestamp with comma decimal separator."""
    return f"{t:.10f}".replace(".", ",")


def write_asc(
    path: Path,
    header: EITHeader,
    n_frames: int,
    timestamps: NDArray,
    images: NDArray,
    global_imp: NDArray,
    roi_imp: NDArray,
    minmax_flags: NDArray,
    tidal_vars: list[TidalVariation],
    rois: list[tuple[str, int, int]] | None = None,
) -> None:
    """Write complete .asc file."""
    if rois is None:
        rois = ROI_DEFAULTS

    duration_s = (timestamps[-1] - timestamps[0]) * 24 * 60 * 60
    baseline_end = int(duration_s)
    baseline_mm = baseline_end // 60
    baseline_ss = baseline_end % 60
    baseline_hh = baseline_mm // 60
    baseline_mm = baseline_mm % 60

    with open(path, "w", encoding="latin-1") as f:
        # Header
        f.write("---DraegerEIT Software V1.30---\n")
        f.write("- Images, Tidal Variations & Waveforms -\n")
        f.write("\n")
        f.write(f"File:\t\t{header.filename}\n")
        f.write(
            f"Length:\t{n_frames} Images (1...{n_frames}) = {int(duration_s)} s\n"
        )
        f.write("Artef.-Filter: \tOff\n")
        f.write("LP/BP-Filter: \tOff\n")
        f.write("Filter Cut-Off Frequ:\t- bpm\n")
        f.write("Rotation Angle:\t0\xb0\n")
        f.write(
            f"Baseline-Data:\tPeriod: {baseline_hh:02d}:{baseline_mm:02d}:{baseline_ss:02d}  -  "
            f"{baseline_hh:02d}:{baseline_mm:02d}:{baseline_ss:02d}\n"
        )
        f.write(f"ROI Size:\t{ROI_SIZE}x{ROI_SIZE} Pixels\n")
        f.write("Medibus Shift:\t0 msec\n")
        f.write("\n")

        # Dynamic Image (use first tidal peak, or frame 0)
        if len(tidal_vars) > 0:
            dyn_idx = tidal_vars[0].frame_idx
        else:
            dyn_idx = 0
        f.write(f"Dynamic Image, time:\t{_fmt_time(timestamps[dyn_idx])}\n")
        f.write("\n")
        _write_image_grid(f, images[dyn_idx])
        f.write("\n")

        # Tidal Image (difference between first two tidal frames)
        if len(tidal_vars) >= 2:
            t_start = tidal_vars[0].frame_idx
            t_end = tidal_vars[1].frame_idx
            tidal_img = images[t_end] - images[t_start]
            f.write(
                f"Tidal Image, time:\t{_fmt_time(timestamps[t_start])}"
                f"\t=>\t{_fmt_time(timestamps[t_end])}\n"
            )
        else:
            tidal_img = np.zeros((32, 32))
            f.write(f"Tidal Image, time:\t{_fmt_time(timestamps[0])}\t=>\t{_fmt_time(timestamps[0])}\n")
        f.write("\n")
        _write_image_grid(f, tidal_img)
        f.write("\n")

        # Tidal Variations table
        f.write("Tidal Variations\n")
        roi_header = "\t".join(
            [f"{name} (X:{cx} Y:{cy})" for name, cx, cy in rois]
        )
        pct_header = "\t".join([f"{name} %" for name, _, _ in rois])
        f.write(f"Image\tTime\tGlobal\t{roi_header}\t{pct_header}\n")
        for tv in tidal_vars:
            local_vals = "\t".join(_fmt_value(v) for v in tv.local_vars)
            local_pcts = "\t".join(f"{p:.2f}" for p in tv.local_pcts)
            f.write(
                f"{tv.frame_idx + 1}\t{_fmt_time(tv.time)}\t"
                f"{_fmt_value(tv.global_var)}\t{local_vals}\t{local_pcts}\n"
            )
        f.write("\n")

        # Waveform table
        roi_col_header = "\t".join(
            [f"{name} (X:{cx} Y:{cy})" for name, cx, cy in rois]
        )
        f.write(
            f"Image\tTime\tGlobal\t{roi_col_header}\tMinMax\tEvent\tEventText\n"
        )
        for i in range(n_frames):
            local_vals = "\t".join(_fmt_value(roi_imp[i, r]) for r in range(roi_imp.shape[1]))
            f.write(
                f"{i + 1}\t{_fmt_time(timestamps[i])}\t"
                f"{_fmt_value(global_imp[i])}\t{local_vals}\t"
                f"{minmax_flags[i]}\t0\t\n"
            )

    print(f"  Wrote {path}", file=sys.stderr)


def _write_image_grid(f, image: NDArray) -> None:
    """Write 32x32 image as tab-separated signed values."""
    for row in range(32):
        vals = [_fmt_value(image[row, col]) for col in range(32)]
        f.write("\t".join(vals) + "\t\n")


# ---------------------------------------------------------------------------
# 5. CLI & Pipeline
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Convert Draeger .eit files to .asc format"
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="Input .eit file(s)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .asc file")
    parser.add_argument(
        "--regularization",
        type=float,
        default=0.01,
        help="Tikhonov regularization parameter (default: 0.01)",
    )
    args = parser.parse_args()

    # 1. Load EIT data
    print("Loading EIT files...", file=sys.stderr)
    data = load_eit_files(args.inputs)
    n_frames = len(data.timestamps)
    print(f"  Total: {n_frames} frames", file=sys.stderr)

    # 2. Calibrate voltages
    print("Calibrating voltages...", file=sys.stderr)
    v_cal = calibrate_voltages(data.voltages)

    # 3. Build reconstruction matrix
    print("Building reconstruction model...", file=sys.stderr)
    R, pixel_map, _, _ = build_reconstruction_matrix(
        regularization=args.regularization
    )

    # 4. Reconstruct images
    print("Reconstructing images...", file=sys.stderr)
    images = reconstruct_images(v_cal, R, pixel_map)

    # 5. Compute impedance values
    print("Computing impedance...", file=sys.stderr)
    global_imp = compute_global_impedance(images)
    roi_imp = compute_roi_impedance(images)

    # 6. Detect breaths and compute tidal variations
    print("Detecting breaths...", file=sys.stderr)
    minmax_flags = detect_breaths(global_imp, data.header.framerate)
    tidal_vars = compute_tidal_variations(
        global_imp, roi_imp, data.timestamps, minmax_flags
    )
    print(f"  Detected {len(tidal_vars)} breath cycles", file=sys.stderr)

    # 7. Write ASC
    print("Writing ASC file...", file=sys.stderr)
    write_asc(
        args.output,
        data.header,
        n_frames,
        data.timestamps,
        images,
        global_imp,
        roi_imp,
        minmax_flags,
        tidal_vars,
    )

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
