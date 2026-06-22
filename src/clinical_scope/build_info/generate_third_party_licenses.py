#!/usr/bin/env python3
"""
Generate THIRD_PARTY_LICENSES.txt for a built ClinicalScope bundle.

The PyInstaller bundle redistributes third-party code and native libraries, all
under permissive / public-domain licenses whose only obligation is attribution.
PyInstaller does not collect their license texts, so this script assembles them:

1. Python packages -- harvested from the *running interpreter's* installed
   distributions (run this with the same venv that produced the build, so the
   set matches exactly). Build-only tooling is excluded.
2. Native libraries + the embedded interpreter -- discovered by scanning the
   bundle's ``_internal/`` folder, then matched against a hand-maintained map.
   Unknown native libraries are emitted as TODO entries rather than skipped.

Usage::

    python generate_third_party_licenses.py --bundle-root <dir-with-_internal>

The output is written to ``<bundle-root>/THIRD_PARTY_LICENSES.txt``.
"""

from __future__ import annotations

import argparse
import importlib.metadata as im
import sys
from pathlib import Path

# Build-only tooling that is NOT redistributed in the bundle -> no obligation.
# (PyInstaller's own bootloader ships under its separate distribution exception.)
BUILD_ONLY = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "macholib",
    "pip",
    "setuptools",
    "wheel",
    "clinical-scope",  # our own code -> covered by the top-level LICENSE
}

LIC_HINTS = ("license", "licence", "copying", "notice", "authors")

# Standalone native shared libraries -> (display name, license notice). Keyed by
# a lowercase filename-stem prefix; matched across platforms (.dylib/.so/.dll).
# Extend this map when a build introduces a native lib not listed here.
NATIVE_LICENSES: dict[str, tuple[str, str]] = {
    "libarrow": (
        "Apache Arrow C++",
        "License: Apache License 2.0. The full Apache-2.0 text and Arrow's NOTICE\n"
        'are reproduced above in the "pyarrow" section (same project).',
    ),
    "libparquet": (
        "Apache Parquet C++ (part of Apache Arrow)",
        'License: Apache License 2.0. See the "pyarrow" section above.',
    ),
    "libcrypto": (
        "OpenSSL",
        "License: Apache License 2.0 (OpenSSL 3.x).\n"
        "Copyright (c) The OpenSSL Project Authors. https://www.openssl.org",
    ),
    "libssl": (
        "OpenSSL",
        "License: Apache License 2.0 (OpenSSL 3.x).\n"
        "Copyright (c) The OpenSSL Project Authors. https://www.openssl.org",
    ),
    "libsqlite3": (
        "SQLite",
        "SQLite is in the public domain. https://www.sqlite.org/copyright.html",
    ),
    "liblzma": (
        "liblzma / xz",
        "The liblzma core is public domain (0BSD). https://tukaani.org/xz/",
    ),
    "libmpdec": (
        "libmpdec",
        "License: BSD 2-Clause. Copyright (c) Stefan Krah. Used by Python decimal.",
    ),
    # Common cross-platform extras (may appear on Linux/Windows builds):
    "libz": ("zlib", "License: zlib license. https://zlib.net"),
    "libbz2": ("bzip2", "License: BSD-style. https://sourceware.org/bzip2/"),
    "libffi": ("libffi", "License: MIT. https://github.com/libffi/libffi"),
    "libtcl": ("Tcl", "License: Tcl/Tk BSD-style license. https://www.tcl.tk"),
    "libtk": ("Tk", "License: Tcl/Tk BSD-style license. https://www.tcl.tk"),
}

# Packages that ship no license file upstream -> supply a notice by hand here.
MANUAL_PKG: dict[str, str] = {}


def norm(name: str) -> str:
    """
    Lowercase a distribution name.

    Hyphens and underscores are unified so lookups are spelling-insensitive.
    """
    return (name or "").lower().replace("_", "-")


def harvest_python_packages() -> tuple[list[str], list[str], list[str]]:
    """
    Collect license sections for the running interpreter's distributions.

    Returns ``(sections, covered, missing)``.
    """
    excluded = {norm(b) for b in BUILD_ONLY}
    seen: set[str] = set()
    sections: list[str] = []
    covered: list[str] = []
    missing: list[str] = []

    dists = sorted(im.distributions(), key=lambda d: norm(d.metadata.get("Name") or ""))
    for d in dists:
        name = d.metadata.get("Name") or "<unknown>"
        n = norm(name)
        if n in excluded or n in seen:
            continue
        seen.add(n)
        texts = _license_texts(d)
        if not texts:
            body = MANUAL_PKG.get(
                n, "*** TODO: upstream ships no license file -- supply the notice. ***"
            )
            sections.append(_block(f"{name}  {d.version}  (manual notice)", [("notice", body)]))
            missing.append(f"{name} {d.version}")
            continue
        sections.append(_block(f"{name}  {d.version}", texts))
        covered.append(f"{name} {d.version}")
    return sections, covered, missing


def _license_texts(dist: im.Distribution) -> list[tuple[str, str]]:
    """Return ``(relative-name, text)`` for each license file a dist ships."""
    out: list[tuple[str, str]] = []
    for f in dist.files or []:
        s = str(f).replace("\\", "/").lower()
        if ".dist-info/" not in s:
            continue
        base = s.rsplit("/", 1)[-1]
        if "/licenses/" in s or "/license_files/" in s or any(h in base for h in LIC_HINTS):
            try:
                text = dist.locate_file(f).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                text = f"<<could not read {f}: {e}>>"
            out.append((str(f).split(".dist-info/", 1)[-1], text))
    return out


