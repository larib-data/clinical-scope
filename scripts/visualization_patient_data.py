import argparse
import logging
import sys
from pathlib import Path

from clinical_data_visualizer import helper, logger_config, wrapper
from clinical_data_visualizer.signal_container import (
    PlotModel,
)

logger = logging.getLogger(__name__)


# ==================================================================================================
def main(option_dict):
    patient_options = helper.load_options(Path(option_dict["path_patient_options"]))
    database_options = helper.load_database_options_from_path(
        Path(option_dict["path_database_options"])
    )

    model = wrapper.main(
        patient_options=patient_options,
        database_options_global=database_options,
    )

    PlotModel.to_html(model, patient_options)

    logger.info("Script finished sucessfully")


# ==================================================================================================
def args_parser(args):
    parser = argparse.ArgumentParser(description="Time series visualization tool")
    parser.add_argument(
        "path_patient_options", type=str, help="Path to the patient options json file"
    )
    parser.add_argument(
        "path_database_options", type=str, help="Path to the database options json file"
    )
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=False, help="")

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
