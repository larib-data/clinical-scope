"""
Database statistics callbacks for the Dash application.

Handles triggering batch inspection across patients, polling progress,
displaying results in a modal, and CSV export.
"""

import logging
import threading
from typing import Any

from dash import ALL, Input, Output, State, callback, html
from dash.exceptions import PreventUpdate

from clinical_data_visualizer import wrapper
from clinical_data_visualizer.dash_api import validation
from clinical_data_visualizer.dash_api.styles import (
    CARD_STYLE,
    COLOR_PURPLE,
    INSPECTION_MODAL_STYLE_HIDDEN,
    INSPECTION_MODAL_STYLE_SHOWN,
)
from clinical_data_visualizer.database_statistics import (
    DatabaseStatistics,
    stats_from_json,
    stats_to_json,
    to_csv_string,
)

logger = logging.getLogger(__name__)

_MAX_COLUMNS_SHOWN = 15
_COMPLETENESS_GOOD_PCT = 70
_COMPLETENESS_MED_PCT = 40


# ---------------------------------------------------------------------------
# Shared progress state (single-user desktop app)
# ---------------------------------------------------------------------------
DB_STATS_PROGRESS: dict[str, Any] = {
    "running": False,
    "current": 0,
    "total": 0,
    "current_patient": "",
    "result": None,
    "error": None,
}


def _reset_progress() -> None:
    DB_STATS_PROGRESS["running"] = False
    DB_STATS_PROGRESS["current"] = 0
    DB_STATS_PROGRESS["total"] = 0
    DB_STATS_PROGRESS["current_patient"] = ""
    DB_STATS_PROGRESS["result"] = None
    DB_STATS_PROGRESS["error"] = None


def _run_stats_in_background(data_folder: str, db_options: dict | None) -> None:
    """Background thread target: run database_statistics and store result."""

    def on_progress(current: int, total: int, name: str) -> None:
        DB_STATS_PROGRESS["current"] = current
        DB_STATS_PROGRESS["total"] = total
        DB_STATS_PROGRESS["current_patient"] = name

    try:
        result = wrapper.database_statistics(
            patient_folders_or_root=data_folder,
            database_options_global=db_options,
            progress_callback=on_progress,
        )
        DB_STATS_PROGRESS["result"] = result
    except Exception as exc:
        logger.exception("Database statistics failed")
        DB_STATS_PROGRESS["error"] = str(exc)
    finally:
        DB_STATS_PROGRESS["running"] = False


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("db-stats-progress", "children"),
    Output("db-stats-progress-interval", "disabled"),
    Input("db-stats-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def trigger_db_stats(
    n_clicks: int,  # noqa: ARG001
    db_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
) -> tuple[Any, bool]:
    """Start database statistics computation in a background thread."""
    if DB_STATS_PROGRESS["running"]:
        return html.Div("Computation already running...", style={"color": "orange"}), False

    if not db_options:
        return html.Div("Database options not loaded.", style={"color": "red"}), True

    # Extract data_folder from form values
    schema_class_lookup = validation.rehydrate_schema_classes(schema_data)
    values_by_id = {i["name"]: v for i, v in zip(ids, values, strict=False)}
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)

    if errors:
        return html.Ul([html.Li(e) for e in errors], style={"color": "red"}), True

    data_folder = validated_dict.get("data_folder", "")
    if not data_folder:
        return html.Div("No data folder specified.", style={"color": "red"}), True

    _reset_progress()
    DB_STATS_PROGRESS["running"] = True

    thread = threading.Thread(
        target=_run_stats_in_background,
        args=(data_folder, db_options),
        daemon=True,
    )
    thread.start()

    return (
        html.Div(
            f"Starting database statistics for: {data_folder}",
            style={"color": COLOR_PURPLE, "fontWeight": "bold"},
        ),
        False,  # Enable the interval
    )


