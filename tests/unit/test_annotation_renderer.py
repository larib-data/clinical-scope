"""
Unit tests for annotations/renderer.py: where a mark is drawn, and at what clock time.

The renderer turns an Annotation into the Plotly ``layout.shapes`` and ``layout.annotations``
dicts a figure is drawn from.  A wrong yref puts a clinician's mark on the wrong signal and a
wrong timezone conversion puts it at the wrong moment, and both look entirely plausible on
screen until someone re-reads the study.

What these pin is where a mark lands, how many dicts it takes, and that normalizing one
leaves the stored annotation alone.  Colour, opacity, font and arrow shape are deliberately
left unasserted, so restyling an annotation cannot redden this file.
"""

from __future__ import annotations

import pytest

from clinical_scope.dash_api.annotations.model import Annotation, AnnotationType
from clinical_scope.dash_api.annotations.renderer import (
    _resolve_subplot_yaxis,
    annotation_to_plotly_annotation,
    annotation_to_shapes,
    build_figure_overlays,
    make_preview_shape,
    normalize_annotation_for_display,
)

# Subplot rows as the graph-subplots store writes them, plus one that carries no yaxis.
SUBPLOT_ROWS = [
    {"row": 1, "col": 1, "name": "Airway pressure", "yaxis": "y3"},
    {"row": 2, "col": 1, "name": "Flow", "yaxis": "y5"},
    {"row": 3, "col": 1, "name": "Unaxed"},
]

# The layout.annotations make_subplots puts in a figure, which the renderer keeps ahead of ours.
SUBPLOT_TITLES = [{"text": "Airway pressure", "yref": "paper"}]

# Annotations reaching the shape builders are already naive display-TZ wall clock; only the
# normalization tests below start from the tz-aware form the store holds.
NAIVE_INSTANT = "2024-01-01T12:00:00"
NAIVE_LATER = "2024-01-01T14:30:00"
STORED_INSTANT = "2024-01-01T12:00:00+00:00"
STORED_LATER = "2024-01-01T14:30:00+00:00"

POINT_Y = 5.0
LOOP_X = 3.14159

# A point draws a dot and, unless its label is hidden, an arrow label.
POINT_ANNOTATION_COUNT = 2

# Labels are pinned to the top of what they are drawn against; both refs run 0 to 1.
TOP_HALF = 0.5

DEFAULT_DATA = {
    AnnotationType.TIME_EVENT: {"x": NAIVE_INSTANT},
    AnnotationType.TIME_WINDOW: {"x0": NAIVE_INSTANT, "x1": NAIVE_LATER},
    AnnotationType.POINT: {"x": NAIVE_INSTANT, "y": POINT_Y, "xaxis": "x2", "yaxis": "y2"},
}


# ==================================================================================================
# Helpers
# ==================================================================================================


def make_annotation(
    annotation_type: AnnotationType = AnnotationType.TIME_EVENT,
    *,
    data: dict | None = None,
    subplot_name: str | None = None,
    label: str = "Intubation",
    plot_name: str = "time_series",
) -> Annotation:
    """Build one annotation, defaulting its payload to the data its type stores."""
    return Annotation(
        id="a1",
        type=annotation_type,
        plot_name=plot_name,
        data=dict(DEFAULT_DATA[annotation_type]) if data is None else data,
        label=label,
        subplot_name=subplot_name,
    )


# ==================================================================================================
# Which subplot a mark lands on
# ==================================================================================================


class TestSubplotResolution:
    """`subplot_name` is resolved by name, so a re-ordered figure cannot move an annotation."""

    def test_a_global_annotation_names_no_axis(self):
        assert _resolve_subplot_yaxis(make_annotation(subplot_name=None), SUBPLOT_ROWS) is None

    def test_a_named_subplot_resolves_to_its_primary_yaxis(self):
        annotation = make_annotation(subplot_name="Airway pressure")
        assert _resolve_subplot_yaxis(annotation, SUBPLOT_ROWS) == "y3"

    def test_resolution_is_by_name_not_by_position(self):
        annotation = make_annotation(subplot_name="Flow")
        assert _resolve_subplot_yaxis(annotation, SUBPLOT_ROWS) == "y5"

    def test_a_subplot_that_no_longer_exists_returns_the_removed_sentinel(self):
        annotation = make_annotation(subplot_name="Ghost")
        assert _resolve_subplot_yaxis(annotation, SUBPLOT_ROWS) == "-1"

    def test_a_row_carrying_no_yaxis_names_no_axis(self):
        """A row with no yaxis is not an error: the mark spans the figure instead of vanishing."""
        annotation = make_annotation(subplot_name="Unaxed")
        assert _resolve_subplot_yaxis(annotation, SUBPLOT_ROWS) is None


