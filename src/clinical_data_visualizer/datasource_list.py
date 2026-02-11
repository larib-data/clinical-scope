import importlib
import logging
from collections.abc import Callable
from typing import ClassVar

from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def add_main_module(cls: type) -> type:
    module_path = f"clinical_data_visualizer.{cls.NAME}.find_load_format"
    module = importlib.import_module(module_path)

    options_path = f"clinical_data_visualizer.{cls.NAME}.options"
    options = importlib.import_module(options_path)

    # Assign the actual main function directly to the class
    cls.MAIN_MODULE = module.main
    cls.OPTIONS = options

    return cls


class DataSource:
    @add_main_module
    class EIT:
        NAME = "eit"
        DESCRIPTION = "EIT - PulmoVista"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class PhilipsWaves:
        NAME = "philips_waves"
        DESCRIPTION = "Philips scope - waves"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class PhilipsNumerics:
        NAME = "philips_numerics"
        DESCRIPTION = "Philips scope - numerics"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class Syringe:
        NAME = "syringe"
        DESCRIPTION = "Syringe"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class FluxmedParameters:
        NAME = "fluxmed_parameters"
        DESCRIPTION = "Fluxmed - numerics"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class FluxmedSignals:
        NAME = "fluxmed_signals"
        DESCRIPTION = "Fluxmed - waves"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class ServoU:
        NAME = "servo_u"
        DESCRIPTION = "Servo U"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class MindRay:
        NAME = "mindray"
        DESCRIPTION = "Mindray scope"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    # This order is the "default" order of plot, so try to choose it a bit carefully
    # Maybe the order should be from the order in database_options, but it's easy to do that there with the global priority honestly  # noqa: E501
    AVAILABLE = (
        PhilipsWaves,
        EIT,
        PhilipsNumerics,
        Syringe,
        FluxmedParameters,
        FluxmedSignals,
        ServoU,
        MindRay,
    )

    @classmethod
    def get_subclass_by_name(cls, name: str) -> type | None:
        nested_classes = get_nested_classes(cls)
        for nested_class in nested_classes:
            if name == nested_class.NAME:
                return nested_class
        return None


def generate_default_database_options() -> dict:
    """Generate database options with all available datasources using their defaults."""
    db_options = {}
    for data_source in DataSource.AVAILABLE:
        default = getattr(data_source.OPTIONS, "DEFAULT_DATABASE_OPTIONS", {})
        db_options[data_source.NAME] = dict(default)
    return db_options


def get_nested_classes(cls: type) -> list[type]:
    return [
        value
        for name, value in vars(cls).items()
        if isinstance(value, type) and issubclass(value, object)
    ]