@callback(
    Output("db-stats-progress", "children", allow_duplicate=True),
    Output("db-stats-progress-interval", "disabled", allow_duplicate=True),
    Output("db-stats-modal", "style"),
    Output("db-stats-modal-content", "children"),
    Output("db-stats-results-store", "data"),
    Input("db-stats-progress-interval", "n_intervals"),
    prevent_initial_call=True,
)
def poll_db_stats_progress(
    n_intervals: int,  # noqa: ARG001
) -> tuple[Any, bool, dict, Any, dict | None]:
    """Poll background thread progress; display results when done."""
    if DB_STATS_PROGRESS["running"]:
        current = DB_STATS_PROGRESS["current"]
        total = DB_STATS_PROGRESS["total"]
        patient = DB_STATS_PROGRESS["current_patient"]

        if total > 0:
            pct = current / total * 100
            progress_text = f"Processing patient {current}/{total}: {patient} ({pct:.0f}%)"
        else:
            progress_text = "Initializing..."

        progress_bar = html.Div(
            [
                html.Div(
                    progress_text,
                    style={"marginBottom": "4px", "fontWeight": "bold", "color": COLOR_PURPLE},
                ),
                html.Div(
                    html.Div(
                        style={
                            "width": f"{pct if total > 0 else 0}%",
                            "height": "8px",
                            "backgroundColor": COLOR_PURPLE,
                            "borderRadius": "4px",
                            "transition": "width 0.3s",
                        },
                    ),
                    style={
                        "backgroundColor": "#e9ecef",
                        "borderRadius": "4px",
                        "overflow": "hidden",
                    },
                ),
            ]
        )
        return (progress_bar, False, INSPECTION_MODAL_STYLE_HIDDEN, "", None)

    # Computation finished
    error = DB_STATS_PROGRESS["error"]
    if error:
        _reset_progress()
        return (
            html.Div(f"Error: {error}", style={"color": "red"}),
            True,
            INSPECTION_MODAL_STYLE_HIDDEN,
            "",
            None,
        )

    result: DatabaseStatistics | None = DB_STATS_PROGRESS["result"]
    if result is None:
        raise PreventUpdate

    content = _build_stats_modal_content(result)
    serialized = stats_to_json(result)
    _reset_progress()

    return (
        html.Div("Database statistics complete!", style={"color": "green", "fontWeight": "bold"}),
        True,  # Disable the interval
        INSPECTION_MODAL_STYLE_SHOWN,
        content,
        serialized,
    )


