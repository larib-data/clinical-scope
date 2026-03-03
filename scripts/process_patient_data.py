"""
Patient data processing script.

Runs find + load + format for each datasource and saves the formatted
DataFrames — without generating any plots.

Subcommands
-----------
patient
    Process a single patient folder.
batch
    Process all patient sub-folders inside a root directory.

Usage
-----
    python scripts/process_patient_data.py patient /data/Patient01
    python scripts/process_patient_data.py patient /data/Patient01 --database-options db.json
    python scripts/process_patient_data.py patient /data/Patient01 --patient-options opts.json
    python scripts/process_patient_data.py patient ... --output-folder /out

    python scripts/process_patient_data.py batch /data/patients
    python scripts/process_patient_data.py batch /data/patients --database-options db.json
    python scripts/process_patient_data.py batch ... --output-folder /out --debug
"""

import argparse
import logging
import sys
from pathlib import Path

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer import helper, logger_config, wrapper

logger = logging.getLogger(__name__)

_TABLE_WIDTH = 58


# ==================================================================================================
def _print_results(results: dict) -> None:
    """Print a name / status / rows summary table to stdout."""
    print(f"\n{'Datasource':<30s}  {'Status':<12s}  {'Rows':>8s}")  # noqa: T201
    print("-" * _TABLE_WIDTH)  # noqa: T201
    for name, df in results.items():
        status = "ok" if df is not None else "not found"
        rows = str(len(df)) if df is not None else "-"
        print(f"{name:<30s}  {status:<12s}  {rows:>8s}")  # noqa: T201
    print()  # noqa: T201
    success = sum(1 for v in results.values() if v is not None)
    print(f"{success}/{len(results)} datasource(s) succeeded.")  # noqa: T201


# ==================================================================================================
def cmd_patient(options: dict) -> None:
    patient_options = helper.build_patient_options(
        options["patient_folder"], options.get("path_patient_options")
    )
    if patient_options.get(cst.PatientOptions.QuickLoad.NAME, False):
        logger.warning(
            "Using quick_load in the script of extraction. This is will only apply the formating "
            "step from the already loaded data"
        )
    path_db = options.get("path_database_options")
    database_options = helper.load_database_options_from_path(Path(path_db)) if path_db else None

    results = wrapper.extract_patient(
        options["patient_folder"],
        database_options,
        patient_options=patient_options,
        save_folder=options.get("output_folder"),
    )

    if options["verbose"]:
        _print_results(results)
        if options.get("output_folder"):
            print(f"Outputs written to: {options['output_folder']}")  # noqa: T201

    logger.info("Patient extraction finished.")


# ==================================================================================================
def cmd_batch(options: dict) -> None:
    path_db = options.get("path_database_options")
    database_options = helper.load_database_options_from_path(Path(path_db)) if path_db else None

    batch_results = wrapper.batch_extract(
        Path(options["root_folder"]),
        database_options,
        save_folder=options.get("output_folder"),
    )

    if options["verbose"]:
        for patient_name, results in batch_results.items():
            print(f"\n── {patient_name}")  # noqa: T201
            _print_results(results)

        total = len(batch_results)
        with_data = sum(1 for r in batch_results.values() if any(v is not None for v in r.values()))
        print(  # noqa: T201
            f"\n{with_data}/{total} patient folder(s) had at least one successful datasource."
        )
        if options.get("output_folder"):
            print(f"Outputs written to: {options['output_folder']}")  # noqa: T201

    logger.info("Batch extraction finished.")


# ==================================================================================================
def args_parser(args: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Process patient data (find + load + format) without generating plots."
    )
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print summary to stdout (default: off). Use --verbose to print.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- patient ----
    p_patient = sub.add_parser("patient", help="Process a single patient folder.")
    p_patient.add_argument("patient_folder", type=str, help="Path to the patient data folder.")
    p_patient.add_argument(
        "--patient-options",
        type=str,
        default=None,
        dest="path_patient_options",
        help="Path to a patient options JSON file (datetime range, quick_load, etc.).",
    )
    p_patient.add_argument(
        "--database-options",
        type=str,
        default=None,
        dest="path_database_options",
        help="Path to the database options file (.json or .xlsx). "
        "Omit to use all available datasources with their defaults.",
    )
    p_patient.add_argument(
        "--output-folder",
        type=str,
        default=None,
        dest="output_folder",
        help="Optional folder to save formatted DataFrames as parquet files.",
    )

    # ---- batch ----
    p_batch = sub.add_parser(
        "batch", help="Process all patient sub-folders inside a root directory."
    )
    p_batch.add_argument(
        "root_folder", type=str, help="Root directory whose sub-folders are patient folders."
    )
    p_batch.add_argument(
        "--database-options",
        type=str,
        default=None,
        dest="path_database_options",
        help="Path to the database options file (.json or .xlsx). "
        "Omit to use all available datasources with their defaults.",
    )
    p_batch.add_argument(
        "--output-folder",
        type=str,
        default=None,
        dest="output_folder",
        help="Optional root folder for outputs; each patient gets a sub-folder.",
    )

    args_namespace = parser.parse_args(args)
    options = vars(args_namespace)

    library_dir = logger_config.get_logs_path()
    script_name = Path(__file__).stem
    logs_path = library_dir / "scripts" / f"{script_name}.log"
    logger_config.setup_logging(logs_path, options["debug"])
    logger.info("Starting script: %s  [subcommand: %s]", script_name, options["command"])

    if options["command"] == "patient":
        cmd_patient(options)
    else:
        cmd_batch(options)


# ==================================================================================================
if __name__ == "__main__":
    args_parser(sys.argv[1:])
