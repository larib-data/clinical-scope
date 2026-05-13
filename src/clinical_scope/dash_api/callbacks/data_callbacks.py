"""
Data-related callbacks for Dash API visualization.

Contains callbacks for loading database options, building patient options UI,
and processing visualizations.
"""

import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
from dash import ALL, MATCH, Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from plotly_resampler import FigureResampler

import clinical_scope.constants as cst
import clinical_scope.datasource.registry as datasource
from clinical_scope import wrapper
from clinical_scope.dash_api import helper_api as ui_helper
from clinical_scope.dash_api import io, ui_components, validation
from clinical_scope.dash_api.styles import (
    BUTTON_RELOAD,
    CARD_STYLE,
    DATASOURCE_CARD_STYLE,
    INSPECTION_MODAL_STYLE_HIDDEN,
    INSPECTION_MODAL_STYLE_SHOWN,
    SECTION_HEADER_STYLE,
)
from clinical_scope.database_options_parser import (
    ValidationIssue,
    validate_database_options,
)
from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options
from clinical_scope.datasource.inspection import (
    ColumnInfo,
    results_from_json,
    results_to_json,
    to_csv_string,
)
from clinical_scope.io.paths import (
    get_database_options_path,
    get_patient_options_path,
)
from clinical_scope.signal_container import PlotModel

logger = logging.getLogger(__name__)

# Server-side caches keyed by UUID — suitable for single-user desktop app.
# Both caches grow during a session and are cleared on each process_visualization call.
# Not bounded by size — acceptable for a single-user desktop app.
# NOTE: these are distinct from the on-disk parquet cache
# (clinical_scope_output/ inside the patient folder)
# which persists across sessions for quick_load. These are ephemeral, in-memory only.
FIGURE_RESAMPLER_CACHE = {}  # FigureResampler objects for time-series zoom/pan
LOOP_DATA_CACHE = {}  # Loop trace data (x, y, time arrays) for slider filtering

# Shared progress state for process_visualization / inspect_data.
# Written by the active callback via progress_callback; read every 500 ms by
# poll_process_progress running in a concurrent Flask thread.
# CPython's GIL protects individual key assignments, but dict.update() with multiple
# keys is not atomic — a partial read is theoretically possible. Acceptable here since
# the polling callback only renders display state, not business logic.
PROCESS_PROGRESS: dict[str, Any] = {
    "running": False,
    "current": 0,
    "total": 0,
    "current_datasource": "",
    "mode": "",  # "visualize" or "inspect"
}


def clear_visualization_caches() -> None:
    """Clear all in-memory visualization caches (resampler + loop data)."""
    FIGURE_RESAMPLER_CACHE.clear()
    LOOP_DATA_CACHE.clear()


def _parse_database_options_file(
    decoded_content: bytes, filename: str
) -> tuple[dict[str, Any], list[ValidationIssue]]:
    """Parse database options from decoded file bytes and run full validation."""
    if filename.lower().endswith(".json"):
        db_options = json.loads(decoded_content.decode("utf-8"))
    elif filename.lower().endswith(".xlsx"):
        db_options = xlsx_bytes_to_database_options(decoded_content)
    else:
        msg = f"Unsupported file type '{Path(filename).suffix}'. Expected .json or .xlsx."
        raise ValueError(msg)

    issues = validate_database_options(db_options)
    for issue in issues:
        if issue.severity == "error":
            logger.error("database_options [%s]: %s", issue.path, issue.message)
        elif issue.severity == "warning":
            logger.warning("database_options [%s]: %s", issue.path, issue.message)
        else:
            logger.info("database_options [%s]: %s", issue.path, issue.message)

    return db_options, issues


def _build_load_status(filename: str, issues: list[ValidationIssue]) -> html.Div:
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    if not errors and not warnings:
        return html.Div(
            f"Successfully loaded {filename}", style={"color": "green", "fontWeight": "bold"}
        )
    _severity_color = {"error": "#dc3545", "warning": "#fd7e14"}
    items = [
        html.Li(f"[{i.path}] {i.message}", style={"color": _severity_color[i.severity]})
        for i in errors + warnings
    ]
    counts = []
    if errors:
        counts.append(f"{len(errors)} error(s)")
    if warnings:
        counts.append(f"{len(warnings)} warning(s)")
    header_color = "#dc3545" if errors else "#fd7e14"
    return html.Div(
        [
            html.Div(
                f"Loaded {filename} — {', '.join(counts)}:",
                style={"color": header_color, "fontWeight": "bold"},
            ),
            html.Ul(
                items,
                style={"margin": "4px 0 0 0", "paddingLeft": "20px", "fontSize": "12px"},
            ),
        ]
    )


