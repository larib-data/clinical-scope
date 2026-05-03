"""
Callbacks module for Dash API visualization.

This module contains all callback functions organized by functionality.
"""

from clinical_data_visualizer.dash_api.callbacks.annotation_callbacks import (
    activate_group,
    auto_load_annotations,
    cancel_annotation,
    cancel_group_modal,
    create_annotation,
    default_mode,
    delete_annotation,
    delete_group,
    handle_graph_click,
    open_group_modal,
    pick_annotation_color_swatch,
    pick_group_color_swatch,
    render_annotations,
    save_annotations_cb,
    toggle_annotation_label,
    toggle_annotation_mode,
    toggle_global_checkbox_visibility,
    toggle_group_expand,
    toggle_group_labels,
    update_annotation_list,
    update_modal_ui,
)
from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    build_patient_options_ui,
    close_inspection_modal,
    download_inspection_csv,
    enable_progress_interval,
    inspect_data,
    load_db_options,
    poll_process_progress,
    process_visualization,
    resample_on_zoom,
)
from clinical_data_visualizer.dash_api.callbacks.loop_callbacks import (
    filter_loop_by_time,
    update_time_display,
)

__all__ = [
    "activate_group",
    "auto_load_annotations",
    "build_patient_options_ui",
    "cancel_annotation",
    "cancel_group_modal",
    "close_inspection_modal",
    "create_annotation",
    "default_mode",
    "delete_annotation",
    "delete_group",
    "download_inspection_csv",
    "enable_progress_interval",
    "filter_loop_by_time",
    "handle_graph_click",
    "inspect_data",
    "load_db_options",
    "open_group_modal",
    "pick_annotation_color_swatch",
    "pick_group_color_swatch",
    "poll_process_progress",
    "process_visualization",
    "render_annotations",
    "resample_on_zoom",
    "save_annotations_cb",
    "toggle_annotation_label",
    "toggle_annotation_mode",
    "toggle_global_checkbox_visibility",
    "toggle_group_expand",
    "toggle_group_labels",
    "update_annotation_list",
    "update_modal_ui",
    "update_time_display",
]
