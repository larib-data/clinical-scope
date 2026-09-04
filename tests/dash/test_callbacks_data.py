"""Tests for Dash callback helper functions — direct invocation, no browser."""

import json

import pytest
from dash import Patch, no_update
from dash.exceptions import PreventUpdate

import clinical_scope.constants as cst
from clinical_scope.dash_api.callbacks.data_callbacks import (
    _build_inspection_content,
    _build_slider_marks,
    _inspect_patient_folder,
    _parse_database_options_file,
    _rehydrate_schema_classes,
    _status_badge,
    FIGURE_RESAMPLER_CACHE,
    resample_on_zoom,
    build_patient_options_ui,
    format_time_range,
    process_visualization,
    reload_patient_options,
    rerender_datetime_on_timezone_change,
    update_datetime_tz_label,
)
from clinical_scope.dash_api.io import load_patient_options
from clinical_scope.datasource.inspection import ColumnInfo, DataSourceInspection
from clinical_scope.io.paths import get_patient_options_path
from tests.dash.helpers import patch_ops

# ---------------------------------------------------------------------------
# _parse_database_options_file
# ---------------------------------------------------------------------------


class TestParseDbOptionsFile:
    def test_parse_json(self, example_database_options):
        content = json.dumps(example_database_options).encode("utf-8")
        result, issues = _parse_database_options_file(content, "test.json")
        assert isinstance(result, dict)
        assert "other::waves" in result
        assert isinstance(issues, list)

    def test_parse_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _parse_database_options_file(b"data", "test.txt")

    def test_parse_xlsx(self, project_root):
        xlsx_path = project_root / "tests/data/option_files/example_database_options.xlsx"
        if not xlsx_path.exists():
            pytest.skip("No example xlsx file")
        content = xlsx_path.read_bytes()
        result, issues = _parse_database_options_file(content, "test.xlsx")
        assert isinstance(result, dict)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# _status_badge
# ---------------------------------------------------------------------------


class TestStatusBadge:
    def test_ok_badge(self):
        badge = _status_badge("ok")
        assert badge.children == "ok"

    def test_error_badge(self):
        badge = _status_badge("load_error")
        assert badge.children == "load_error"

    def test_unknown_status(self):
        badge = _status_badge("unknown")
        assert badge.children == "unknown"


# ---------------------------------------------------------------------------
# _build_inspection_content
# ---------------------------------------------------------------------------


class TestBuildInspectionContent:
    def test_ok_result(self):
        results = [
            DataSourceInspection(
                datasource_name="servo_u",
                status="ok",
                file_path="/data/waves.parquet",
                raw_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
                filtered_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
                columns=[ColumnInfo("ART", True, 1000, 800)],
            )
        ]
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0

    def test_error_result(self):
        results = [
            DataSourceInspection(
                datasource_name="broken",
                status="load_error",
                error_message="File corrupt",
            )
        ]
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0

    def test_empty_results(self):
        content = _build_inspection_content([])
        assert isinstance(content, list)


# ---------------------------------------------------------------------------
# _build_slider_marks
# ---------------------------------------------------------------------------


class TestBuildSliderMarks:
    def test_default_marks(self):
        marks = _build_slider_marks(1000000.0, 3600.0)
        assert isinstance(marks, dict)
        assert len(marks) == 6  # n_marks=5 → 6 entries (0 to 5)
        assert 0.0 in marks
        assert 3600.0 in marks

    def test_custom_n_marks(self):
        marks = _build_slider_marks(1000000.0, 3600.0, n_marks=3)
        assert len(marks) == 4

    def test_long_duration_format(self):
        """Durations > 1 day should use date+time format."""
        marks = _build_slider_marks(1000000.0, 100000.0)
        # Should contain "/" (month/day format)
        for label in marks.values():
            assert "/" in label


# ---------------------------------------------------------------------------
# format_time_range
# ---------------------------------------------------------------------------


