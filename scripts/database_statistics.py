"""
Database statistics CLI script.

Compute aggregate statistics across all patients in a database folder.

Usage
-----
    python scripts/database_statistics.py /data/patients
    python scripts/database_statistics.py /data/patients --database-options db.json
    python scripts/database_statistics.py /data/patients --output-csv stats.csv
"""

import argparse
import logging
import sys
from pathlib import Path

from clinical_data_visualizer import helper, logger_config, wrapper
from clinical_data_visualizer.database_statistics import to_csv_string, to_text_summary

logger = logging.getLogger(__name__)


# ==================================================================================================
def main(option_dict: dict) -> None:
    path_db = option_dict.get("path_database_options")
    database_options = helper.load_database_options_from_path(Path(path_db)) if path_db else None

    patient_options: dict = {}
    verbose = option_dict["verbose"]

    def progress(current: int, total: int, name: str) -> None:
        if verbose:
            print(f"  Processing patient {current}/{total}: {name}")  # noqa: T201

    stats = wrapper.database_statistics(
        patient_folders_or_root=option_dict["root_folder"],
        database_options_global=database_options,
        patient_options=patient_options,
        progress_callback=progress,
    )

    if verbose:
        print(to_text_summary(stats))  # noqa: T201

    # --- optional CSV output ---
    output_csv = option_dict.get("output_csv")
    if output_csv:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(to_csv_string(stats), encoding="utf-8")
        logger.info("Statistics CSV written to: %s", output_path)
        if verbose:
            print(f"CSV written to: {output_path}")  # noqa: T201

    logger.info("Script finished successfully.")


# ==================================================================================================
def args_parser(args: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Compute aggregate statistics across all patients in a database folder."
    )
    parser.add_argument(
        "root_folder",
        type=str,
        help="Root directory whose immediate subdirectories are patient folders.",
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
        help="Optional path to write statistics as CSV.",
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