# ==================================================================================================
# Time events: one vertical line
# ==================================================================================================


class TestTimeEventGeometry:
    def test_it_produces_exactly_one_line(self):
        shapes = annotation_to_shapes(make_annotation(), None)
        assert len(shapes) == 1
        assert shapes[0]["type"] == "line"

    def test_both_ends_sit_on_the_stored_instant(self):
        shape = annotation_to_shapes(make_annotation(data={"x": "2024-03-05T08:15:00"}), None)[0]
        assert shape["x0"] == "2024-03-05T08:15:00"
        assert shape["x1"] == "2024-03-05T08:15:00"

    def test_it_spans_the_full_height_of_what_it_is_drawn_against(self):
        shape = annotation_to_shapes(make_annotation(), "y3")[0]
        assert shape["y0"] == 0
        assert shape["y1"] == 1

    def test_a_global_event_is_drawn_against_the_whole_figure(self):
        assert annotation_to_shapes(make_annotation(), None)[0]["yref"] == "paper"

    def test_a_scoped_event_is_drawn_against_its_subplot_domain(self):
        assert annotation_to_shapes(make_annotation(), "y3")[0]["yref"] == "y3 domain"

    def test_it_is_drawn_against_the_axis_the_click_landed_on(self):
        """Linked time axes keep distinct refs, so a mark on the second row stores ``x2``."""
        annotation = make_annotation(data={"x": NAIVE_INSTANT, "xaxis": "x2"})
        assert annotation_to_shapes(annotation, "y3")[0]["xref"] == "x2"

    def test_an_event_with_no_stored_axis_falls_back_to_the_first(self):
        """Every click records an axis; a hand-written annotations.json need not."""
        assert annotation_to_shapes(make_annotation(), "y3")[0]["xref"] == "x"


# ==================================================================================================
# Time windows: one rectangle
# ==================================================================================================


class TestTimeWindowGeometry:
    def test_it_produces_exactly_one_rectangle(self):
        shapes = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), None)
        assert len(shapes) == 1
        assert shapes[0]["type"] == "rect"

    def test_its_edges_are_the_stored_bounds_in_order(self):
        shape = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), None)[0]
        assert shape["x0"] == "2024-01-01T12:00:00"
        assert shape["x1"] == "2024-01-01T14:30:00"

    def test_it_spans_the_full_height_of_what_it_is_drawn_against(self):
        shape = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), "y3")[0]
        assert shape["y0"] == 0
        assert shape["y1"] == 1

    def test_a_global_window_is_drawn_against_the_whole_figure(self):
        shape = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), None)[0]
        assert shape["yref"] == "paper"

    def test_a_scoped_window_is_drawn_against_its_subplot_domain(self):
        shape = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), "y5")[0]
        assert shape["yref"] == "y5 domain"

    def test_it_is_drawn_against_the_axis_the_click_landed_on(self):
        data = {"x0": NAIVE_INSTANT, "x1": NAIVE_LATER, "xaxis": "x2"}
        window = make_annotation(AnnotationType.TIME_WINDOW, data=data)
        assert annotation_to_shapes(window, None)[0]["xref"] == "x2"

    def test_a_window_with_no_stored_axis_falls_back_to_the_first(self):
        shape = annotation_to_shapes(make_annotation(AnnotationType.TIME_WINDOW), None)[0]
        assert shape["xref"] == "x"


# ==================================================================================================
# Points: no shape, Plotly annotations instead
# ==================================================================================================


