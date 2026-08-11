"""
Data-related callbacks for Dash API visualization.

Covers loading database options, building the patient-options form from them, and the
two actions that form drives: Process (build figures) and Inspect (report columns).
"""

import base64
import concurrent.futures
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from clinical_scope.datasource.formatting.timezone import (
    resolve_display_timezone,
    to_aware_display_ts,
    to_naive_display_ts,
)
from clinical_scope.datasource.inspection import (
    PRUNED_VIEW_NOTICE,
    ColumnInfo,
    results_from_json,
    results_to_json,
    to_csv_string,
)
from clinical_scope.io.paths import (
    get_database_options_path,
    get_output_base,
    get_patient_options_path,
)
from clinical_scope.signal_container import PlotModel

logger = logging.getLogger(__name__)

# Server-side caches keyed by UUID. Unbounded — they grow through a session and are cleared
# on each process_visualization call, which is acceptable for a single-user desktop app.
# Distinct from the on-disk parquet cache (clinical_scope_output/), which persists for quick_load.
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
        database_options = json.loads(decoded_content.decode("utf-8"))
    elif filename.lower().endswith(".xlsx"):
        database_options = xlsx_bytes_to_database_options(decoded_content)
    else:
        msg = f"Unsupported file type '{Path(filename).suffix}'. Expected .json or .xlsx."
        raise ValueError(msg)

    issues = validate_database_options(database_options)
    for issue in issues:
        if issue.severity == "error":
            logger.error("database_options [%s]: %s", issue.path, issue.message)
        elif issue.severity == "warning":
            logger.warning("database_options [%s]: %s", issue.path, issue.message)
        else:
            logger.info("database_options [%s]: %s", issue.path, issue.message)

    return database_options, issues


def _build_load_status(filename: str, issues: list[ValidationIssue]) -> html.Div:
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    if not errors and not warnings:
        return html.Div(
            f"Successfully loaded {filename}", style={"color": "green", "fontWeight": "bold"}
        )
    severity_color = {"error": "#dc3545", "warning": "#fd7e14"}
    items = [
        html.Li(f"[{issue.path}] {issue.message}", style={"color": severity_color[issue.severity]})
        for issue in errors + warnings
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
def load_database_options(
    contents: str | None,
    n_clicks: int | None,  # noqa: ARG001
    n_clicks_reload: int | None,  # noqa: ARG001
    filename: str,
) -> tuple[dict[str, Any] | None, html.Div | None]:
    """Load database options from uploaded file, cache, or generate defaults."""

    triggered = ctx.triggered_id
    logger.info(
        "load_database_options fired | triggered=%r | filename=%r | contents_present=%s",
        triggered,
        filename,
        contents is not None,
    )

    if triggered == "default-viz-button":
        logger.info("load_database_options: generating default database options")
        return (
            datasource.generate_default_database_options(),
            html.Div(
                "Using default visualization (all sources)",
                style={"color": "green", "fontWeight": "bold"},
            ),
        )

    if triggered == "reload-cached-db-button":
        logger.info("load_database_options: reloading cached db options")
        cached = ui_helper.load_cached_database_options()
        if cached is None:
            logger.warning("load_database_options: no cached config found")
            return (
                None,
                html.Div("No cached config found.", style={"color": "red", "fontWeight": "bold"}),
            )
        logger.info("load_database_options: cached config reloaded successfully")
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
            "load_database_options: triggered=%r but contents is None/empty "
            "(user may have cancelled the file picker, or a Dash upload issue occurred)",
            triggered,
        )
        return None, None

    try:
        logger.info(
            "load_database_options: parsing file %r (%d bytes encoded)", filename, len(contents)
        )
        _, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        database_options_dict, issues = _parse_database_options_file(decoded, filename)
        logger.info(
            "load_database_options: parsed successfully, keys=%s",
            list(database_options_dict.keys()),
        )

        ui_helper.save_cached_database_options(database_options_dict)

        return database_options_dict, _build_load_status(filename, issues)

    except Exception as exc:
        logger.exception("load_database_options: failed to parse %r", filename)
        return (
            None,
            html.Div(f"Error loading file: {exc!s}", style={"color": "red", "fontWeight": "bold"}),
        )


def _options_card(schema_class: Any, prefix: str, title: str) -> tuple[html.Div, dict]:
    """Build one patient-options card, and the schema lookup for the widgets inside it."""
    component, schema = ui_components.build_ui_and_schema_registry(schema_class, prefix=prefix)
    return html.Div([html.H5(title), component], style=DATASOURCE_CARD_STYLE), schema


