"""
The ``clinical-scope`` console script: launch the dashboard, or say where to get the demo data.

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

_EPILOG = """\
examples:
  clinical-scope            launch the dashboard at http://127.0.0.1:8050
  clinical-scope --demo     print where to download the demo dataset

The demo archive holds a ready-made patient recording plus the database_options config that
goes with it: download it in a browser, unzip it, and paste the printed paths into the app.
"""

_DEMO_INSTRUCTIONS = """\
The demo dataset is a 2 MB download:

  {url}

Open that link in a browser and unzip the file it saves — your Downloads folder is fine. Then
start the app with `clinical-scope` and fill in, where <unzipped> is where you unzipped it:

  - Data folder:      <unzipped>/{demo}/{patient}
  - Database options: <unzipped>/{demo}/{options}

The demo's EIT and EDF files carry no recording date, so the app asks you for one: the user
guide's "Trying the Demo Dataset" section (the Docs button in the app) gives both values.\
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
        help="print where to download the demo dataset and exit (does not start the app)",
    )
    parser.add_argument("--version", action="version", version=_version_string())
    return parser


def _version_string() -> str:
    # Deferred import — see the module docstring.
    from clinical_scope.dash_api.version_check import running_version

    return f"clinical-scope {running_version()}"


def _print_demo_instructions() -> None:
    """
    Print the demo download link and what to do with the archive it points at.

    A link rather than a download: a browser saves it to Downloads, a folder every user can
    open, whereas anything this command wrote under the app's own state folder would be hidden
    by default on both macOS and Windows.
    """
    print(
        _DEMO_INSTRUCTIONS.format(
            url=cst.DEMO_ARCHIVE_URL,
            demo=f"{cst.DEMO_ARCHIVE_ROOT_DIR_NAME}/{cst.DEMO_DATABASE_DIR_NAME}",
            patient=cst.DEMO_PATIENT_DIR_NAME,
            options=cst.DEMO_DATABASE_OPTIONS_FILE_NAME,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``clinical-scope`` script; returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if args.demo:
        _print_demo_instructions()
        return 0

    # Deferred import — see the module docstring.
    from clinical_scope.dash_api.core_api import main as run_dashboard

    run_dashboard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
