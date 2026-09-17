"""
The ``clinical-scope`` console script: launch the dashboard, or fetch the demo dataset.

Separate from :mod:`clinical_scope.dash_api.core_api` because the two entry points have
different argv contracts. This one is run by a person who may pass flags; core_api is the
PyInstaller entry point, run by Finder, which hands a macOS bundle a ``-psn_…`` argument that
any parser would reject.

Imports of ``dash_api`` are deferred to their call sites: it builds the Dash layout at import
time, so ``--help`` and ``--demo`` would otherwise pay for a layout they never render.
"""

from __future__ import annotations

import argparse
import sys

import clinical_scope.constants as cst
from clinical_scope.demo_data import DemoDownloadError, fetch_demo_data

_EPILOG = """\
examples:
  clinical-scope            launch the dashboard at http://127.0.0.1:8050
  clinical-scope --demo     download the demo dataset and print where it landed

The demo folder holds a ready-made patient recording plus the database_options config
that goes with it: paste its demo_patient path into the app's Data folder field.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinical-scope",
        description="Interactive visualization dashboard for clinical physiological signals.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="download the demo dataset, print its path and exit (does not start the app)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --demo, re-download even if the demo folder already exists",
    )
    parser.add_argument("--version", action="version", version=_version_string())
    return parser


def _version_string() -> str:
    # Deferred import — see the module docstring.
    from clinical_scope.dash_api.version_check import running_version

    return f"clinical-scope {running_version()}"


def _download_demo(*, force: bool) -> int:
    try:
        folder = fetch_demo_data(force=force)
    except DemoDownloadError as error:
        print(f"clinical-scope: could not get the demo data: {error}", file=sys.stderr)
        return 1

    database = folder / cst.DEMO_DATABASE_DIR_NAME
    print(f"Demo data ready at:\n  {folder}\n")
    print("Start the app with `clinical-scope`, then:")
    print(f"  - Data folder:      {database / cst.DEMO_PATIENT_DIR_NAME}")
    print(f"  - Database options: {database / cst.DEMO_DATABASE_OPTIONS_FILE_NAME}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``clinical-scope`` script; returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.demo:
        return _download_demo(force=args.force)
    if args.force:
        parser.error("--force only applies to --demo")

    # Deferred import — see the module docstring.
    from clinical_scope.dash_api.core_api import main as run_dashboard

    run_dashboard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
