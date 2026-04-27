"""
Callbacks module for Dash API visualization.

This module contains all callback functions organized by functionality.
"""

from clinical_data_visualizer.dash_api.callbacks.annotation_callbacks import (
    auto_load_annotations,
    cancel_annotation,
    create_annotation,
    delete_annotation,
    handle_graph_click,
    pick_color_swatch,
    render_annotations,
    save_annotations_cb,
    toggle_annotation_mode,
    update_annotation_list,
    update_modal_ui,
)
from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    build_patient_options_ui,
    close_inspection_modal,
    download_inspection_csv,
    inspect_data,
    load_db_options,
    process_visualization,
    resample_on_zoom,
)
from clinical_data_visualizer.dash_api.callbacks.loop_callbacks import (
    filter_loop_by_time,
    update_time_display,
)

__all__ = [
    "auto_load_annotations",
    "build_patient_options_ui",
    "cancel_annotation",
    "close_inspection_modal",
    "create_annotation",
    "delete_annotation",
    "download_inspection_csv",
    "filter_loop_by_time",
    "handle_graph_click",
    "inspect_data",
    "load_db_options",
    "pick_color_swatch",
    "process_visualization",
    "render_annotations",
    "resample_on_zoom",
    "save_annotations_cb",
    "toggle_annotation_mode",
    "update_annotation_list",
    "update_modal_ui",
    "update_time_display",
]