class TestPointGeometry:
    """A point is anchored to one data coordinate, so it is drawn as a Plotly annotation."""

    def test_a_point_produces_no_shape(self):
        assert annotation_to_shapes(make_annotation(AnnotationType.POINT), "y2") == []

    def test_a_point_is_rendered_at_its_data_coordinate(self):
        label = annotation_to_plotly_annotation(make_annotation(AnnotationType.POINT), "y2")
        assert label is not None
        assert label["x"] == "2024-01-01T12:00:00"
        assert label["y"] == POINT_Y

    def test_it_is_anchored_to_the_axes_the_click_landed_on(self):
        """The stored axes win over the resolved subplot: the arrow must follow its own scale."""
        label = annotation_to_plotly_annotation(make_annotation(AnnotationType.POINT), "y9")
        assert label["xref"] == "x2"
        assert label["yref"] == "y2"

    def test_axes_fall_back_to_the_primary_pair(self):
        data = {"x": NAIVE_INSTANT, "y": POINT_Y}
        label = annotation_to_plotly_annotation(
            make_annotation(AnnotationType.POINT, data=data), None
        )
        assert label["xref"] == "x"
        assert label["yref"] == "y"

    def test_a_shown_point_is_a_dot_and_a_label_at_the_same_coordinate(self):
        shapes, annotations = build_figure_overlays(
            [make_annotation(AnnotationType.POINT, subplot_name="Airway pressure")],
            "time_series",
            [],
            SUBPLOT_ROWS,
        )
        assert shapes == []
        assert len(annotations) == POINT_ANNOTATION_COUNT
        assert [entry["x"] for entry in annotations] == [NAIVE_INSTANT] * POINT_ANNOTATION_COUNT
        assert [entry["y"] for entry in annotations] == [POINT_Y] * POINT_ANNOTATION_COUNT

    def test_a_point_as_the_app_creates_it_is_drawn_as_the_dot_alone(self):
        """`Annotation.create` hides a point's label, so the dot is all a clinician sees."""
        point = Annotation.create(
            annotation_type=AnnotationType.POINT,
            plot_name="time_series",
            data=dict(DEFAULT_DATA[AnnotationType.POINT]),
            subplot_name="Airway pressure",
        )
        shapes, annotations = build_figure_overlays([point], "time_series", [], SUBPLOT_ROWS)
        assert shapes == []
        assert len(annotations) == 1
        dot = annotations[0]
        assert dot["x"] == NAIVE_INSTANT
        assert dot["y"] == POINT_Y
        assert dot["xref"] == "x2"
        assert dot["yref"] == "y2"


# ==================================================================================================
# Labels
# ==================================================================================================


class TestLabelPlacement:
    """A label is anchored to the moment it names; an empty one is simply not drawn."""

    def test_an_event_label_sits_on_the_event(self):
        label = annotation_to_plotly_annotation(make_annotation(), "y3")
        assert label["x"] == "2024-01-01T12:00:00"
        assert label["y"] > TOP_HALF
        assert label["yref"] == "y3 domain"

    def test_a_window_label_sits_at_the_start_of_the_window(self):
        label = annotation_to_plotly_annotation(make_annotation(AnnotationType.TIME_WINDOW), None)
        assert label["x"] == "2024-01-01T12:00:00"
        assert label["y"] > TOP_HALF
        assert label["yref"] == "paper"

    def test_a_scoped_window_label_is_drawn_against_its_subplot_domain(self):
        label = annotation_to_plotly_annotation(make_annotation(AnnotationType.TIME_WINDOW), "y5")
        assert label["yref"] == "y5 domain"

    @pytest.mark.parametrize(
        "annotation_type", [AnnotationType.TIME_EVENT, AnnotationType.TIME_WINDOW]
    )
    def test_an_unlabelled_annotation_gets_no_label(self, annotation_type):
        assert (
            annotation_to_plotly_annotation(make_annotation(annotation_type, label=""), "y3")
            is None
        )

    def test_an_unlabelled_event_still_draws_its_line(self):
        assert len(annotation_to_shapes(make_annotation(label=""), "y3")) == 1


# ==================================================================================================
# Composing a figure's overlays
# ==================================================================================================


class TestFigureOverlays:
    def _overlays(self, annotation: Annotation) -> tuple[list[dict], list[dict]]:
        return build_figure_overlays([annotation], "time_series", SUBPLOT_TITLES, SUBPLOT_ROWS)

    def test_a_scoped_annotation_is_drawn_against_its_subplot(self):
        shapes, annotations = self._overlays(make_annotation(subplot_name="Airway pressure"))
        assert [shape["yref"] for shape in shapes] == ["y3 domain"]
        assert annotations[-1]["yref"] == "y3 domain"

    def test_a_global_annotation_is_drawn_against_the_whole_figure(self):
        shapes, annotations = self._overlays(make_annotation(subplot_name=None))
        assert [shape["yref"] for shape in shapes] == ["paper"]
        assert annotations[-1]["yref"] == "paper"

    def test_an_annotation_whose_subplot_is_gone_is_dropped_entirely(self):
        """No shape and no label: a mark with nowhere to land is not drawn figure-wide instead."""
        shapes, annotations = self._overlays(make_annotation(subplot_name="Ghost"))
        assert shapes == []
        assert annotations == SUBPLOT_TITLES

    def test_the_subplot_titles_are_kept_ahead_of_our_own(self):
        _shapes, annotations = self._overlays(make_annotation(subplot_name="Flow"))
        assert annotations[0] == SUBPLOT_TITLES[0]

    def test_another_plots_annotations_are_left_out(self):
        shapes, annotations = build_figure_overlays(
            [make_annotation(plot_name="loop", subplot_name="Airway pressure")],
            "time_series",
            SUBPLOT_TITLES,
            SUBPLOT_ROWS,
        )
        assert shapes == []
        assert annotations == SUBPLOT_TITLES


