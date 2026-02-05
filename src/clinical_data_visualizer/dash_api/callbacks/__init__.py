"""
Callbacks module for Dash API visualization.

This module contains all callback functions organized by functionality.
"""

from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    build_patient_options_ui,
    load_db_options,
    process_visualization,
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
    "load_db_options",
    "build_patient_options_ui",
    "process_visualization",
    "sync_plotly_annotations",
    "lock_and_style_shapes",
    "persist_shapes",
    "save_annotations_and_shapes",
    "update_shape_options",
    "toggle_modal",
    "modify_shape",
]