@callback(
    Output("db-options-store", "data"),
    Output("db-options-status", "children"),
    Input("db-options-upload", "contents"),
    Input("default-viz-button", "n_clicks"),
    Input("reload-cached-db-button", "n_clicks"),
    State("db-options-upload", "filename"),
    prevent_initial_call=True,
)
def load_db_options(
    contents: str | None,
    n_clicks: int | None,  # noqa: ARG001
    n_clicks_reload: int | None,  # noqa: ARG001
    filename: str,
) -> tuple[dict[str, Any] | None, html.Div | None]:
    """Load database options from uploaded file, cache, or generate defaults."""

    triggered = ctx.triggered_id
    logger.info(
        "load_db_options fired | triggered=%r | filename=%r | contents_present=%s",
        triggered,
        filename,
        contents is not None,
    )

    if triggered == "default-viz-button":
        logger.info("load_db_options: generating default database options")
        return (
            datasource.generate_default_database_options(),
            html.Div(
                "Using default visualization (all sources)",
                style={"color": "green", "fontWeight": "bold"},
            ),
        )

    if triggered == "reload-cached-db-button":
        logger.info("load_db_options: reloading cached db options")
        cached = ui_helper.load_cached_db_options()
        if cached is None:
            logger.warning("load_db_options: no cached config found")
            return (
                None,
                html.Div("No cached config found.", style={"color": "red", "fontWeight": "bold"}),
            )
        logger.info("load_db_options: cached config reloaded successfully")
        return (
            cached,
            html.Div("Reloaded last config", style={"color": "green", "fontWeight": "bold"}),
        )

    if not contents:
        # This fires when dcc.Upload triggers the callback but contents is None
        # (e.g. the user opened the file picker and cancelled, or the component
        # was initialised without a file). If this fires right after the user
        # selected a file, it indicates a Dash upload bug — check the browser console.
        logger.warning(
            "load_db_options: triggered=%r but contents is None/empty "
            "(user may have cancelled the file picker, or a Dash upload issue occurred)",
            triggered,
        )
        return None, None

    try:
        logger.info("load_db_options: parsing file %r (%d bytes encoded)", filename, len(contents))
        _, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        database_options_dict, issues = _parse_database_options_file(decoded, filename)
        logger.info(
            "load_db_options: parsed successfully, keys=%s",
            list(database_options_dict.keys()),
        )

        ui_helper.save_cached_db_options(database_options_dict)

        return database_options_dict, _build_load_status(filename, issues)

    except Exception as e:
        logger.exception("load_db_options: failed to parse %r", filename)
        return (
            None,
            html.Div(f"Error loading file: {e!s}", style={"color": "red", "fontWeight": "bold"}),
        )


@callback(
    Output("patient-options-ui", "children"),
    Output("schema-registry", "data"),
    Input("db-options-store", "data"),
    prevent_initial_call=True,
)
def build_patient_options_ui(
    database_options: dict[str, Any] | None,
) -> tuple[list[Any] | None, dict[str, str]]:
    """Build the patient options UI based on loaded database options."""
    if not database_options:
        return None, {}

    components = []
    schema_lookup = {}

    # Global options
    components.append(html.H3("Global Patient Options", style=SECTION_HEADER_STYLE))
    _reload_patient_btn = html.Button(
        "Reload patient options",
        id="reload-patient-options-btn",
        n_clicks=0,
        style={**BUTTON_RELOAD, "marginLeft": "8px", "marginRight": "0", "whiteSpace": "nowrap"},
    )
    component, schema = ui_components.build_ui_and_schema_registry(
        cst.PatientOptions,
        prefix="global",
        extra_per_field={"global.data_folder": [_reload_patient_btn]},
    )
    components.append(html.Div(component, style=CARD_STYLE))
    schema_lookup = schema_lookup | schema

    # Per-datasource options
    components.append(html.H3("Specific Options", style=SECTION_HEADER_STYLE))

    datasource_cards = []
    requested_data_sources = database_options.keys()
    for data_source in datasource.DataSource.AVAILABLE:
        if data_source.NAME not in requested_data_sources:
            continue

        component, schema = ui_components.build_ui_and_schema_registry(
            data_source.OPTIONS.PatientOptionsDataSourceRelative,
            prefix=f"specific.{data_source.NAME}",
        )
        datasource_cards.append(
            html.Div(
                [html.H5(data_source.DESCRIPTION), component],
                style=DATASOURCE_CARD_STYLE,
            )
        )
        schema_lookup = schema_lookup | schema

    components.append(
        html.Div(
            datasource_cards,
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr",
                "gap": "12px",
            },
        )
    )

    schema_data = {k: v.__name__ for k, v in schema_lookup.items()}

    return components, schema_data