@callback(
    Output("db-stats-modal", "style", allow_duplicate=True),
    Input("db-stats-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_db_stats_modal(n_clicks: int) -> dict:  # noqa: ARG001
    """Hide the database statistics modal."""
    return INSPECTION_MODAL_STYLE_HIDDEN


@callback(
    Output("db-stats-download", "data"),
    Input("db-stats-download-btn", "n_clicks"),
    State("db-stats-results-store", "data"),
    prevent_initial_call=True,
)
def download_db_stats_csv(n_clicks: int, stored: dict | None) -> dict:  # noqa: ARG001
    """Trigger a CSV download of the latest database statistics."""
    if not stored:
        raise PreventUpdate
    stats = stats_from_json(stored)
    return {
        "content": to_csv_string(stats),
        "filename": "database_statistics.csv",
        "type": "text/csv",
    }


# ---------------------------------------------------------------------------
# Modal content builder
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    "ok": "#28a745",
    "file_not_found": "#868e96",
    "load_error": "#dc3545",
    "format_error": "#fd7e14",
    "not_inspected": "#dee2e6",
}


def _status_cell(status: str) -> html.Td:
    """Create a colored table cell for a datasource status."""
    color = _STATUS_COLORS.get(status, "#dee2e6")
    label = {
        "ok": "OK",
        "file_not_found": "---",
        "load_error": "ERR",
        "format_error": "FMT",
        "not_inspected": ".",
    }.get(status, status[:3])
    return html.Td(
        label,
        style={
            "backgroundColor": color,
            "color": "white" if status in ("ok", "load_error") else "#333",
            "textAlign": "center",
            "padding": "4px 8px",
            "fontSize": "13px",
            "fontWeight": "bold",
        },
    )


def _build_stats_modal_content(stats: DatabaseStatistics) -> html.Div:
    """Build the modal content for database statistics results."""
    sections = []

    # ---- Summary header ----
    sections.append(
        html.Div(
            [
                html.Span(
                    f"{stats.total_patients} patients",
                    style={"fontWeight": "bold", "fontSize": "16px", "marginRight": "20px"},
                ),
                html.Span(
                    f"{len(stats.datasource_names)} datasources",
                    style={"fontWeight": "bold", "fontSize": "16px", "marginRight": "20px"},
                ),
                html.Span(
                    f"Root: {stats.root_folder}",
                    style={"color": "#666", "fontSize": "14px"},
                ),
            ],
            style={"marginBottom": "16px"},
        )
    )

    # ---- Presence matrix table ----
    if stats.patient_summaries:
        sections.append(html.H4("Signal Presence Matrix"))
        sections.append(
            html.Div(
                (
                    "(OK=loaded  ;;  ---=not found  ;;  ERR=load error  ;;  FMT=format error  ;;"
                    "  .=n/a)"
                ),
                style={"color": "#666", "fontSize": "12px", "marginBottom": "8px"},
            )
        )

        # Build table
        header_cells = [html.Th("Patient", style={"position": "sticky", "left": 0})]
        header_cells.extend(
            html.Th(
                ds,
                style={
                    "textAlign": "center",
                    "padding": "8px 4px",
                    "fontSize": "12px",
                    "maxWidth": "40px",
                    "wordBreak": "break-all",
                    "whiteSpace": "normal",
                },
            )
            for ds in stats.datasource_names
        )
        header_cells.append(html.Th("Completeness"))

        rows = []
        # Sort by completeness (highest first)
        sorted_summaries = sorted(
            stats.patient_summaries, key=lambda ps: ps.completeness_score, reverse=True
        )
        for ps in sorted_summaries:
            cells = [html.Td(ps.patient_name, style={"fontWeight": "bold", "whiteSpace": "nowrap"})]
            for ds in stats.datasource_names:
                status = ps.datasource_statuses.get(ds, "not_inspected")
                cells.append(_status_cell(status))
            # Completeness bar
            pct = ps.completeness_score * 100
            cells.append(
                html.Td(
                    html.Div(
                        [
                            html.Div(
                                style={
                                    "width": f"{pct}%",
                                    "height": "16px",
                                    "backgroundColor": (
                                        "#28a745"
                                        if pct >= _COMPLETENESS_GOOD_PCT
                                        else "#fd7e14"
                                        if pct >= _COMPLETENESS_MED_PCT
                                        else "#dc3545"
                                    ),
                                    "borderRadius": "3px",
                                },
                            ),
                            html.Span(
                                f"{pct:.0f}%",
                                style={
                                    "fontSize": "11px",
                                    "marginLeft": "6px",
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center", "minWidth": "80px"},
                    )
                )
            )
            rows.append(html.Tr(cells))

        table = html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody(rows)],
            style={
                "borderCollapse": "collapse",
                "width": "100%",
                "border": "1px solid #dee2e6",
                "fontSize": "13px",
            },
        )
        sections.append(html.Div(table, style={"overflowX": "auto", "marginBottom": "24px"}))

    # ---- Datasource summaries ----
    if stats.datasource_summaries:
        sections.append(html.H4("Datasource Summaries"))
        ds_cards = []
        for ds_sum in stats.datasource_summaries:
            if ds_sum.patient_count == 0:
                continue
            coverage_pct = ds_sum.config_coverage * 100
            header = html.Div(
                [
                    html.Strong(ds_sum.datasource_name),
                    html.Span(
                        f"  {ds_sum.patient_count}/{ds_sum.total_patients} patients, "
                        f"{len(ds_sum.columns)} columns, "
                        f"config coverage {coverage_pct:.0f}%",
                        style={"color": "#666", "fontSize": "13px", "marginLeft": "8px"},
                    ),
                ]
            )
            # Column stats table (top 10 by patient_count)
            col_rows = []
            sorted_cols = sorted(
                ds_sum.columns.values(), key=lambda c: c.patient_count, reverse=True
            )
            for col in sorted_cols[:_MAX_COLUMNS_SHOWN]:
                rate_str = (
                    f"{col.mean_sampling_rate_hz:.1f} Hz"
                    if col.mean_sampling_rate_hz is not None
                    else "—"
                )
                col_rows.append(
                    html.Tr(
                        [
                            html.Td(col.raw_name),
                            html.Td(f"{col.patient_count}", style={"textAlign": "right"}),
                            html.Td(f"{col.mean_points:,.0f}", style={"textAlign": "right"}),
                            html.Td(
                                f"{col.min_points:,}-{col.max_points:,}",
                                style={"textAlign": "right"},
                            ),
                            html.Td(rate_str, style={"textAlign": "right"}),
                        ]
                    )
                )
            if len(sorted_cols) > _MAX_COLUMNS_SHOWN:
                col_rows.append(
                    html.Tr(
                        html.Td(
                            f"... and {len(sorted_cols) - _MAX_COLUMNS_SHOWN} more columns",
                            colSpan=5,
                            style={"color": "#888", "fontStyle": "italic"},
                        )
                    )
                )

            col_table = html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("Column"),
                                html.Th("Patients", style={"textAlign": "right"}),
                                html.Th("Mean pts", style={"textAlign": "right"}),
                                html.Th("Min-Max pts", style={"textAlign": "right"}),
                                html.Th("Avg rate", style={"textAlign": "right"}),
                            ]
                        )
                    ),
                    html.Tbody(col_rows),
                ],
                style={
                    "width": "100%",
                    "fontSize": "12px",
                    "borderCollapse": "collapse",
                    "marginTop": "6px",
                },
            )

            ds_cards.append(
                html.Div([header, col_table], style={**CARD_STYLE, "marginBottom": "12px"})
            )

        sections.append(html.Div(ds_cards, style={"marginBottom": "24px"}))

    # ---- Temporal overlap ----
    if stats.temporal_overlap and len(stats.datasource_names) > 1:
        # Only show datasources that have at least 1 patient
        active_ds = [
            ds
            for ds in stats.datasource_names
            if any(
                stats.temporal_overlap.get(ds, {}).get(other, 0) > 0
                for other in stats.datasource_names
            )
        ]
        if active_ds:
            sections.append(html.H4("Temporal Overlap"))
            sections.append(
                html.Div(
                    "Number of patients with overlapping recording time ranges",
                    style={"color": "#666", "fontSize": "12px", "marginBottom": "8px"},
                )
            )
            header_cells = [html.Th("")]
            for ds in active_ds:
                header_cells.append(
                    html.Th(
                        ds,
                        style={
                            "writingMode": "vertical-rl",
                            "fontSize": "11px",
                            "padding": "6px 3px",
                        },
                    )
                )
            rows = []
            for ds_a in active_ds:
                cells = [html.Td(ds_a, style={"fontWeight": "bold", "fontSize": "12px"})]
                for ds_b in active_ds:
                    count = stats.temporal_overlap.get(ds_a, {}).get(ds_b, 0)
                    bg = (
                        f"rgba(111, 66, 193, {min(count / max(stats.total_patients, 1), 1) * 0.6})"
                        if count > 0
                        else "transparent"
                    )
                    cells.append(
                        html.Td(
                            str(count) if count > 0 else "",
                            style={
                                "textAlign": "center",
                                "backgroundColor": bg,
                                "padding": "4px",
                                "fontSize": "12px",
                            },
                        )
                    )
                rows.append(html.Tr(cells))

            overlap_table = html.Table(
                [html.Thead(html.Tr(header_cells)), html.Tbody(rows)],
                style={"borderCollapse": "collapse", "fontSize": "12px"},
            )
            sections.append(
                html.Div(overlap_table, style={"overflowX": "auto", "marginBottom": "24px"})
            )

    return html.Div(sections)