class TestFormatTimeRange:
    def test_returns_string(self):
        result = format_time_range(1000000.0, 1003600.0)
        assert isinstance(result, str)
        assert "\u2014" in result  # — separator

    def test_contains_timestamps(self):
        result = format_time_range(1000000.0, 1003600.0)
        assert ":" in result  # time format HH:MM:SS


# ---------------------------------------------------------------------------
# Issue #68: datetime_start/datetime_end stored as tz-aware instants
# ---------------------------------------------------------------------------


def _global_ids(*names: str) -> list[dict[str, str]]:
    return [{"type": "patient-option", "name": f"global.{name}"} for name in names]


_DATETIME_SCHEMA_DATA = {
    "global.data_folder": "PathDataFolder",
    "global.output_root": "OutputRoot",
    "global.datetime_start": "DatetimeStart",
    "global.datetime_end": "DatetimeEnd",
}


class TestReloadPatientOptionsTimezoneRoundTrip:
    def test_aware_saved_bound_renders_in_current_settings_timezone(self, tmp_path):
        """The preview always uses the live Settings tz, not whatever the file was saved in (#69)."""
        data_folder = tmp_path / "patient"
        data_folder.mkdir()
        patient_options_path = get_patient_options_path(str(data_folder))
        patient_options_path.parent.mkdir(parents=True, exist_ok=True)
        patient_options_path.write_text(
            json.dumps(
                {
                    "data_folder": str(data_folder),
                    "datetime_start": "2004-09-15T08:20:00+02:00",
                    "datetime_end": "2004-09-15T10:20:00+02:00",
                }
            )
        )

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        current_values = [str(data_folder), "", "", ""]

        new_values, _status = reload_patient_options(
            1,
            current_values,
            ids,
            _DATETIME_SCHEMA_DATA,
            {"display_timezone": "America/New_York"},
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 02:20:00"
        assert new_values[names.index("global.datetime_end")] == "2004-09-15 04:20:00"

    def test_legacy_naive_saved_file_is_unaffected(self, tmp_path):
        """Strictly additive: an older, still-naive saved file round-trips unchanged."""
        data_folder = tmp_path / "patient"
        data_folder.mkdir()
        patient_options_path = get_patient_options_path(str(data_folder))
        patient_options_path.parent.mkdir(parents=True, exist_ok=True)
        patient_options_path.write_text(
            json.dumps(
                {
                    "data_folder": str(data_folder),
                    "display_timezone": "UTC",
                    "datetime_start": "2004-09-15 06:20:00",
                }
            )
        )

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        current_values = [str(data_folder), "", "", ""]

        new_values, _status = reload_patient_options(
            1, current_values, ids, _DATETIME_SCHEMA_DATA, {"display_timezone": "Europe/Paris"}
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 06:20:00"


class TestProcessVisualizationSubmitTimezone:
    def test_submit_writes_aware_datetime_bounds(self, tmp_path):
        data_folder = tmp_path / "patient"
        data_folder.mkdir()

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        values = [
            str(data_folder),
            "",
            "2004-09-15 08:20:00",
            "2004-09-15 10:20:00",
        ]

        # database_options only needs to be truthy; wrapper.main can fail afterward (no real
        # data under data_folder) since this test only cares what got saved.
        process_visualization(
            1,
            {"servo_u": {}},
            _DATETIME_SCHEMA_DATA,
            values,
            ids,
            {"display_timezone": "Europe/Paris"},
        )

        saved = load_patient_options(str(data_folder))
        assert saved["datetime_start"] == "2004-09-15T08:20:00+02:00"
        assert saved["datetime_end"] == "2004-09-15T10:20:00+02:00"


class TestRerenderDatetimeOnTimezoneChange:
    def test_preserves_instant_across_timezones(self):
        ids = _global_ids("datetime_start", "datetime_end")
        current_values = ["2004-09-15 08:20:00", "2004-09-15 10:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "America/New_York", current_values, ids, "Europe/Paris"
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 02:20:00"
        assert new_values[names.index("global.datetime_end")] == "2004-09-15 04:20:00"
        assert new_timezone == "America/New_York"

    def test_unchanged_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "Europe/Paris", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"

    def test_mid_typing_invalid_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "America/New_Y", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"

    def test_empty_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"


class TestUpdateDatetimeTzLabel:
    def test_shows_given_timezone(self):
        assert update_datetime_tz_label("Europe/Paris") == (
            "interpreted in Europe/Paris",
            "interpreted in Europe/Paris",
        )

    def test_falls_back_to_default_when_empty(self):
        start_label, end_label = update_datetime_tz_label(None)
        assert "interpreted in" in start_label
        assert start_label == end_label

    def test_falls_back_to_default_when_invalid(self):
        # Never echo an unresolved/invalid name (e.g. mid-typing) as if it were in effect.
        start_label, end_label = update_datetime_tz_label("Not/AZone")
        assert "Not/AZone" not in start_label
        assert f"interpreted in {cst.DISPLAY_TIMEZONE}" == start_label == end_label


# ---------------------------------------------------------------------------
# _inspect_patient_folder — now sourced from datasource.scan_patient_folder() (#53)
# ---------------------------------------------------------------------------


class TestInspectPatientFolder:
    """
    Uses an explicit 'patient' folder name (not bare tmp_path) throughout, since
    tmp_path's auto-generated name is derived from the test name and could otherwise
    accidentally collide with a datasource FOLDER_KEYWORDS match (e.g. "other").
    """

    def test_missing_folder(self, tmp_path):
        span = _inspect_patient_folder(tmp_path / "patient" / "does_not_exist")
        assert span.children == "⚠ This folder doesn't exist."

    def test_path_is_a_file(self, tmp_path):
        file_path = tmp_path / "patient.csv"
        file_path.touch()
        span = _inspect_patient_folder(file_path)
        assert "not a folder" in span.children

    def test_found_device_folder_with_content(self, tmp_path):
        patient_folder = tmp_path / "patient"
        eit_folder = patient_folder / "eit"
        eit_folder.mkdir(parents=True)
        (eit_folder / "recording.asc").touch()

        span = _inspect_patient_folder(patient_folder)

        assert span.children == "✓ Found 1 device folder(s): EIT - PulmoVista."

    def test_recognized_but_empty_device_folder(self, tmp_path):
        patient_folder = tmp_path / "patient"
        (patient_folder / "eit").mkdir(parents=True)

        span = _inspect_patient_folder(patient_folder)

        assert "1 recognized but empty" in span.children

    def test_path_itself_looks_like_a_device_folder(self, tmp_path):
        device_folder = tmp_path / "patient" / "eit"
        device_folder.mkdir(parents=True)
        (device_folder / "recording.asc").touch()

        span = _inspect_patient_folder(device_folder)

        assert "looks like a" in span.children
        assert "EIT - PulmoVista" in span.children

    def test_unrecognized_subfolder(self, tmp_path):
        patient_folder = tmp_path / "patient"
        (patient_folder / "ventilator_data").mkdir(parents=True)

        span = _inspect_patient_folder(patient_folder)

        assert "ventilator_data" in span.children

    def test_empty_folder_no_subfolders(self, tmp_path):
        patient_folder = tmp_path / "patient"
        patient_folder.mkdir()

        span = _inspect_patient_folder(patient_folder)

        assert "contains no device subfolders" in span.children


# ---------------------------------------------------------------------------
# build_patient_options_ui — per-file 'other' cards
# ---------------------------------------------------------------------------


class TestOtherPerFileCards:
    """Files declared with other::<stem> get their own options card, as datasource peers."""

    def _scopes(self, database_options):
        """Return the set of 'specific.<scope>' prefixes the form produced widgets for."""
        _, schema_data = build_patient_options_ui(database_options)
        return {
            field_id.split(".")[1] for field_id in schema_data if field_id.startswith("specific.")
        }

    def test_itemized_config_has_no_generic_card(self):
        scopes = self._scopes({"other::waves": {}, "other::numerics": {}})
        assert scopes == {"other::waves", "other::numerics"}

    def test_generic_content_keeps_the_fallback_card(self):
        scopes = self._scopes({"other": {"field_display": ["col"]}, "other::waves": {}})
        assert scopes == {"other", "other::waves"}

    def test_default_visualization_keeps_the_generic_card(self):
        """generate_default_database_options() emits an empty 'other' — the card must survive."""
        scopes = self._scopes({"other": {}})
        assert scopes == {"other"}

    def test_normalized_config_is_read_too(self):
        """The store holds raw config, but the 'files' shape must not silently render nothing."""
        scopes = self._scopes({"other": {"files": {"waves": {}}}})
        assert scopes == {"other::waves"}

    def test_no_other_config_no_other_card(self):
        scopes = self._scopes({"servo_u": {}})
        assert scopes == {"servo_u"}

    def test_per_file_widgets_carry_both_fields(self):
        _, schema_data = build_patient_options_ui({"other::waves": {}})
        assert schema_data["specific.other::waves.time_shift"] == "TimeShift"
        assert schema_data["specific.other::waves.group_by_file"] == "GroupByFile"


class TestRehydrateSchemaClasses:
    """Widget ids carrying an other::<stem> scope resolve to the 'other' schema classes."""

    def test_per_file_id_resolves_to_other_schema(self):
        lookup = _rehydrate_schema_classes({"specific.other::waves.time_shift": "TimeShift"})
        schema = lookup["specific.other::waves.time_shift"]
        assert schema.NAME == "time_shift"

    def test_plain_datasource_id_still_resolves(self):
        lookup = _rehydrate_schema_classes({"specific.servo_u.time_shift": "TimeShift"})
        assert lookup["specific.servo_u.time_shift"].NAME == "time_shift"


# ---------------------------------------------------------------------------
# resample_on_zoom — reset-axes healing
# ---------------------------------------------------------------------------


class TestResampleOnZoomReset:
    """A graph with no resampler (uid None) must still be re-homed on a reset."""

    def test_empty_relayout_does_nothing(self):
        with pytest.raises(PreventUpdate):
            resample_on_zoom({}, None, {"axes": {"xaxis": None}})

    def test_zoom_without_a_resampler_does_nothing(self):
        with pytest.raises(PreventUpdate):
            resample_on_zoom(
                {"xaxis.range[0]": 1.0, "xaxis.range[1]": 2.0},
                None,
                {"axes": {"xaxis": None}},
            )

    def test_stale_reset_is_pulled_back_to_autorange(self):
        patch = resample_on_zoom(
            {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False},
            None,
            {"axes": {"xaxis": None}},
        )

        ops = patch_ops(patch)
        assert ops["layout.xaxis.autorange"] is True
        assert ops["layout.xaxis.range"] is None

    def test_double_click_reset_is_pulled_back_too(self):
        patch = resample_on_zoom({"xaxis.range": [100.0, 200.0]}, None, {"axes": {"xaxis": None}})

        assert patch_ops(patch)["layout.xaxis.autorange"] is True

    def test_configured_range_is_the_home(self):
        patch = resample_on_zoom(
            {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False},
            None,
            {"axes": {"xaxis": [0.0, 10.0]}},
        )

        ops = patch_ops(patch)
        assert ops["layout.xaxis.range"] == [0.0, 10.0]
        assert ops["layout.xaxis.autorange"] is False

    def test_missing_home_store_still_resets(self):
        patch = resample_on_zoom({"xaxis.range": [1.0, 2.0]}, None, None)

        assert patch_ops(patch)["layout.xaxis.autorange"] is True

    def test_unknown_resampler_uid_still_resets(self):
        patch = resample_on_zoom(
            {"xaxis.range": [1.0, 2.0]},
            "no-such-uid",
            {"axes": {"xaxis": None}},
        )

        assert patch_ops(patch)["layout.xaxis.autorange"] is True

    def test_healthy_reset_is_passed_through_untouched(self):
        # Nothing is off home, so the callback must stay silent as it did before the fix.
        with pytest.raises(PreventUpdate):
            resample_on_zoom(
                {"xaxis.autorange": True, "xaxis.showspikes": False},
                None,
                {"axes": {"xaxis": None}},
            )

    def test_spike_lines_toggle_is_passed_through_untouched(self):
        with pytest.raises(PreventUpdate):
            resample_on_zoom(
                {"xaxis.showspikes": True, "yaxis.showspikes": True},
                None,
                {"axes": {"xaxis": [0.0, 10.0]}},
            )

    def test_matched_axes_get_no_layout_ops(self):
        relayout = {"xaxis.range": [1.0, 2.0], "xaxis2.range": [1.0, 2.0]}

        patch = resample_on_zoom(
            relayout,
            None,
            {"axes": {"xaxis": None, "xaxis2": None}, "matched": {"xaxis2": "xaxis"}},
        )

        ops = patch_ops(patch)
        assert not [key for key in ops if key.startswith("layout.xaxis2")]
        assert ops["layout.xaxis.autorange"] is True


class _SpyResampler:
    """Stands in for a FigureResampler, recording the relayout it is asked to aggregate."""

    def __init__(self, patch=None):
        self.seen: dict | None = None
        self._patch = patch

    def construct_update_data_patch(self, relayout):
        self.seen = relayout
        return no_update if self._patch is None else self._patch


class TestResampleOnZoomFeedsTheResampler:
    """The healed relayout, not plotly's stale one, is what gets re-aggregated."""

    @pytest.fixture
    def spy(self):
        uid = "spy-uid"
        spy = _SpyResampler()
        FIGURE_RESAMPLER_CACHE[uid] = spy
        yield uid, spy
        del FIGURE_RESAMPLER_CACHE[uid]

    def test_a_stale_reset_is_aggregated_on_the_home_window(self, spy):
        uid, resampler = spy

        resample_on_zoom(
            {"xaxis.range": [100.0, 200.0], "xaxis.showspikes": False},
            uid,
            {"axes": {"xaxis": [0.0, 10.0]}},
        )

        assert resampler.seen["xaxis.range[0]"] == 0.0
        assert resampler.seen["xaxis.range[1]"] == 10.0
        assert "xaxis.range" not in resampler.seen

    def test_a_matched_axis_is_aggregated_too(self, spy):
        uid, resampler = spy

        resample_on_zoom(
            {"xaxis.range": [100.0, 200.0], "xaxis2.range": [100.0, 200.0]},
            uid,
            {"axes": {"xaxis": [0.0, 10.0], "xaxis2": None}, "matched": {"xaxis2": "xaxis"}},
        )

        assert resampler.seen["xaxis2.range[0]"] == 0.0
        assert resampler.seen["xaxis2.range[1]"] == 10.0

    def test_an_ordinary_zoom_reaches_the_resampler_unaltered(self, spy):
        uid, resampler = spy
        relayout = {"xaxis.range[0]": 1.0, "xaxis.range[1]": 2.0}

        with pytest.raises(PreventUpdate):
            resample_on_zoom(relayout, uid, {"axes": {"xaxis": None}})

        assert resampler.seen == relayout

    def test_the_layout_ops_compose_onto_the_resampler_data_patch(self, spy):
        uid, resampler = spy
        data_patch = Patch()
        data_patch["data"][0]["x"] = [1, 2, 3]
        resampler._patch = data_patch

        ops = patch_ops(
            resample_on_zoom({"xaxis.range": [100.0, 200.0]}, uid, {"axes": {"xaxis": None}})
        )

        assert ops["data.0.x"] == [1, 2, 3]
        assert ops["layout.xaxis.autorange"] is True