def _block(title: str, parts: list[tuple[str, str]]) -> str:
    bar = "=" * 78
    body = "\n".join(f"--- {name} ---\n{text.rstrip()}\n" for name, text in parts)
    return f"\n{bar}\n{title}\n{bar}\n\n{body}"


def discover_native_libs(internal: Path) -> list[Path]:
    """
    Return the standalone native shared libraries bundled in ``_internal``.

    Extension modules (``*.cpython-*.so``, ``*.pyd``, ``*.cpython-*.dylib``) belong
    to a Python package and are already attributed; only standalone ``lib*`` /
    versioned shared objects need their own notice, so those are what we return.
    """
    standalone: list[Path] = []
    ext_suffixes = (".pyd",)
    for p in sorted(internal.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        is_shared = name.endswith((".dylib", ".dll")) or (
            ".so" in name and (name.endswith(".so") or ".so." in name)
        )
        if not is_shared and not name.endswith(ext_suffixes):
            continue
        is_extension = "cpython-" in name or name.endswith(ext_suffixes) or "abi3" in name
        if is_shared and not is_extension:
            standalone.append(p)
    return standalone


def find_psf_text() -> str:
    """Return the CPython PSF license text, or a pointer if not found on disk."""
    base = Path(sys.base_prefix)
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        base / "lib" / ver / "LICENSE.txt",
        base / "LICENSE.txt",
        base / "LICENSE",
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8", errors="replace").rstrip()
    return "*** TODO: paste PSF License text. https://docs.python.org/3/license.html ***"


def native_section(internal: Path) -> tuple[str, list[str]]:
    """
    Build the native-library + embedded-interpreter section for this bundle.

    Returns ``(text, unrecognised)`` so the caller can flag unmatched native
    libraries via the process exit code.
    """
    standalone = discover_native_libs(internal)
    lines = [
        "\n" + "#" * 78,
        "NATIVE LIBRARIES AND EMBEDDED INTERPRETER",
        "#" * 78,
        "",
        "Bundled as compiled shared libraries in `_internal/`; no Python metadata.",
        "Discovered for THIS platform's build (re-run per platform).",
        "",
    ]
    matched: dict[str, tuple[str, list[str]]] = {}
    unknown: list[str] = []
    for p in standalone:
        stem = p.name.lower()
        hit = next((k for k in NATIVE_LICENSES if stem.startswith(k)), None)
        if hit:
            disp, notice = NATIVE_LICENSES[hit]
            matched.setdefault(disp, (notice, []))[1].append(p.name)
        else:
            unknown.append(p.name)

    for disp, (notice, files) in sorted(matched.items()):
        lines += ["-" * 78, f"{disp}  ({', '.join(sorted(set(files)))})", "-" * 78, notice, ""]

    # Embedded interpreter (PSF) -- always present in a PyInstaller bundle.
    lines += [
        "-" * 78,
        f"CPython {sys.version_info.major}.{sys.version_info.minor} interpreter "
        "(Python, base_library.zip, interpreter shared lib)",
        "-" * 78,
        "License: Python Software Foundation License Version 2 (PSF-2.0).",
        "Copyright (c) 2001-present Python Software Foundation. All Rights Reserved.",
        "",
        find_psf_text(),
        "",
    ]

    if unknown:
        lines += [
            "-" * 78,
            "UNRECOGNISED NATIVE LIBRARIES -- ACTION REQUIRED",
            "-" * 78,
            "Add these to NATIVE_LICENSES in generate_third_party_licenses.py:",
            *[f"  *** TODO: {u}" for u in sorted(unknown)],
            "",
        ]
    return "\n".join(lines), unknown


def build_header(covered: int, missing: int) -> str:
    """Return the file preamble summarising counts and provenance."""
    return f"""\
THIRD-PARTY SOFTWARE NOTICES AND LICENSES
=========================================

ClinicalScope is distributed as a self-contained executable produced with
PyInstaller. The bundle (the `_internal/` folder next to the executable)
redistributes the third-party components listed below, each under its own
license. The full and unmodified text of every license follows; refer to each
notice for its specific terms.

Generated from the build interpreter: {sys.executable}

Python packages with reproduced license text: {covered}
Python packages needing a manual notice (listed inline below): {missing}
Native libraries + interpreter: see "NATIVE LIBRARIES" at the end.
"""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, assemble the file, and write it to the bundle root."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bundle-root",
        required=True,
        type=Path,
        help="Bundle directory containing the executable and _internal/.",
    )
    ap.add_argument("--output", type=Path, default=None, help="Override output path.")
    args = ap.parse_args(argv)

    internal = args.bundle_root / "_internal"
    if not internal.is_dir():
        ap.error(f"no _internal/ under {args.bundle_root} -- is this a built bundle?")
    out = args.output or (args.bundle_root / "THIRD_PARTY_LICENSES.txt")

    sections, covered, missing = harvest_python_packages()
    native_text, unrecognised = native_section(internal)
    out.write_text(
        build_header(len(covered), len(missing)) + "".join(sections) + native_text,
        encoding="utf-8",
    )
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  python packages: {len(covered)} with text, {len(missing)} manual")
    if missing:
        print(f"  MANUAL NEEDED: {', '.join(missing)}")
    if unrecognised:
        print(f"  UNRECOGNISED NATIVE LIBS: {', '.join(sorted(unrecognised))}")

    # Warn-only by design (see build_info/README.md): a fresh dependency must not
    # block an iterative build, but unresolved attribution must not pass silently
    # either -- so signal it via a non-zero exit code that build.sh surfaces.
    return 1 if (missing or unrecognised) else 0


if __name__ == "__main__":
    raise SystemExit(main())
