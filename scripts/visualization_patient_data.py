import argparse
import logging
import sys
from pathlib import Path

from clinical_scope import logger_config, wrapper
from clinical_scope.config.parsing import (
    build_patient_options,
    load_database_options_from_path,
)
from clinical_scope.signal_container import (
    PlotModel,
)

logger = logging.getLogger(__name__)


# ==================================================================================================
def main(option_dict):
    patient_options = build_patient_options(
        option_dict["patient_folder"], option_dict.get("path_patient_options")
    )
    path_db = option_dict.get("path_database_options")
    database_options = load_database_options_from_path(Path(path_db)) if path_db else None

    model = wrapper.main(
        patient_options=patient_options,
        database_options_global=database_options,
    )

    PlotModel.to_html(model, patient_options)

    logger.info("Script finished sucessfully")


# ==================================================================================================
def args_parser(args):
    parser = argparse.ArgumentParser(description="Time series visualization tool")
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
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=False, help="")
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print summary to stdout (default: off). Use --verbose to print.",
    )

    args_namespace = parser.parse_args(args)
    options = vars(args_namespace)

    # setup logger
    library_dir = logger_config.get_logs_path()
    script_name = Path(__file__).stem
    logs_path = library_dir / "scripts" / f"{script_name}.log"

    logger_config.setup_logging(logs_path, options["debug"])
    logger.info("Starting script: %s", script_name)

    main(options)


# ==================================================================================================
if __name__ == "__main__":
    args_parser(sys.argv[1:])
