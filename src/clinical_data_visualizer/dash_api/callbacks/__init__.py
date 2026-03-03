"""
Callbacks module for Dash API visualization.

This module contains all callback functions organized by functionality.
"""

from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    build_patient_options_ui,
    close_inspection_modal,
    download_inspection_csv,
    inspect_data,
    load_db_options,
    process_visualization,
)
from clinical_data_visualizer.dash_api.callbacks.loop_callbacks import (
    filter_loop_by_time,
    update_time_display,
)
from clinical_data_visualizer.dash_api.callbacks.shape_callbacks import (
    lock_and_style_shapes,
    modify_shape,
    persist_shapes,
    save_annotations_and_shapes,
    sync_plotly_annotations,
    toggle_modal,
    update_shape_options,
)

__all__ = [
    "build_patient_options_ui",
    "close_inspection_modal",
    "download_inspection_csv",
    "filter_loop_by_time",
    "inspect_data",
    "load_db_options",
    "lock_and_style_shapes",
    "modify_shape",
    "persist_shapes",
    "process_visualization",
    "save_annotations_and_shapes",
    "sync_plotly_annotations",
    "toggle_modal",
    "update_shape_options",
    "update_time_display",
]