def _other_file_stems(database_options: dict[str, Any]) -> list[str]:
    """
    List the file stems declared for the 'other' datasource, from config alone.

    Reads both dict shapes: the raw ``other::<stem>`` top-level keys the store holds, and the
    ``other.files`` form :func:`normalize_database_options` produces. Never scans the patient
    folder — widgets follow the config, like every other card here.
    """
    section = database_options.get(datasource.DataSource.Other.NAME) or {}
    return sorted(
        {
            key[len(cst.OTHER_FILE_PREFIX) :]
            for key in database_options
            if key.startswith(cst.OTHER_FILE_PREFIX)
        }
        | set(section.get(cst.DatabaseOptions.FILES, {}))
    )


def _other_cards(
    other_source: Any, database_options: dict[str, Any], file_stems: list[str]
) -> list[tuple[html.Div, dict]]:
    """
    Build the 'other' cards: one per declared file, plus the generic one when it still earns a spot.

    Each file is a peer of a datasource here, titled by its own ``other::<stem>`` token, so a
    curated 3-column export and a 90-column raw dump no longer share one time_shift.

    The generic card covers files present on disk but absent from database_options. It is
    dropped only when per-file cards exist *and* the ``other`` section holds nothing but them —
    a fully-itemized config gets no leftover card, while a config with generic content (or none
    at all, as after Default visualization) keeps the safety net.
    """
    schema_class = other_source.OPTIONS.PatientOptionsDataSourceRelative
    section = database_options.get(other_source.NAME)
    if section is None and not file_stems:
        return []

    cards = []
    generic_content = set(section or {}) - {cst.DatabaseOptions.FILES}
    if generic_content or not file_stems:
        cards.append(
            _options_card(
                schema_class, prefix=f"specific.{other_source.NAME}", title=other_source.DESCRIPTION
            )
        )

    token_prefix = other_source.NAME + cst.QUALIFIED_NAME_SEPARATOR
    cards.extend(
        _options_card(
            schema_class, prefix=f"specific.{token_prefix}{stem}", title=f"{token_prefix}{stem}"
        )
        for stem in file_stems
    )
    return cards


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
        style={
            **BUTTON_RELOAD,
            "marginLeft": "8px",
            "marginRight": "0",
        },
    )
    _reload_status = html.Div(
        id="patient-options-reload-status",
        style={
            "fontSize": "12px",
            "marginLeft": "8px",
            "width": "320px",
            "display": "flex",
            "flexDirection": "column",
        },
    )
    _datetime_tz_label_style = {"fontSize": "12px", "color": "#666"}
    _datetime_tz_label_start = html.Span(
        id="datetime-tz-label-start", style=_datetime_tz_label_style
    )
    _datetime_tz_label_end = html.Span(id="datetime-tz-label-end", style=_datetime_tz_label_style)
    component, schema = ui_components.build_ui_and_schema_registry(
        cst.PatientOptions,
        prefix=cst.PatientOptions.GLOBAL,
        extra_per_field={
            f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.PathDataFolder.NAME}": [
                _reload_patient_btn,
                _reload_status,
            ],
            f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.DatetimeStart.NAME}": [
                _datetime_tz_label_start
            ],
            f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.DatetimeEnd.NAME}": [
                _datetime_tz_label_end
            ],
        },
    )
    components.append(html.Div(component, style=CARD_STYLE))
    components.append(
        html.Div(
            id="data-folder-preview",
            style={"margin": "-4px 0 12px 4px", "fontSize": "13px"},
        )
    )
    schema_lookup = schema_lookup | schema

    # Per-datasource options
    components.append(html.H3("Specific Options", style=SECTION_HEADER_STYLE))

    datasource_cards = []
    requested_data_sources = database_options.keys()
    other_name = datasource.DataSource.Other.NAME
    other_file_stems = _other_file_stems(database_options)

    for data_source in datasource.DataSource.AVAILABLE:
        if other_name == data_source.NAME:
            for card, schema in _other_cards(data_source, database_options, other_file_stems):
                datasource_cards.append(card)
                schema_lookup = schema_lookup | schema
            continue

        if data_source.NAME not in requested_data_sources:
            continue

        card, schema = _options_card(
            data_source.OPTIONS.PatientOptionsDataSourceRelative,
            prefix=f"specific.{data_source.NAME}",
            title=data_source.DESCRIPTION,
        )
        datasource_cards.append(card)
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

    schema_data = {key: value.__name__ for key, value in schema_lookup.items()}

    return components, schema_data