@callback(
    Output({"type": "patient-option", "name": ALL}, "value"),
    Output("patient-options-reload-status", "children"),
    Input("reload-patient-options-btn", "n_clicks"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def reload_patient_options(
    n_clicks: int,
    current_values: list[Any],
    ids: list[dict[str, str]],
) -> tuple[list[Any], Any]:
    """Reload patient options from the saved JSON in the current patient folder."""
    if not n_clicks:
        raise PreventUpdate

    values_by_id = {id_["name"]: val for id_, val in zip(ids, current_values, strict=False)}
    data_folder = values_by_id.get("global.data_folder")

    if not data_folder:
        return current_values, html.Span("No patient folder specified.", style={"color": "#e67e00"})

    try:
        saved = io.load_patient_options(data_folder)
    except (ValueError, TypeError) as e:
        logger.warning("Failed to reload patient options: %s", e)
        return current_values, html.Span(str(e), style={"color": "#dc3545"})
    if saved is None:
        return current_values, html.Span(
            "No saved patient options found.", style={"color": "#e67e00"}
        )

    new_values = []
    for id_, current_val in zip(ids, current_values, strict=False):
        field_id = id_["name"]
        parts = field_id.split(".")

        if field_id == "global.data_folder":
            new_values.append(current_val)  # keep the path the user typed
        elif parts[0] == "global":
            new_values.append(saved.get(parts[1], current_val))
        elif parts[0] == "specific" and len(parts) == 3:  # noqa: PLR2004
            new_values.append(saved.get(parts[1], {}).get(parts[2], current_val))
        else:
            new_values.append(current_val)

    return new_values, ""


def _rehydrate_schema_classes(schema_data: dict) -> dict[str, type]:
    """Rehydrate schema classes from schema_data dictionary."""
    schema_class_lookup = {}
    for k, v in schema_data.items():
        if k.startswith("global"):
            schema_class_lookup[k] = getattr(cst.PatientOptions, v)
        elif k.startswith("specific"):
            parts = k.split(".")
            datasource_name = parts[1] if len(parts) > 1 else None
            datasource_class = datasource.DataSource.get_subclass_by_name(datasource_name)
            logger.debug("parts: %s", parts)
            logger.debug("datasource_name: %s", datasource_name)
            logger.debug("datasource_class: %s", datasource_class)
            schema_class_lookup[k] = getattr(
                datasource_class.OPTIONS.PatientOptionsDataSourceRelative, v
            )
    return schema_class_lookup


@callback(
    Output("process-progress-interval", "disabled"),
    Input("process-button", "n_clicks"),
    Input("inspect-button", "n_clicks"),
    prevent_initial_call=True,
)
def enable_progress_interval(
    n_proc: int | None,  # noqa: ARG001
    n_insp: int | None,  # noqa: ARG001
) -> bool:
    """Enable the progress interval as soon as either action button is clicked."""
    return False


@callback(
    Output({"type": "graph", "name": MATCH}, "figure", allow_duplicate=True),
    Input({"type": "graph", "name": MATCH}, "relayoutData"),
    State({"type": "resampler-store", "name": MATCH}, "data"),
    prevent_initial_call=True,
)
def resample_on_zoom(relayout: dict[str, Any], resampler_uid: str | None) -> Any:
    """Resample time-series traces when the user zooms or pans."""
    if not relayout or not resampler_uid or resampler_uid not in FIGURE_RESAMPLER_CACHE:
        raise PreventUpdate
    result = FIGURE_RESAMPLER_CACHE[resampler_uid].construct_update_data_patch(relayout)
    if result is no_update:
        raise PreventUpdate
    return result


@callback(
    Output("visualization-container", "children"),
    Output("validation-errors", "children"),
    Output("process-status", "children"),
    Output("folder-visu-path", "data"),
    Output("process-progress-interval", "disabled", allow_duplicate=True),
    Output("process-progress", "children", allow_duplicate=True),
    Input("process-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def process_visualization(
    n_clicks: int,  # noqa: ARG001
    db_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
) -> tuple[Any, Any, Any, str | None, bool, str]:
    """Process visualization request with validated patient options."""
    interval_off, progress_clear = True, ""
    if not db_options:
        return (
            None,
            "Database options not loaded",
            None,
            None,
            interval_off,
            progress_clear,
        )

    schema_class_lookup = _rehydrate_schema_classes(schema_data)

    # Map IDs to values
    logger.debug("ids: %s", ids)
    logger.debug("values: %s", values)
    values_by_id = {i["name"]: v for i, v in zip(ids, values, strict=False)}

    # Validate
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)
    logger.debug("errors: %s", errors)
    logger.debug("validated_dict: %s", validated_dict)

    if errors:
        return (
            None,
            html.Ul([html.Li(e) for e in errors]),
            None,
            None,
            interval_off,
            progress_clear,
        )

    # Save JSON exactly as before
    data_folder = validated_dict["data_folder"]
    patient_options_path = get_patient_options_path(data_folder)
    name_folder_visu = str(data_folder)
    ui_helper.save_json(validated_dict, patient_options_path)
    db_options_path = get_database_options_path(data_folder)
    ui_helper.save_json(db_options, db_options_path)

    clear_visualization_caches()
    PROCESS_PROGRESS.update(
        {"running": True, "current": 0, "total": 0, "current_datasource": "", "mode": "visualize"}
    )

    def _on_progress(current: int, total: int, name: str) -> None:
        PROCESS_PROGRESS.update({"current": current, "total": total, "current_datasource": name})

    logger.info("Processing visualization request for: %s", validated_dict.get("data_folder", "?"))
    try:
        model = wrapper.main(
            patient_options=validated_dict,
            database_options_global=db_options,
            progress_callback=_on_progress,
        )
        PlotModel.to_html(model, validated_dict)
        graphs = _build_graphs(model)
    except Exception as e:
        logger.exception("Could not make the plot: ")
        return (
            None,
            None,
            html.Div(
                [
                    html.Span("Visualization failed: ", style={"fontWeight": "bold"}),
                    html.Span(str(e)),
                    html.Div(
                        "See application logs for details.",
                        style={"color": "#999", "fontSize": "12px", "marginTop": "4px"},
                    ),
                ],
                style={"color": "red"},
            ),
            None,
            interval_off,
            progress_clear,
        )
    finally:
        PROCESS_PROGRESS["running"] = False

    logger.info("Visualization succeeded: %d plot model(s) generated.", len(model))
    return (
        graphs,
        None,
        html.Div(
            f"Visualization succeeded — {len(model)} plot(s) generated.",
            style={"color": "green"},
        ),
        name_folder_visu,
        interval_off,
        progress_clear,
    )


def _status_badge(status: str) -> html.Span:
    """Return a coloured inline badge for a datasource status."""
    color = {
        "ok": "#28a745",
        "file_not_found": "#fd7e14",
        "load_error": "#dc3545",
        "format_error": "#dc3545",
    }.get(status, "#6c757d")
    return html.Span(
        status,
        style={
            "backgroundColor": color,
            "color": "white",
            "padding": "2px 8px",
            "borderRadius": "4px",
            "fontSize": "12px",
            "marginLeft": "8px",
            "verticalAlign": "middle",
        },
    )


# Per-column Dash styles, indexed to match ColumnInfo.DISPLAY_HEADERS order.
# Adding a new ColumnInfo field: update ColumnInfo, _column_infos (datasource_base),
# ColumnInfo.DISPLAY_HEADERS + column_display_values (inspection), and this list.
_COL_CELL_STYLES: list[dict | None] = [
    {"fontFamily": "monospace", "fontSize": "13px"},  # Column
    None,  # Configured — style computed dynamically below
    {"textAlign": "right"},  # Raw pts
    {"textAlign": "right"},  # Filtered pts
    {"textAlign": "right"},  # % retained
    {"textAlign": "left", "fontSize": "11px"},  # First (filtered)
    {"textAlign": "left", "fontSize": "11px"},  # Last (filtered)
]


def _col_cell(col: ColumnInfo) -> list[html.Td]:
    """
    Return <td> cells for one ColumnInfo row.

    Text content comes from ``column_display_values`` (shared with CLI);
    Dash-specific styling is applied per-column via ``_COL_CELL_STYLES``.
    """
    values = col.display_values()
    cells = []
    for (_, align), val, extra in zip(
        ColumnInfo.DISPLAY_HEADERS, values, _COL_CELL_STYLES, strict=True
    ):
        style: dict = {"textAlign": align}
        if extra:
            style |= extra
        cells.append(html.Td(val, style=style))
    # Override "Configured" column color based on actual value
    cells[1] = html.Td(
        values[1],
        style={
            "textAlign": "center",
            "color": "#28a745" if col.is_configured else "#aaa",
        },
    )
    return cells


def _build_inspection_content(results: list) -> list:
    """Build modal content from a list of DataSourceInspection objects."""
    sections = []
    for r in results:
        meta_parts = []
        if r.file_path:
            meta_parts.append(
                html.Div(f"File: {r.file_path}", style={"fontSize": "12px", "color": "#666"})
            )
        if r.raw_date_range:
            meta_parts.append(
                html.Div(
                    f"Date range in file: {r.raw_date_range[0]}  →  {r.raw_date_range[1]}",
                    style={"fontSize": "12px", "color": "#666"},
                )
            )
        if r.filtered_date_range:
            meta_parts.append(
                html.Div(
                    f"After filter:        "
                    f"{r.filtered_date_range[0]}  →  {r.filtered_date_range[1]}",
                    style={"fontSize": "12px", "color": "#666"},
                )
            )
        if r.error_message:
            meta_parts.append(
                html.Div(
                    f"Error: {r.error_message}",
                    style={"fontSize": "12px", "color": "#dc3545"},
                )
            )

        table_rows = [html.Tr(_col_cell(col)) for col in r.columns]

        table = (
            html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th(header, style={"textAlign": align})
                                for header, align in ColumnInfo.DISPLAY_HEADERS
                            ]
                        )
                    ),
                    html.Tbody(table_rows),
                ],
                className="table table-sm table-hover",
                style={"marginTop": "8px"},
            )
            if table_rows
            else html.Div(
                "No columns found.", style={"color": "#999", "fontSize": "13px", "marginTop": "8px"}
            )
        )

        sections.append(
            html.Div(
                [
                    html.H4(
                        [r.datasource_name, _status_badge(r.status)],
                        style={"marginBottom": "6px"},
                    ),
                    *meta_parts,
                    table,
                ],
                style={
                    "marginBottom": "24px",
                    "paddingBottom": "16px",
                    "borderBottom": "1px solid #dee2e6",
                },
            )
        )
    return sections


