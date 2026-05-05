"""
Data inspection CLI script.

Runs find + load + format for each datasource and reports available columns,
point counts, and load status — without generating any plots.

Usage
-----
    python scripts/inspect_patient_data.py /data/Patient01
    python scripts/inspect_patient_data.py /data/Patient01 --database-options db.json
    python scripts/inspect_patient_data.py /data/Patient01 --patient-options opts.json
    python scripts/inspect_patient_data.py ... --output-csv out.csv
"""

import argparse
import logging
import sys
from pathlib import Path

from clinical_scope import logger_config, wrapper
from clinical_scope.config.parsing import (
    build_patient_options,
    load_database_options_from_path,
)
from clinical_scope.datasource.inspection import to_csv_string, to_text_summary

logger = logging.getLogger(__name__)


# ==================================================================================================
def main(option_dict: dict) -> None:
    patient_options = build_patient_options(
        option_dict["patient_folder"], option_dict.get("path_patient_options")
    )
    path_db = option_dict.get("path_database_options")
    database_options = load_database_options_from_path(Path(path_db)) if path_db else None

    results = wrapper.inspect(
        patient_options=patient_options,
        database_options_global=database_options,
    )

    verbose = option_dict["verbose"]

    if verbose:
        print(to_text_summary(results))  # noqa: T201

    # --- optional CSV output ---
    output_csv = option_dict.get("output_csv")
    if output_csv:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(to_csv_string(results), encoding="utf-8")
        logger.info("Inspection CSV written to: %s", output_path)
        if verbose:
            print(f"CSV written to: {output_path}")  # noqa: T201

    logger.info("Script finished successfully.")


# ==================================================================================================
def args_parser(args: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Inspect available columns per datasource without generating plots."
    )
    parser.add_argument("patient_folder", type=str, help="Path to the patient data folder.")
    parser.add_argument(
        "--patient-options",
        type=str,
        default=None,
        dest="path_patient_options",
        help="Path to a patient options JSON file (datetime range, quick_load, etc.).",
    )
    parser.add_argument(
        "--database-options",
        type=str,
        default=None,
        dest="path_database_options",
        help="Path to the database options file (.json or .xlsx). "
        "Omit to use all available datasources with their defaults.",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        dest="output_csv",
        help="Optional path to write inspection results as CSV.",
    )
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print summary to stdout (default: off). Use --verbose to print.",
    )

    args_namespace = parser.parse_args(args)
    options = vars(args_namespace)

    library_dir = logger_config.get_logs_path()
    script_name = Path(__file__).stem
    logs_path = library_dir / "scripts" / f"{script_name}.log"
    logger_config.setup_logging(logs_path, options["debug"])
    logger.info("Starting script: %s", script_name)

    main(options)


# ==================================================================================================
if __name__ == "__main__":
    args_parser(sys.argv[1:])