@callback(
    Output("datetime-tz-label-start", "children"),
    Output("datetime-tz-label-end", "children"),
    Input({"type": "user-option", "name": "user_options.display_timezone"}, "value"),
)
def update_datetime_tz_label(display_timezone: str | None) -> tuple[str, str]:
    """
    Show which timezone the datetime-window fields are typed in.

    Resolves through :func:`resolve_display_timezone` instead of echoing the raw widget
    value, so a mid-typed or invalid name is never shown as if it were in effect.
    """
    label = f"interpreted in {resolve_display_timezone(display_timezone)}"
    return label, label


# The only patient-option fields whose stored form (tz-aware instant) differs from the
# widget's naive wall-clock display.
_DATETIME_FIELD_NAMES = (
    f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.DatetimeStart.NAME}",
    f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.DatetimeEnd.NAME}",
)


@callback(
    Output({"type": "patient-option", "name": ALL}, "value"),
    Output("patient-options-reload-status", "children"),
    Input("reload-patient-options-btn", "n_clicks"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    State("schema-registry", "data"),
    State("user-options-store", "data"),
    prevent_initial_call=True,
)
def reload_patient_options(
    n_clicks: int,
    current_values: list[Any],
    ids: list[dict[str, str]],
    schema_data: dict[str, str],
    user_options: dict[str, Any] | None,
) -> tuple[list[Any], Any]:
    """Reload patient options from the saved JSON in the current patient folder."""
    if not n_clicks:
        raise PreventUpdate

    values_by_id = {id_["name"]: val for id_, val in zip(ids, current_values, strict=False)}
    data_folder = values_by_id.get(
        f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.PathDataFolder.NAME}"
    )
    output_root = (
        values_by_id.get(f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.OutputRoot.NAME}")
        or None
    )

    if not data_folder:
        return (
            current_values,
            html.Span("No patient folder specified.", style={"color": "#e67e00"}),
        )

    try:
        saved = io.load_patient_options(data_folder, output_root)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to reload patient options: %s", exc)
        return (
            current_values,
            html.Span(str(exc), style={"color": "#dc3545", "wordBreak": "break-all"}),
        )
    if saved is None:
        looked_in = get_patient_options_path(data_folder, output_root).parent
        return (
            current_values,
            [
                html.Span("No saved patient options found in:", style={"color": "#e67e00"}),
                html.Span(str(looked_in), style={"color": "#e67e00", "wordBreak": "break-all"}),
            ],
        )

    schema_class_lookup = _rehydrate_schema_classes(schema_data or {})
    # Render the saved bound (may be tz-aware) as naive text in the current Settings
    # timezone; naive saved files pass through to_naive_display_ts unchanged.
    current_display_timezone = resolve_display_timezone(
        (user_options or {}).get(cst.UserOptions.DisplayTimezone.NAME)
    )

    new_values = []
    for id_, current_val in zip(ids, current_values, strict=False):
        field_id = id_["name"]
        parts = field_id.split(".")
        schema_class = schema_class_lookup.get(field_id)
        api_type = getattr(schema_class, "API_TYPE", None)
        raw_default = getattr(schema_class, "DEFAULT", None)

        if field_id in (
            f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.PathDataFolder.NAME}",
            f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.OutputRoot.NAME}",
        ):
            new_values.append(current_val)  # keep the paths used to locate the saved file
            continue
        if parts[0] == cst.PatientOptions.GLOBAL:
            raw = saved.get(parts[1], raw_default)
        elif parts[0] == "specific" and len(parts) == 3:  # noqa: PLR2004
            raw = saved.get(parts[1], {}).get(parts[2], raw_default)
        else:
            raw = raw_default

        if field_id in _DATETIME_FIELD_NAMES and raw:
            raw = to_naive_display_ts(raw, current_display_timezone, sep=" ")

        # Saved JSON holds Python values; re-encode into each widget's expected shape.
        new_values.append(ui_components.to_widget_value(api_type, raw))

    return new_values, ""


