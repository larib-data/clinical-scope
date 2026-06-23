#!/usr/bin/env python3
"""
Finish a built ClinicalScope bundle: copy static assets in, write license notices.

PyInstaller produces the raw bundle (the executable + ``_internal/``); this script
takes over from there and is **shared by both build entry points** -- ``build.sh``
(local) and the GitHub Actions build workflow -- so the asset manifest and the
license step live in exactly one place instead of drifting between a bash script
and a YAML file. Each caller still runs PyInstaller itself, because their output
paths differ; they converge here.

Steps:

1. Copy the static assets listed in ``ASSETS`` into the bundle root.
2. Regenerate ``THIRD_PARTY_LICENSES.txt`` via ``generate_third_party_licenses``.

Exit code: ``0`` when every asset copied and attribution is complete; non-zero
when an asset was missing or the license notice has unresolved entries. Callers
treat a non-zero exit as a *warning*, not a hard failure -- see
``docs/adr/0002-warn-only-on-unresolved-license-attribution.md``.

Usage::

    python assemble_bundle.py --bundle-root <dir-with-_internal>
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from clinical_scope.build_info import generate_third_party_licenses as licenses

# Repo root: this file is at src/clinical_scope/build_info/assemble_bundle.py.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# (path relative to the repo root, "file" | "tree"). Trees drop the per-run cache.
ASSETS: list[tuple[str, str]] = [
    ("docs/user_guide/ClinicalScope_UserGuide.pdf", "file"),
    ("LICENSE", "file"),
    ("DISCLAIMER.txt", "file"),
    ("example/template_patient_data_structure", "tree"),
    ("example/demo_database", "tree"),
]
_TREE_IGNORE = shutil.ignore_patterns("clinical_scope_output")


def copy_assets(bundle_root: Path) -> list[str]:
    """Copy each asset into ``bundle_root``; return the ones that were missing."""
    missing: list[str] = []
    for rel, kind in ASSETS:
        src = PROJECT_ROOT / rel
        if not src.exists():
            print(f"  WARNING: asset not found, skipped: {rel}")
            missing.append(rel)
            continue
        dest = bundle_root / src.name
        if kind == "tree":
            shutil.copytree(src, dest, ignore=_TREE_IGNORE, dirs_exist_ok=True)
        else:
            shutil.copy(src, dest)
        print(f"  copied {rel}")
    return missing


def main(argv: list[str] | None = None) -> int:
    """Copy assets and write license notices into the bundle; return an exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bundle-root",
        required=True,
        type=Path,
        help="Built bundle directory (contains the executable and _internal/).",
    )
    args = ap.parse_args(argv)
    if not args.bundle_root.is_dir():
        ap.error(f"bundle root does not exist: {args.bundle_root}")

    print("Copying bundle assets...")
    missing = copy_assets(args.bundle_root)
    if missing:
        print(f"  MISSING ASSETS: {', '.join(missing)}")

    print("Generating third-party license notices...")
    lic_rc = licenses.main(["--bundle-root", str(args.bundle_root)])

    return 1 if (missing or lic_rc) else 0


if __name__ == "__main__":
    raise SystemExit(main())
