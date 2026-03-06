import importlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from clinical_data_visualizer.datasource_base import DataSourceBase
from clinical_data_visualizer.helper import folder_name_matches_keywords
from clinical_data_visualizer.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def add_main_module(cls: type) -> type:
    module_path = f"clinical_data_visualizer.{cls.NAME}.find_load_format"
    module = importlib.import_module(module_path)

    options_path = f"clinical_data_visualizer.{cls.NAME}.options"
    options = importlib.import_module(options_path)

    # Safety check: Validate NAME matches options.DATASOURCE_NAME
    ds_name = getattr(options, "DATASOURCE_NAME", None)
    if ds_name is not None and ds_name != cls.NAME:
        msg = (
            f"DataSource registry NAME={cls.NAME!r} does not match "
            f"options.DATASOURCE_NAME={ds_name!r}"
        )
        raise ValueError(msg)

    # Assign the actual main function directly to the class
    cls.MAIN_MODULE = module.main
    cls.OPTIONS = options

    # Find the DataSourceBase subclass in the module for inspection

    cls.DATASOURCE_CLASS = next(
        (
            v
            for v in vars(module).values()
            if isinstance(v, type) and issubclass(v, DataSourceBase) and v is not DataSourceBase
        ),
        None,
    )

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
    class MindRayScope:
        NAME = "mindray_scope"
        DESCRIPTION = "Mindray scope"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class MindRayRespiNumerics:
        NAME = "mindray_respi_numerics"
        DESCRIPTION = "Mindray Respi - numerics"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class MindRayRespiWaves:
        NAME = "mindray_respi_waves"
        DESCRIPTION = "Mindray Respi - waves"
        MAIN_MODULE: ClassVar[Callable[[dict, dict | None], list[Signal]]]
        OPTIONS: object

    @add_main_module
    class Other:
        NAME = "other"
        DESCRIPTION = "Other (generic)"
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
        MindRayRespiNumerics,
        MindRayRespiWaves,
        MindRayScope,
        Other,
    )

    @classmethod
    def get_subclass_by_name(cls, name: str) -> type | None:
        nested_classes = get_nested_classes(cls)
        for nested_class in nested_classes:
            if name == nested_class.NAME:
                return nested_class
        return None


def detect_datasource_from_folder(folder: str | Path) -> type | None:
    """
    Return the DataSource registry entry whose ``FOLDER_KEYWORDS`` all appear in *folder*'s name.

    When multiple datasources match, the one with the most keywords wins (best-match).
    Matching is case-insensitive.  Returns ``None`` if no datasource matches.

    Args:
        folder: Path to a datasource subfolder (only the *name* component is inspected).

    Returns:
        The matching DataSource registry entry (with ``.NAME``, ``.DATASOURCE_CLASS``,
        ``.OPTIONS`` …), or ``None``.

    """
    folder_name = Path(folder).name
    best_match = None
    best_score = 0
    for ds in DataSource.AVAILABLE:
        keywords = getattr(ds.OPTIONS, "FOLDER_KEYWORDS", None)
        if not keywords:
            continue
        if folder_name_matches_keywords(folder_name, keywords):
            score = len(keywords)
            if score > best_score:
                best_score = score
                best_match = ds
    return best_match


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