@callback(
    Output({"type": "patient-option", "name": ALL}, "value", allow_duplicate=True),
    Output("form-display-timezone-store", "data", allow_duplicate=True),
    Input({"type": "user-option", "name": "user_options.display_timezone"}, "value"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    State("form-display-timezone-store", "data"),
    prevent_initial_call=True,
)
def rerender_datetime_on_timezone_change(
    new_timezone: str | None,
    current_values: list[Any],
    ids: list[dict[str, str]],
    previous_timezone: str | None,
) -> tuple[list[Any], str]:
    """
    Rewrite datetime_start/end so editing display_timezone changes the label, not the instant.

    Otherwise the naive fields keep the same digits but get interpreted in a different
    timezone at Submit, silently shifting the stored window. No-op on empty or unparseable
    timezone input, so half-typed IANA names leave the fields untouched.
    """
    previous_timezone = resolve_display_timezone(previous_timezone)
    no_op = [no_update] * len(ids)

    if not new_timezone or new_timezone == previous_timezone:
        return no_op, previous_timezone
    try:
        ZoneInfo(new_timezone)
    except (ZoneInfoNotFoundError, KeyError):
        return no_op, previous_timezone

    new_values = []
    for id_, current_val in zip(ids, current_values, strict=False):
        if id_["name"] in _DATETIME_FIELD_NAMES and current_val:
            aware = to_aware_display_ts(current_val, previous_timezone)
            new_values.append(to_naive_display_ts(aware, new_timezone, sep=" "))
        else:
            new_values.append(no_update)
    return new_values, new_timezone


_PREVIEW_OK = {"color": "#28a745"}
_PREVIEW_WARN = {"color": "#e67e00"}
_PREVIEW_ERROR = {"color": "#dc3545"}

# A slow/dead share can make is_dir()/iterdir() block, so the scan runs in a worker
# thread and we give up after this long rather than hang the request.
_PREVIEW_SCAN_TIMEOUT_S = 2.0
# Module-level pool: a timed-out scan is abandoned, not joined (a stuck OS call can't be
# interrupted), so we never block on shutdown; max_workers bounds how many can pile up.
_PREVIEW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="folder-preview"
)


def _build_data_folder_preview(value: str | None) -> Any:
    """
    Reflect back what the typed patient-folder path actually contains.

    Names the device subfolders found (or why none were), so a wrong path surfaces here
    rather than at Process. Advisory only: filesystem errors degrade to a soft hint and a
    slow share is capped by a timeout, since real validation still runs on Process.
    """
    if not value or not str(value).strip():
        return ""

    path = ui_helper.format_path(value)
    try:
        return _PREVIEW_EXECUTOR.submit(_inspect_patient_folder, path).result(
            timeout=_PREVIEW_SCAN_TIMEOUT_S
        )
    except concurrent.futures.TimeoutError:
        logger.warning("Patient-folder preview timed out scanning %r", value)
        return html.Span(
            "⏳ Still reading this folder — it may be a slow or unresponsive drive. "
            "You can still Process once the path is correct.",
            style=_PREVIEW_WARN,
        )
    except Exception:
        logger.exception("Patient-folder preview failed")
        return html.Span(
            "⚠ Couldn't check this path",
            style=_PREVIEW_WARN,
        )