# ==================================================================================================
# The pending time-window preview
# ==================================================================================================


class TestPreviewShape:
    def test_it_is_a_full_height_line_at_the_first_click(self):
        shape = make_preview_shape("2024-01-01T12:00:00")
        assert shape["type"] == "line"
        assert shape["x0"] == "2024-01-01T12:00:00"
        assert shape["x1"] == "2024-01-01T12:00:00"
        assert shape["y0"] == 0
        assert shape["y1"] == 1
        assert shape["yref"] == "paper"

    def test_it_defaults_to_the_shared_time_axis(self):
        assert make_preview_shape(NAIVE_INSTANT)["xref"] == "x"

    def test_it_can_be_drawn_against_another_x_axis(self):
        assert make_preview_shape(NAIVE_INSTANT, xref="x2")["xref"] == "x2"


# ==================================================================================================
# Timezone normalization: tz-aware stored value to display-TZ wall clock
# ==================================================================================================


class TestDisplayTimezoneNormalization:
    """Trace x-data is naive wall clock in the display timezone; annotations must match it."""

    @pytest.mark.parametrize(
        ("display_timezone", "expected"),
        [
            ("Europe/Paris", "2024-01-01T13:00:00"),
            ("UTC", "2024-01-01T12:00:00"),
            ("America/New_York", "2024-01-01T07:00:00"),
        ],
    )
    def test_an_event_lands_on_the_wall_clock_of_the_display_timezone(
        self, display_timezone, expected
    ):
        annotation = make_annotation(data={"x": STORED_INSTANT})
        assert normalize_annotation_for_display(annotation, display_timezone).data["x"] == expected

    def test_the_offset_follows_the_date_rather_than_being_fixed(self):
        """Paris is +1 in January and +2 in July; one fixed shift would be wrong half the year."""
        winter = make_annotation(data={"x": "2024-01-01T12:00:00+00:00"})
        summer = make_annotation(data={"x": "2024-07-01T12:00:00+00:00"})
        assert normalize_annotation_for_display(winter, "Europe/Paris").data["x"] == (
            "2024-01-01T13:00:00"
        )
        assert normalize_annotation_for_display(summer, "Europe/Paris").data["x"] == (
            "2024-07-01T14:00:00"
        )

    def test_both_ends_of_a_window_are_converted(self):
        annotation = make_annotation(
            AnnotationType.TIME_WINDOW, data={"x0": STORED_INSTANT, "x1": STORED_LATER}
        )
        data = normalize_annotation_for_display(annotation, "Europe/Paris").data
        assert data["x0"] == "2024-01-01T13:00:00"
        assert data["x1"] == "2024-01-01T15:30:00"

    def test_a_point_is_converted_and_keeps_everything_else(self):
        annotation = make_annotation(
            AnnotationType.POINT,
            data={"x": STORED_INSTANT, "y": POINT_Y, "xaxis": "x2", "yaxis": "y2"},
        )
        data = normalize_annotation_for_display(annotation, "Europe/Paris").data
        assert data["x"] == "2024-01-01T13:00:00"
        assert data["y"] == POINT_Y
        assert data["xaxis"] == "x2"
        assert data["yaxis"] == "y2"

    def test_a_loop_point_keeps_its_numeric_x(self):
        """A loop plot puts a signal on the x axis, so there is no clock time to convert."""
        annotation = make_annotation(
            AnnotationType.POINT, data={"x": LOOP_X, "y": POINT_Y}, plot_name="loop"
        )
        assert normalize_annotation_for_display(annotation, "Europe/Paris").data["x"] == LOOP_X

    def test_the_stored_annotation_is_left_untouched(self):
        """The store keeps the instant; only the copy handed to Plotly is wall clock."""
        annotation = make_annotation(data={"x": STORED_INSTANT})
        normalized = normalize_annotation_for_display(annotation, "Europe/Paris")
        assert annotation.data["x"] == "2024-01-01T12:00:00+00:00"
        assert normalized is not annotation
