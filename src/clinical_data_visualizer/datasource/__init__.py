# datasource package — datasource management and infrastructure.

# Re-export key classes for backward compatibility and convenience
from clinical_data_visualizer.datasource.base import DataSourceBase
from clinical_data_visualizer.datasource.registry import (
    DataSource,
    add_main_module,
    detect_datasource_from_folder,
    generate_default_database_options,
    get_nested_classes,
)

__all__ = [
    "DataSource",
    "DataSourceBase",
    "add_main_module",
    "detect_datasource_from_folder",
    "generate_default_database_options",
    "get_nested_classes",
]