@callback(
    Output("inspection-modal", "style"),
    Output("inspection-modal-content", "children"),
    Output("inspection-results-store", "data"),
    Output("inspect-status", "children"),
    Output("process-progress-interval", "disabled", allow_duplicate=True),
    Output("process-progress", "children", allow_duplicate=True),
    Input("inspect-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def inspect_data(
    n_clicks: int,  # noqa: ARG001
    db_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
) -> tuple[dict, Any, list | None, None, bool, str]:
    """Run data inspection for all enabled datasources and display results in modal."""
    interval_off, progress_clear = True, ""

    if not db_options:
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Div("Database options not loaded.", style={"color": "red"}),
            None,
            None,
            interval_off,
            progress_clear,
        )

    schema_class_lookup = _rehydrate_schema_classes(schema_data)
    values_by_id = {i["name"]: v for i, v in zip(ids, values, strict=False)}
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)

    if errors:
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Ul([html.Li(e) for e in errors]),
            None,
            None,
            interval_off,
            progress_clear,
        )

    PROCESS_PROGRESS.update(
        {"running": True, "current": 0, "total": 0, "current_datasource": "", "mode": "inspect"}
    )

    def _on_progress(current: int, total: int, name: str) -> None:
        PROCESS_PROGRESS.update({"current": current, "total": total, "current_datasource": name})

    logger.info("Running inspection for: %s", validated_dict.get("data_folder", "?"))
    try:
        results = wrapper.inspect(
            patient_options=validated_dict,
            database_options_global=db_options,
            progress_callback=_on_progress,
        )
    except Exception as e:
        logger.exception("Inspection failed: ")
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Div(f"Inspection failed: {e}", style={"color": "red"}),
            None,
            None,
            interval_off,
            progress_clear,
        )
    finally:
        PROCESS_PROGRESS["running"] = False

    content = _build_inspection_content(results)
    return (
        INSPECTION_MODAL_STYLE_SHOWN,
        content,
        results_to_json(results),
        None,
        interval_off,
        progress_clear,
    )