def _inspect_patient_folder(path: Path) -> Any:
    """Scan *path* and return the preview Span. Runs in a worker thread (see caller)."""
    scan = datasource.scan_patient_folder(path)

    if scan.status == "is_file":
        return html.Span(
            "⚠ That's a file, not a folder. Pick the patient folder (maybe its parent? "
            f"{path.parent.parent} ?)",
            style=_PREVIEW_ERROR,
        )
    # A suffix but no such directory: almost certainly a data file, not the folder.
    if scan.status == "missing" and path.suffix:
        return html.Span(
            f"⚠ '{path.name}' looks like a file, not a folder. Pick the patient folder, not a "
            "data file.",
            style=_PREVIEW_ERROR,
        )
    if scan.status == "missing":
        return html.Span("⚠ This folder doesn't exist.", style=_PREVIEW_WARN)
    if scan.status == "unreadable":
        return html.Span(
            "⚠ Couldn't read this folder (permission or path issue).", style=_PREVIEW_WARN
        )

    found = [ds.DESCRIPTION for ds in scan.found]
    empty = [ds.DESCRIPTION for ds in scan.empty]
    # Retired folders sit alongside recognized ones, so they must be called out on the success
    # path too — otherwise a patient with eit/ + philips_waves/ reads as a clean "✓ Found".
    retired_note = (
        f" ⚠ Ignoring {', '.join(scan.retired)}: removed datasource(s) — move these files "
        "into 'other/'."
        if scan.retired
        else ""
    )

    if found or empty:
        msg = ""
        if found:
            msg += f"✓ Found {len(found)} device folder(s): {', '.join(found)}."
        if empty:
            msg += f" ({len(empty)} recognized but empty: {', '.join(empty)})"
        msg += retired_note
        style = _PREVIEW_WARN if (scan.retired or not found) else _PREVIEW_OK
        return html.Span(msg.strip(), style=style)
    # If the path itself is named like a device folder, the user went one level too deep.
    if scan.self_datasource is not None:
        return html.Span(
            f"⚠ This looks like a '{scan.self_datasource.DESCRIPTION}' device folder, not a "
            f"patient folder. Pick the patient folder (maybe its parent? {path.parent} ?)",
            style=_PREVIEW_WARN,
        )
    if scan.other_subfolders:
        names = ", ".join(scan.other_subfolders)
        return html.Span(
            f"⚠ This doesn't look like a patient folder — its subfolders ({names}) don't match "
            f"any known device. A patient folder holds one subfolder per device.{retired_note}",
            style=_PREVIEW_WARN,
        )
    return html.Span(
        "⚠ This doesn't look like a patient folder — it contains no device subfolders. "
        "A patient folder holds one subfolder per device (monitor, ventilator, …).",
        style=_PREVIEW_WARN,
    )


@callback(
    Output("data-folder-preview", "children"),
    Input(
        {
            "type": "patient-option",
            "name": f"{cst.PatientOptions.GLOBAL}.{cst.PatientOptions.PathDataFolder.NAME}",
        },
        "value",
    ),
    prevent_initial_call=True,
)
def preview_data_folder(value: str | None) -> Any:
    """Update the live preview under the data-folder field as the user types/pastes."""
    return _build_data_folder_preview(value)