@callback(
    Output("inspection-modal", "style", allow_duplicate=True),
    Input("inspection-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_inspection_modal(n_clicks: int) -> dict:  # noqa: ARG001
    """Hide the inspection modal when the Close button is clicked."""
    return INSPECTION_MODAL_STYLE_HIDDEN


@callback(
    Output("inspection-download", "data"),
    Input("inspect-download-btn", "n_clicks"),
    State("inspection-results-store", "data"),
    prevent_initial_call=True,
)
def download_inspection_csv(n_clicks: int, stored: list | None) -> dict:  # noqa: ARG001
    """Trigger a CSV download of the latest inspection results."""

    if not stored:
        raise PreventUpdate
    results = results_from_json(stored)
    return {
        "content": to_csv_string(results),
        "filename": "data_inspection.csv",
        "type": "text/csv",
    }


_PROGRESS_BAR_COLOR = {"visualize": "#fd7e14", "inspect": "#17a2b8"}
_PROGRESS_BAR_LABEL = {"visualize": "Visualizing", "inspect": "Inspecting"}


@callback(
    Output("process-progress", "children"),
    Input("process-progress-interval", "n_intervals"),
)
def poll_process_progress(n_intervals: int) -> Any:  # noqa: ARG001
    """Update the per-datasource progress bar while a long operation is running."""
    if not PROCESS_PROGRESS["running"]:
        raise PreventUpdate

    current = PROCESS_PROGRESS["current"]
    total = PROCESS_PROGRESS["total"]
    name = PROCESS_PROGRESS["current_datasource"]
    mode = PROCESS_PROGRESS["mode"]

    if total == 0:
        return html.Div("Starting...", style={"fontSize": "13px", "color": "#666"})

    # Bar tracks completed sources; label names the active one — the two are intentionally
    # decoupled so the bar never shows 100% while the last datasource is still processing.
    # TODO: reset current_datasource="" at run start so a stale name doesn't flash briefly
    #       on the next run before the first progress_callback fires.
    pct = int((current - 1) / total * 100)
    label = f"{_PROGRESS_BAR_LABEL.get(mode, 'Processing')} ({current}/{total}): {name}"
    bar_color = _PROGRESS_BAR_COLOR.get(mode, "#6c757d")

    return html.Div(
        [
            html.Div(label, style={"fontSize": "13px", "color": "#555", "marginBottom": "4px"}),
            html.Div(
                html.Div(
                    style={
                        "width": f"{pct}%",
                        "backgroundColor": bar_color,
                        "height": "8px",
                        "borderRadius": "4px",
                        "transition": "width 0.3s",
                    }
                ),
                style={
                    "backgroundColor": "#e9ecef",
                    "borderRadius": "4px",
                    "overflow": "hidden",
                    "width": "300px",
                },
            ),
        ],
        style={"marginTop": "4px"},
    )


_ONE_DAY_SECONDS = 86400


def _build_slider_marks(t_min: float, duration: float, n_marks: int = 5) -> dict[float, str]:
    """
    Build evenly-spaced marks for a RangeSlider using relative-second keys.

    Keys are seconds offset from t_min (0 … duration).
    Labels are absolute clock times in DISPLAY_TIMEZONE so the user sees
    human-readable timestamps, not raw numbers.
    """
    display_tz = ZoneInfo(cst.DISPLAY_TIMEZONE)
    fmt = "%m/%d %H:%M" if duration > _ONE_DAY_SECONDS else "%H:%M:%S"
    marks = {}
    for i in range(n_marks + 1):
        offset = duration * i / n_marks
        dt = datetime.fromtimestamp(t_min + offset, tz=UTC).astimezone(display_tz)
        marks[float(offset)] = dt.strftime(fmt)
    return marks


def format_time_range(t_start: float, t_end: float) -> str:
    """Format a time range as a human-readable string in DISPLAY_TIMEZONE."""
    display_tz = ZoneInfo(cst.DISPLAY_TIMEZONE)
    dt_start = datetime.fromtimestamp(t_start, tz=UTC).astimezone(display_tz)
    dt_end = datetime.fromtimestamp(t_end, tz=UTC).astimezone(display_tz)
    fmt = "%Y-%m-%d %H:%M:%S"
    return f"{dt_start.strftime(fmt)}  —  {dt_end.strftime(fmt)}"


def _build_graphs(model: Any) -> list[html.Div]:
    """
    Build list of dcc.Graph + dcc.Store components from model.

    Time-series figures are wrapped with FigureResampler for dynamic
    downsampling on zoom/pan. A companion dcc.Store holds the cache UUID
    so the resample_on_zoom callback can retrieve the server-side object.

    Loop figures get a time-range slider for interactive time filtering.
    """
    graphs = []

    for mod in model:
        fig = mod.figure

        # Wrap time_series with FigureResampler for dynamic downsampling
        uid = None
        if mod.name == "time_series":
            uid = str(uuid4())
            fig = FigureResampler(fig)
            FIGURE_RESAMPLER_CACHE[uid] = fig

        # Set explicit CSS height so the container matches the figure's intended
        # height.  Without this, Plotly's default autosize=True sizes the figure
        # to its container, and an unsized container collapses to a default that
        # can hide the plot (especially for time-series with few subplots).
        graph_height = int(mod.computed_height) if mod.computed_height else None
        graph_style = {"marginBottom": "40px"}
        if graph_height:
            graph_style["height"] = f"{graph_height}px"

        # --- Build annotation metadata stores from the PlotModel ---
        # These are read by annotation_callbacks to know subplot names and axis refs.
        # Must be built from mod.figure (original go.Figure) before FigureResampler wraps it.
        is_loop = mod.plot_type == cst.PlotType.LOOP
        n_cols_layout = 2 if (is_loop and len(mod.groups) > 1) else 1

        signal_meta_lookup: dict[str, dict] = {
            sig.name: {
                "raw_name": sig.raw_name,
                "datasource_name": sig.metadata.datasource_name or "",
            }
            for group in mod.groups
            for sig in group.signals
        }
        trace_map: dict[str, dict] = {}
        for trace_idx, trace in enumerate(mod.figure.data):
            trace_name = getattr(trace, "name", "") or ""
            meta = signal_meta_lookup.get(trace_name, {})
            trace_color: str | None = None
            try:
                if getattr(trace, "line", None) and getattr(trace.line, "color", None):
                    trace_color = trace.line.color
                elif getattr(trace, "marker", None) and isinstance(
                    getattr(trace.marker, "color", None), str
                ):
                    trace_color = trace.marker.color
            except (AttributeError, TypeError):
                pass
            trace_map[f"curve_{trace_idx}"] = {
                "yaxis": getattr(trace, "yaxis", None) or "y",
                "xaxis": getattr(trace, "xaxis", None) or "x",
                "display_name": trace_name,
                "raw_name": meta.get("raw_name", ""),
                "datasource_name": meta.get("datasource_name", ""),
                "line_color": trace_color,
            }

        subplot_rows = []
        # Build mapping from yaxis reference to subplot name.
        # Traces are added to the figure in group order, so we can iterate
        # through mod.figure.data and assign each trace's yaxis to its group's subplot.
        yaxis_to_subplot: dict[str, dict] = {}
        trace_idx = 0
        for group_idx, group in enumerate(mod.groups):
            plotly_row = group_idx // n_cols_layout + 1
            plotly_col = group_idx % n_cols_layout + 1

            # Get the primary y-axis for this subplot (first trace's yaxis)
            primary_yaxis = "y"
            if trace_idx < len(mod.figure.data):
                primary_yaxis = getattr(mod.figure.data[trace_idx], "yaxis", None) or "y"

            subplot_rows.append(
                {
                    "row": plotly_row,
                    "col": plotly_col,
                    "name": group.name,
                    "yaxis": primary_yaxis,
                }
            )

            # Add all traces from this group to the mapping
            n_traces_in_group = len(group.signals)
            for _ in range(n_traces_in_group):
                if trace_idx < len(mod.figure.data):
                    trace = mod.figure.data[trace_idx]
                    yaxis_ref = getattr(trace, "yaxis", None) or "y"
                    yaxis_to_subplot[yaxis_ref] = {
                        "row": plotly_row,
                        "col": plotly_col,
                        "name": group.name,
                    }
                    trace_idx += 1

        # Capture subplot title annotations injected by make_subplots so the
        # annotation renderer can restore them when it replaces layout.annotations.
        subplot_title_annotations: list[dict] = []
        if mod.figure.layout.annotations:
            subplot_title_annotations = [
                ann.to_plotly_json() for ann in mod.figure.layout.annotations
            ]

        graph_subplots_data = {
            "rows": subplot_rows,
            "yaxis_to_subplot": yaxis_to_subplot,
            "subplot_annotations": subplot_title_annotations,
            "plot_type": mod.plot_type,
            "n_cols": n_cols_layout,
            "display_timezone": cst.DISPLAY_TIMEZONE,
        }

        children = [
            dcc.Graph(
                id={"type": "graph", "name": mod.name},
                figure=fig,
                config={"displayModeBar": True},
                style=graph_style,
            ),
            dcc.Store(id={"type": "resampler-store", "name": mod.name}, data=uid),
            dcc.Store(id={"type": "graph-subplots", "name": mod.name}, data=graph_subplots_data),
            dcc.Store(id={"type": "graph-trace-map", "name": mod.name}, data=trace_map),
        ]

        # --- Loop time-range slider ---
        if mod.plot_type == cst.PlotType.LOOP:
            loop_uid = str(uuid4())

            # Cache full data arrays for each trace.
            # Skip traces with missing data to keep cache indices aligned
            # with the Plotly figure traces that are actually filterable.
            trace_data = []
            t_min_global = np.inf
            t_max_global = -np.inf
            for group in mod.groups:
                for sig in group.signals:
                    time_array = sig.data.loop_time_axis
                    if time_array is None or sig.data.x is None or sig.data.y is None:
                        trace_data.append({"x": None, "y": None, "time_axis": None})
                        continue
                    if len(time_array) > 0:
                        t_min_global = min(t_min_global, time_array[0])
                        t_max_global = max(t_max_global, time_array[-1])
                    trace_data.append(
                        {
                            "x": sig.data.x,
                            "y": sig.data.y,
                            "time_axis": time_array,
                        }
                    )

            # Store t_min alongside traces so callbacks can convert relative
            # offsets back to absolute epoch seconds for display/masking.
            # Convert to native Python float for orjson serialization safety.
            t_min_f = float(t_min_global) if np.isfinite(t_min_global) else 0.0
            LOOP_DATA_CACHE[loop_uid] = {"traces": trace_data, "t_min": t_min_f}
            children.append(dcc.Store(id={"type": "loop-store", "name": mod.name}, data=loop_uid))

            if np.isfinite(t_min_global) and t_min_global < t_max_global:
                duration = float(t_max_global) - t_min_f
                step = 1
                marks = _build_slider_marks(t_min_f, duration)

                children.append(
                    html.Div(
                        [
                            html.Label(
                                "Time range",
                                style={
                                    "fontWeight": "bold",
                                    "marginBottom": "4px",
                                    "display": "block",
                                },
                            ),
                            dcc.RangeSlider(
                                id={"type": "loop-time-slider", "name": mod.name},
                                min=0.0,
                                max=duration,
                                value=[0.0, duration],
                                marks=marks,
                                step=step,
                                updatemode="mouseup",
                                # No tooltip: raw offset seconds are not meaningful to the user.
                                tooltip=None,
                            ),
                            html.Div(
                                format_time_range(t_min_f, t_min_f + duration),
                                id={"type": "loop-time-display", "name": mod.name},
                                style={
                                    "textAlign": "center",
                                    "color": "#555",
                                    "fontSize": "13px",
                                    "marginTop": "4px",
                                },
                            ),
                        ],
                        style={
                            "padding": "12px 16px",
                            "border": "1px solid #dee2e6",
                            "borderRadius": "6px",
                            "backgroundColor": "#f8f9fa",
                            "marginTop": "8px",
                        },
                    )
                )

        graphs.append(html.Div(children))

    return graphs