def _rehydrate_schema_classes(schema_data: dict) -> dict[str, type]:
    """
    Map component ids back to their schema classes.

    A dcc.Store can only hold JSON, so the registry stores class *names*; this resolves
    each one against PatientOptions or the datasource's own options class.

    A scope segment may be a standalone per-file token (``other::waves``); the file part only
    selects which options *block* the widget writes to, so the schema comes from ``other``.
    """
    schema_class_lookup = {}
    for field_id, class_name in schema_data.items():
        if field_id.startswith(cst.PatientOptions.GLOBAL):
            schema_class_lookup[field_id] = getattr(cst.PatientOptions, class_name)
        elif field_id.startswith("specific"):
            parts = field_id.split(".")
            scope = parts[1] if len(parts) > 1 else ""
            datasource_name = scope.split(cst.QUALIFIED_NAME_SEPARATOR, 1)[0]
            datasource_class = datasource.DataSource.get_subclass_by_name(datasource_name)
            schema_class_lookup[field_id] = getattr(
                datasource_class.OPTIONS.PatientOptionsDataSourceRelative, class_name
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
    Output("display-timezone-store", "data"),
    Output("process-progress-interval", "disabled", allow_duplicate=True),
    Output("process-progress", "children", allow_duplicate=True),
    Input("process-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    State("user-options-store", "data"),
    prevent_initial_call=True,
)
def process_visualization(
    n_clicks: int,  # noqa: ARG001
    database_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
    user_options: dict[str, Any] | None,
) -> tuple[Any, Any, Any, str | None, str | None, bool, str]:
    """Process visualization request with validated patient options."""
    interval_off, progress_clear = True, ""
    if not database_options:
        return (
            None,
            "Database options not loaded",
            None,
            None,
            no_update,
            interval_off,
            progress_clear,
        )

    schema_class_lookup = _rehydrate_schema_classes(schema_data)

    logger.debug("ids: %s", ids)
    logger.debug("values: %s", values)
    values_by_id = {widget_id["name"]: value for widget_id, value in zip(ids, values, strict=False)}

    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)
    logger.debug("errors: %s", errors)
    logger.debug("validated_dict: %s", validated_dict)

    if errors:
        return (
            None,
            html.Ul([html.Li(error) for error in errors]),
            None,
            None,
            no_update,
            interval_off,
            progress_clear,
        )

    data_folder = validated_dict["data_folder"]
    output_root = validated_dict.get(cst.PatientOptions.OutputRoot.NAME) or None
    patient_options_path = get_patient_options_path(data_folder, output_root)
    folder_visu_path = str(get_output_base(data_folder, output_root))

    # The form only holds naive wall-clock text; bake in the current Settings
    # display_timezone so the saved file stores an instant.
    display_timezone = resolve_display_timezone(
        (user_options or {}).get(cst.UserOptions.DisplayTimezone.NAME)
    )
    datetime_fields = (cst.PatientOptions.DatetimeStart.NAME, cst.PatientOptions.DatetimeEnd.NAME)
    for datetime_field in datetime_fields:
        raw_value = validated_dict.get(datetime_field)
        if raw_value:
            validated_dict[datetime_field] = to_aware_display_ts(raw_value, display_timezone)

    ui_helper.save_json(validated_dict, patient_options_path)
    database_options_path = get_database_options_path(data_folder, output_root)
    ui_helper.save_json(database_options, database_options_path)

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
            database_options_global=database_options,
            progress_callback=_on_progress,
            user_options=user_options,
        )
        # HTML export is opt-in (user_options.save_html_on_process, default off) — off avoids
        # the full-resolution serialization spike and writes no file.
        if (user_options or {}).get(cst.UserOptions.SaveHtmlOnProcess.NAME):
            PlotModel.to_html(
                model,
                validated_dict,
                self_contained=bool(
                    (user_options or {}).get(cst.UserOptions.SelfContainedHtml.NAME)
                ),
            )
        graphs = _build_graphs(model, display_timezone=display_timezone)
    except Exception as exc:
        logger.exception("Could not make the plot: ")
        return (
            None,
            None,
            html.Div(
                [
                    html.Span("Visualization failed: ", style={"fontWeight": "bold"}),
                    html.Span(str(exc)),
                    html.Div(
                        "See application logs for details.",
                        style={"color": "#999", "fontSize": "12px", "marginTop": "4px"},
                    ),
                ],
                style={"color": "red"},
            ),
            None,
            no_update,
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
        folder_visu_path,
        display_timezone,
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
# Adding a new ColumnInfo field: update ColumnInfo, _column_infos,
# ColumnInfo.DISPLAY_HEADERS and ColumnInfo.display_values (all in inspection.py), and this list.
_COL_CELL_STYLES: list[dict | None] = [
    {"fontFamily": "monospace", "fontSize": "13px"},  # Column
    None,  # Configured — style computed dynamically below
    {"textAlign": "right"},  # Raw pts
    {"textAlign": "right"},  # Kept pts
    {"textAlign": "right"},  # % retained
    {"textAlign": "left", "fontSize": "11px"},  # First
    {"textAlign": "left", "fontSize": "11px"},  # Last
]


def _col_cell(col: ColumnInfo) -> list[html.Td]:
    """
    Return <td> cells for one ColumnInfo row.

    Text content comes from ``ColumnInfo.display_values`` (shared with the CLI);
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
    for result in results:
        meta_parts = []
        if result.file_path:
            meta_parts.append(
                html.Div(f"File: {result.file_path}", style={"fontSize": "12px", "color": "#666"})
            )
        if result.raw_date_range:
            meta_parts.append(
                html.Div(
                    f"Date range in file: {result.raw_date_range[0]}  →  "
                    f"{result.raw_date_range[1]}",
                    style={"fontSize": "12px", "color": "#666"},
                )
            )
        if result.filtered_date_range:
            meta_parts.append(
                html.Div(
                    f"After time options:  "
                    f"{result.filtered_date_range[0]}  →  {result.filtered_date_range[1]}",
                    style={"fontSize": "12px", "color": "#666"},
                )
            )
        if result.error_message:
            meta_parts.append(
                html.Div(
                    f"Error: {result.error_message}",
                    style={"fontSize": "12px", "color": "#dc3545"},
                )
            )
        if result.columns_pruned:
            meta_parts.append(
                html.Div(
                    PRUNED_VIEW_NOTICE,
                    style={"fontSize": "12px", "color": "#856404", "fontStyle": "italic"},
                )
            )

        table_rows = [html.Tr(_col_cell(col)) for col in result.columns]

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
                        [result.datasource_name, _status_badge(result.status)],
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
    State("user-options-store", "data"),
    prevent_initial_call=True,
)
def inspect_data(
    n_clicks: int,  # noqa: ARG001
    database_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
    user_options: dict[str, Any] | None,
) -> tuple[dict, Any, list | None, None, bool, str]:
    """Run data inspection for all enabled datasources and display results in modal."""
    interval_off, progress_clear = True, ""

    if not database_options:
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Div("Database options not loaded.", style={"color": "red"}),
            None,
            None,
            interval_off,
            progress_clear,
        )

    schema_class_lookup = _rehydrate_schema_classes(schema_data)
    values_by_id = {widget_id["name"]: value for widget_id, value in zip(ids, values, strict=False)}
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)

    if errors:
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Ul([html.Li(error) for error in errors]),
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
            database_options_global=database_options,
            progress_callback=_on_progress,
            user_options=user_options,
            configured_columns_only=bool(
                (user_options or {}).get(cst.UserOptions.InspectConfiguredColumnsOnly.NAME)
            ),
        )
    except Exception as exc:
        logger.exception("Inspection failed: ")
        return (
            INSPECTION_MODAL_STYLE_SHOWN,
            html.Div(f"Inspection failed: {exc}", style={"color": "red"}),
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


def _build_slider_marks(
    time_min: float,
    duration: float,
    n_marks: int = 5,
    display_timezone: str | None = None,
) -> dict[float, str]:
    """
    Build evenly-spaced marks for a RangeSlider using relative-second keys.

    Keys are seconds offset from time_min (0 … duration).
    Labels are absolute clock times in the configured display timezone so the
    user sees human-readable timestamps, not raw numbers.
    """
    display_tz = ZoneInfo(display_timezone or cst.DISPLAY_TIMEZONE)
    fmt = "%m/%d %H:%M" if duration > _ONE_DAY_SECONDS else "%H:%M:%S"
    marks = {}
    for mark_index in range(n_marks + 1):
        offset = duration * mark_index / n_marks
        mark_datetime = datetime.fromtimestamp(time_min + offset, tz=UTC).astimezone(display_tz)
        marks[float(offset)] = mark_datetime.strftime(fmt)
    return marks


def format_time_range(
    time_start: float, time_end: float, display_timezone: str | None = None
) -> str:
    """Format a time range as a human-readable string in the configured display timezone."""
    display_tz = ZoneInfo(display_timezone or cst.DISPLAY_TIMEZONE)
    datetime_start = datetime.fromtimestamp(time_start, tz=UTC).astimezone(display_tz)
    datetime_end = datetime.fromtimestamp(time_end, tz=UTC).astimezone(display_tz)
    fmt = "%Y-%m-%d %H:%M:%S"
    return f"{datetime_start.strftime(fmt)}  —  {datetime_end.strftime(fmt)}"


def _build_graphs(model: Any, display_timezone: str | None = None) -> list[html.Div]:
    """
    Build list of dcc.Graph + dcc.Store components from model.

    Time-series figures are wrapped with FigureResampler for dynamic
    downsampling on zoom/pan. A companion dcc.Store holds the cache UUID
    so the resample_on_zoom callback can retrieve the server-side object.

    Loop figures get a time-range slider for interactive time filtering.
    """
    display_timezone = display_timezone or cst.DISPLAY_TIMEZONE
    graphs = []

    for plot_model in model:
        fig = plot_model.figure

        uid = None
        if plot_model.name == "time_series":
            uid = str(uuid4())
            fig = FigureResampler(fig)
            FIGURE_RESAMPLER_CACHE[uid] = fig
            # TEMPORARY WORKAROUND (dash >= 4.2.0 zoom regression, dash PR #3785):
            # applying a data-only Patch to a dcc.Graph now re-syncs layout and discards
            # the user's live zoom, so resampling on zoom snaps the axes back. A constant
            # uirevision tells plotly.js to preserve zoom/pan across the data update. Scoped
            # to `uid` so a fresh Process (new figure) still resets the view. Remove once
            # dash or plotly-resampler restores layout-preserving partial updates.
            fig.update_layout(uirevision=uid)

        # Plotly's autosize=True sizes the figure to its container, so an unsized container
        # collapses to a default that can hide the plot (time-series with few subplots
        # especially) — set the CSS height explicitly to match the figure's intended height.
        graph_height = int(plot_model.computed_height) if plot_model.computed_height else None
        graph_style = {"marginBottom": "40px"}
        if graph_height:
            graph_style["height"] = f"{graph_height}px"

        # --- Build annotation metadata stores from the PlotModel ---
        # These are read by annotation_callbacks to know subplot names and axis refs.
        # Must be built from plot_model.figure (original go.Figure) before FigureResampler wraps it.
        n_cols_layout = plot_model.n_cols

        signal_meta_lookup: dict[str, dict] = {
            signal_obj.name: {
                "raw_name": signal_obj.raw_name,
                "datasource_name": signal_obj.metadata.datasource_name or "",
            }
            for group in plot_model.groups
            for signal_obj in group.signals
        }
        trace_map: dict[str, dict] = {}
        for trace_idx, trace in enumerate(plot_model.figure.data):
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
        # through plot_model.figure.data and assign each trace's yaxis to its group's subplot.
        yaxis_to_subplot: dict[str, dict] = {}
        trace_idx = 0
        for group_idx, group in enumerate(plot_model.groups):
            plotly_row = group_idx // n_cols_layout + 1
            plotly_col = group_idx % n_cols_layout + 1

            # The subplot's primary y-axis is the one carried by its first trace.
            primary_yaxis = "y"
            if trace_idx < len(plot_model.figure.data):
                primary_yaxis = getattr(plot_model.figure.data[trace_idx], "yaxis", None) or "y"

            subplot_rows.append(
                {
                    "row": plotly_row,
                    "col": plotly_col,
                    "name": group.name,
                    "yaxis": primary_yaxis,
                }
            )

            n_traces_in_group = len(group.signals)
            for _ in range(n_traces_in_group):
                if trace_idx < len(plot_model.figure.data):
                    trace = plot_model.figure.data[trace_idx]
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
        if plot_model.figure.layout.annotations:
            subplot_title_annotations = [
                ann.to_plotly_json() for ann in plot_model.figure.layout.annotations
            ]

        graph_subplots_data = {
            "rows": subplot_rows,
            "yaxis_to_subplot": yaxis_to_subplot,
            "subplot_annotations": subplot_title_annotations,
            "plot_type": plot_model.plot_type,
            "n_cols": n_cols_layout,
        }

        children = [
            dcc.Graph(
                id={"type": "graph", "name": plot_model.name},
                figure=fig,
                config={"displayModeBar": True},
                style=graph_style,
            ),
            dcc.Store(id={"type": "resampler-store", "name": plot_model.name}, data=uid),
            dcc.Store(
                id={"type": "graph-subplots", "name": plot_model.name}, data=graph_subplots_data
            ),
            dcc.Store(id={"type": "graph-trace-map", "name": plot_model.name}, data=trace_map),
        ]

        # --- Loop time-range slider ---
        if plot_model.plot_type == cst.PlotType.LOOP:
            loop_uid = str(uuid4())

            # Traces with no data get a null placeholder rather than being dropped, so cache
            # indices stay aligned with the Plotly figure's trace indices.
            trace_data = []
            time_min_global = np.inf
            time_max_global = -np.inf
            for group in plot_model.groups:
                for signal_obj in group.signals:
                    time_array = signal_obj.data.loop_time_axis
                    if time_array is None or signal_obj.data.x is None or signal_obj.data.y is None:
                        trace_data.append({"x": None, "y": None, "time_axis": None})
                        continue
                    if len(time_array) > 0:
                        time_min_global = min(time_min_global, time_array[0])
                        time_max_global = max(time_max_global, time_array[-1])
                    trace_data.append(
                        {
                            "x": signal_obj.data.x,
                            "y": signal_obj.data.y,
                            "time_axis": time_array,
                        }
                    )

            # Store t_min alongside traces so callbacks can convert relative
            # offsets back to absolute epoch seconds for display/masking.
            # Convert to native Python float for orjson serialization safety.
            time_min_float = float(time_min_global) if np.isfinite(time_min_global) else 0.0
            LOOP_DATA_CACHE[loop_uid] = {
                "traces": trace_data,
                "t_min": time_min_float,
                "display_timezone": display_timezone,
            }
            children.append(
                dcc.Store(id={"type": "loop-store", "name": plot_model.name}, data=loop_uid)
            )

            if np.isfinite(time_min_global) and time_min_global < time_max_global:
                duration = float(time_max_global) - time_min_float
                step = 1
                marks = _build_slider_marks(
                    time_min_float, duration, display_timezone=display_timezone
                )

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
                                id={"type": "loop-time-slider", "name": plot_model.name},
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
                                format_time_range(
                                    time_min_float,
                                    time_min_float + duration,
                                    display_timezone=display_timezone,
                                ),
                                id={"type": "loop-time-display", "name": plot_model.name},
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
