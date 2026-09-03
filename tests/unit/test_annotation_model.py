"""
Unit tests for Annotation, Group and AnnotationSet in annotations/model.py.

These exercise the logic that used to live inline in the annotation callbacks, where it
could not be reached without a Dash context.
"""

from __future__ import annotations

import pytest

from clinical_scope.dash_api.annotations.model import (
    Annotation,
    AnnotationSet,
    AnnotationType,
    Group,
)

TWO = 2
THREE = 3


# ==================================================================================================
# Helpers
# ==================================================================================================


def make_annotation(
    annotation_id: str,
    *,
    group_id: str | None = None,
    group_name: str | None = None,
    color: str = "#e74c3c",
    annotation_type: AnnotationType = AnnotationType.TIME_EVENT,
    subplot_name: str | None = "Pressure",
    label_hidden: bool = False,
    hidden: bool = False,
) -> Annotation:
    """Build an annotation with an explicit id so ordering assertions stay readable."""
    return Annotation(
        id=annotation_id,
        type=annotation_type,
        plot_name="time_series",
        data={"x": "2024-01-01T00:00:00+00:00"},
        group_id=group_id,
        group_name=group_name,
        color=color,
        subplot_name=subplot_name,
        label_hidden=label_hidden,
        hidden=hidden,
    )


# ==================================================================================================
# Group derivation
# ==================================================================================================


class TestGroupDerivation:
    """Groups are rebuilt from the annotations alone; no group metadata is ever persisted."""

    def test_groups_are_returned_in_first_seen_order(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g2", group_name="Second"),
                make_annotation("b", group_id="g1", group_name="First"),
                make_annotation("c", group_id="g2", group_name="Second"),
            ]
        )
        assert [group.id for group in annotation_set.groups()] == ["g2", "g1"]

    def test_group_metadata_comes_from_the_first_member(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", group_name="Weaning", color="#3498db"),
                make_annotation("b", group_id="g1", group_name="IGNORED", color="#000000"),
            ]
        )
        group = annotation_set.groups()[0]
        assert group.name == "Weaning"
        assert group.color == "#3498db"

    def test_members_keep_creation_order(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1"),
                make_annotation("b"),
                make_annotation("c", group_id="g1"),
            ]
        )
        assert [a.id for a in annotation_set.groups()[0].annotations] == ["a", "c"]

    def test_is_global_is_encoded_as_a_missing_subplot_name(self):
        grouped = AnnotationSet([make_annotation("a", group_id="g1", subplot_name=None)])
        assert grouped.groups()[0].is_global is True
        scoped = AnnotationSet([make_annotation("a", group_id="g1", subplot_name="Flow")])
        assert scoped.groups()[0].is_global is False

    def test_ungrouped_holds_only_annotations_without_a_group(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1"),
                make_annotation("b"),
                make_annotation("c"),
            ]
        )
        assert [a.id for a in annotation_set.ungrouped()] == ["b", "c"]

    def test_group_lookup_returns_none_for_an_unknown_id(self):
        annotation_set = AnnotationSet([make_annotation("a", group_id="g1")])
        assert annotation_set.group("g1") is not None
        assert annotation_set.group("nope") is None

    def test_a_group_can_never_be_empty(self):
        """Every derived group carries a member, so `labels_hidden` is always defined."""
        annotation_set = AnnotationSet(
            [make_annotation("a", group_id="g1"), make_annotation("b", group_id="g2")]
        )
        assert all(len(group) >= 1 for group in annotation_set.groups())


# ==================================================================================================
# Label visibility
# ==================================================================================================


class TestLabelVisibility:
    """The group Labels button and the mutator that flips it must read the same rule."""

    def test_group_labels_hidden_only_when_every_member_is_hidden(self):
        partly = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=True),
                make_annotation("b", group_id="g1", label_hidden=False),
            ]
        )
        assert partly.groups()[0].labels_hidden is False

        fully = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=True),
                make_annotation("b", group_id="g1", label_hidden=True),
            ]
        )
        assert fully.groups()[0].labels_hidden is True

    @pytest.mark.parametrize("start_hidden", [True, False])
    def test_toggling_a_group_flips_it_to_the_state_the_button_is_not_showing(self, start_hidden):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=start_hidden),
                make_annotation("b", group_id="g1", label_hidden=start_hidden),
            ]
        )
        before = annotation_set.groups()[0].labels_hidden
        after = annotation_set.with_group_labels_toggled("g1").groups()[0].labels_hidden
        assert after is not before

    def test_a_mixed_group_hides_every_member(self):
        """Any visible label means the group reads as shown, so one click hides all of it."""
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=True),
                make_annotation("b", group_id="g1", label_hidden=False),
            ]
        )
        toggled = annotation_set.with_group_labels_toggled("g1")
        assert all(annotation.label_hidden for annotation in toggled)

    def test_toggling_a_group_leaves_other_groups_alone(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=False),
                make_annotation("b", group_id="g2", label_hidden=False),
            ]
        )
        toggled = annotation_set.with_group_labels_toggled("g1")
        assert toggled.group("g2").labels_hidden is False

    def test_toggling_an_unknown_group_is_a_no_op(self):
        annotation_set = AnnotationSet([make_annotation("a", group_id="g1")])
        assert annotation_set.with_group_labels_toggled("nope").to_dicts() == (
            annotation_set.to_dicts()
        )

    def test_toggling_one_annotation_flips_only_that_one(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=False),
                make_annotation("b", group_id="g1", label_hidden=False),
            ]
        )
        toggled = annotation_set.with_label_toggled("a")
        assert [annotation.label_hidden for annotation in toggled] == [True, False]


# ==================================================================================================
# Whole-annotation visibility
# ==================================================================================================


class TestAnnotationVisibility:
    """`hidden` suppresses the whole annotation; `label_hidden` suppresses only its text."""

    def test_an_annotation_is_visible_by_default(self):
        assert make_annotation("a").hidden is False

    def test_group_hidden_only_when_every_member_is_hidden(self):
        partly = AnnotationSet(
            [
                make_annotation("a", group_id="g1", hidden=True),
                make_annotation("b", group_id="g1", hidden=False),
            ]
        )
        assert partly.groups()[0].hidden is False

        fully = AnnotationSet(
            [
                make_annotation("a", group_id="g1", hidden=True),
                make_annotation("b", group_id="g1", hidden=True),
            ]
        )
        assert fully.groups()[0].hidden is True

    @pytest.mark.parametrize("start_hidden", [True, False])
    def test_toggling_a_group_flips_it_to_the_state_the_button_is_not_showing(self, start_hidden):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", hidden=start_hidden),
                make_annotation("b", group_id="g1", hidden=start_hidden),
            ]
        )
        before = annotation_set.groups()[0].hidden
        after = annotation_set.with_group_hidden_toggled("g1").groups()[0].hidden
        assert after is not before

    def test_a_mixed_group_hides_every_member(self):
        """Any shown member means the group reads as shown, so one click hides all of it."""
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", hidden=True),
                make_annotation("b", group_id="g1", hidden=False),
            ]
        )
        assert all(annotation.hidden for annotation in annotation_set.with_group_hidden_toggled("g1"))

    def test_toggling_a_group_leaves_other_groups_alone(self):
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1"),
                make_annotation("b", group_id="g2"),
            ]
        )
        assert annotation_set.with_group_hidden_toggled("g1").group("g2").hidden is False

    def test_toggling_an_unknown_group_is_a_no_op(self):
        annotation_set = AnnotationSet([make_annotation("a", group_id="g1")])
        assert annotation_set.with_group_hidden_toggled("nope").to_dicts() == (
            annotation_set.to_dicts()
        )

    def test_toggling_one_annotation_flips_only_that_one(self):
        annotation_set = AnnotationSet(
            [make_annotation("a", group_id="g1"), make_annotation("b", group_id="g1")]
        )
        toggled = annotation_set.with_hidden_toggled("a")
        assert [annotation.hidden for annotation in toggled] == [True, False]

    def test_hiding_a_group_preserves_each_members_own_label_choice(self):
        """The reason the two flags stay separate rather than collapsing into one tri-state."""
        annotation_set = AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=True),
                make_annotation("b", group_id="g1", label_hidden=False),
            ]
        )
        round_tripped = annotation_set.with_group_hidden_toggled("g1").with_group_hidden_toggled(
            "g1"
        )
        assert [annotation.label_hidden for annotation in round_tripped] == [True, False]

    def test_hidden_survives_a_move(self):
        annotation_set = AnnotationSet([make_annotation("a", hidden=True)])
        moved = annotation_set.with_moved(
            "a",
            data={"x": "2024-01-01T01:00:00+00:00"},
            plot_name="time_series",
            subplot_name="Flow",
            trace_metadata=None,
        )
        assert moved.annotations[0].hidden is True

    def test_hidden_round_trips_through_a_dict(self):
        annotation = make_annotation("a", hidden=True)
        assert Annotation.from_dict(annotation.to_dict()).hidden is True

    def test_a_file_predating_the_field_loads_as_visible(self):
        """`hidden` is absent from every annotations.json written before this feature."""
        raw = {"id": "a", "type": "time_event", "plot_name": "time_series", "data": {}}
        annotation = Annotation.from_dict(raw)
        assert annotation.hidden is False
        assert "hidden" not in annotation.extra


# ==================================================================================================
# Mutators return new sets
# ==================================================================================================


class TestImmutability:
    """Every mutator returns a new set; callbacks never mutate the store payload in place."""

    @pytest.fixture
    def annotation_set(self) -> AnnotationSet:
        return AnnotationSet(
            [
                make_annotation("a", group_id="g1", label_hidden=False),
                make_annotation("b", group_id="g1", label_hidden=False),
                make_annotation("c"),
            ]
        )

    @pytest.mark.parametrize(
        ("method", "argument"),
        [
            ("without", "a"),
            ("without_group", "g1"),
            ("with_label_toggled", "a"),
            ("with_group_labels_toggled", "g1"),
            ("with_hidden_toggled", "a"),
            ("with_group_hidden_toggled", "g1"),
        ],
    )
    def test_source_set_is_unchanged(self, annotation_set, method, argument):
        before = annotation_set.to_dicts()
        getattr(annotation_set, method)(argument)
        assert annotation_set.to_dicts() == before

    def test_without_drops_one_annotation(self, annotation_set):
        assert [a.id for a in annotation_set.without("a")] == ["b", "c"]

    def test_without_group_drops_every_member(self, annotation_set):
        assert [a.id for a in annotation_set.without_group("g1")] == ["c"]

    def test_with_added_appends_at_the_end(self, annotation_set):
        grown = annotation_set.with_added(make_annotation("d"))
        assert [a.id for a in grown] == ["a", "b", "c", "d"]
        assert len(annotation_set) == THREE


# ==================================================================================================
# Serialisation boundary
# ==================================================================================================


class TestOpenSchema:
    """Keys the app does not own survive a round-trip (ADR-0012)."""

    def test_unknown_keys_survive_a_round_trip(self):
        raw = {
            "id": "a",
            "type": "time_event",
            "plot_name": "time_series",
            "data": {"x": "2024-01-01T00:00:00+00:00"},
            "reviewer": "dr-who",
            "confidence": 0.8,
        }
        round_tripped = Annotation.from_dict(raw).to_dict()
        assert round_tripped["reviewer"] == "dr-who"
        assert round_tripped["confidence"] == pytest.approx(0.8)

    def test_unknown_keys_survive_a_mutation(self):
        raw = [
            {
                "id": "a",
                "type": "time_event",
                "plot_name": "time_series",
                "data": {},
                "group_id": "g1",
                "reviewer": "dr-who",
            },
            {"id": "b", "type": "time_event", "plot_name": "time_series", "data": {}},
        ]
        survivor = AnnotationSet.from_dicts(raw).without("b").to_dicts()[0]
        assert survivor["reviewer"] == "dr-who"

    def test_a_known_field_can_never_be_shadowed(self):
        """`extra` is splatted first, so a stale duplicate key cannot overwrite a real field."""
        annotation = Annotation.from_dict(
            {"id": "a", "type": "time_event", "plot_name": "time_series", "data": {}}
        )
        annotation.extra["id"] = "hijacked"
        assert annotation.to_dict()["id"] == "a"

    def test_an_annotation_with_no_extra_keys_serialises_the_owned_set(self):
        raw = {"id": "a", "type": "time_event", "plot_name": "time_series", "data": {}}
        assert Annotation.from_dict(raw).extra == {}

    def test_from_dicts_tolerates_an_untouched_store(self):
        assert len(AnnotationSet.from_dicts(None)) == 0


# ==================================================================================================
# Creation-time defaulting
# ==================================================================================================


class TestAnnotationCreate:
    """`create` interprets; `from_dict` transcribes."""

    def test_a_point_is_never_global(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.POINT,
            plot_name="time_series",
            data={},
            is_global=True,
            subplot_name="Pressure",
        )
        assert annotation.subplot_name == "Pressure"

    def test_a_point_starts_with_its_label_hidden(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.POINT, plot_name="time_series", data={}
        )
        assert annotation.label_hidden is True

    def test_an_explicit_label_hidden_wins_over_the_point_default(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.POINT,
            plot_name="time_series",
            data={},
            label_hidden=False,
        )
        assert annotation.label_hidden is False

    def test_a_time_event_keeps_its_label_shown(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.TIME_EVENT, plot_name="time_series", data={}
        )
        assert annotation.label_hidden is False

    def test_a_global_time_event_drops_its_subplot_name(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.TIME_EVENT,
            plot_name="time_series",
            data={},
            is_global=True,
            subplot_name="Pressure",
        )
        assert annotation.subplot_name is None

    def test_a_scoped_time_event_keeps_its_subplot_name(self):
        annotation = Annotation.create(
            annotation_type=AnnotationType.TIME_EVENT,
            plot_name="time_series",
            data={},
            is_global=False,
            subplot_name="Pressure",
        )
        assert annotation.subplot_name == "Pressure"

    def test_deserialisation_does_not_apply_creation_defaults(self):
        """A point whose label the user un-hid must load back un-hidden."""
        raw = {
            "id": "a",
            "type": "point",
            "plot_name": "time_series",
            "data": {},
            "label_hidden": False,
            "subplot_name": None,
        }
        annotation = Annotation.from_dict(raw)
        assert annotation.label_hidden is False
        assert annotation.subplot_name is None


# ==================================================================================================
# Group is a value object
# ==================================================================================================


def test_group_length_is_its_member_count():
    annotation_set = AnnotationSet(
        [make_annotation("a", group_id="g1"), make_annotation("b", group_id="g1")]
    )
    assert len(annotation_set.groups()[0]) == TWO


def test_group_carries_the_annotation_type_as_an_enum():
    annotation_set = AnnotationSet(
        [make_annotation("a", group_id="g1", annotation_type=AnnotationType.TIME_WINDOW)]
    )
    group = annotation_set.groups()[0]
    assert isinstance(group, Group)
    assert group.type is AnnotationType.TIME_WINDOW


# ==================================================================================================
# Moving an annotation
# ==================================================================================================


class TestMove:
    """A move re-derives position, plot, scope and trace from the new click — and nothing else."""

    NEW_DATA = {"x": "2024-06-01T12:00:00+00:00", "xaxis": "x2"}

    @pytest.fixture
    def annotation_set(self) -> AnnotationSet:
        return AnnotationSet(
            [
                Annotation(
                    id="a",
                    type=AnnotationType.TIME_EVENT,
                    plot_name="time_series",
                    data={"x": "2024-01-01T00:00:00+00:00", "xaxis": "x"},
                    label="Intubation",
                    color="#3498db",
                    subplot_name="Pressure",
                    group_id="g1",
                    group_name="Events",
                    label_hidden=True,
                    created_at="2024-01-01T00:00:00+00:00",
                    extra={"reviewer": "AJ"},
                ),
                make_annotation("b"),
            ]
        )

    def _moved(self, annotation_set: AnnotationSet, **overrides) -> AnnotationSet:
        return annotation_set.with_moved(
            "a",
            **{
                "data": self.NEW_DATA,
                "plot_name": "time_series",
                "subplot_name": "Flow",
                "trace_metadata": {"display_name": "Paw"},
                **overrides,
            },
        )

    def test_position_comes_from_the_new_click(self, annotation_set):
        moved = self._moved(annotation_set).annotations[0]
        assert moved.data == {"x": "2024-06-01T12:00:00+00:00", "xaxis": "x2"}

    def test_scope_and_trace_are_re_derived(self, annotation_set):
        """A point moved into another subplot must take that subplot's axis, not keep the old."""
        moved = self._moved(annotation_set).annotations[0]
        assert moved.subplot_name == "Flow"
        assert moved.trace_metadata == {"display_name": "Paw"}

    def test_the_plot_can_change(self, annotation_set):
        assert self._moved(annotation_set, plot_name="loop").annotations[0].plot_name == "loop"

    def test_identity_and_metadata_survive(self, annotation_set):
        moved = self._moved(annotation_set).annotations[0]
        assert moved.id == "a"
        assert moved.label == "Intubation"
        assert moved.color == "#3498db"
        assert moved.group_id == "g1"
        assert moved.group_name == "Events"
        assert moved.label_hidden is True
        assert moved.created_at == "2024-01-01T00:00:00+00:00"

    def test_unowned_keys_survive_a_move(self, annotation_set):
        """A hand-written annotations.json round-trips through a move (ADR-0012)."""
        assert self._moved(annotation_set).to_dicts()[0]["reviewer"] == "AJ"

    def test_a_global_annotation_stays_global(self):
        """Globalness is a modal choice, not a fact about coordinates: a nudge cannot demote it."""
        annotation_set = AnnotationSet([make_annotation("a", subplot_name=None)])
        moved = annotation_set.with_moved(
            "a",
            data=self.NEW_DATA,
            plot_name="time_series",
            subplot_name="Flow",
            trace_metadata=None,
        )
        assert moved.annotations[0].subplot_name is None

    def test_other_annotations_are_untouched(self, annotation_set):
        untouched = self._moved(annotation_set).annotations[1]
        assert untouched.data == {"x": "2024-01-01T00:00:00+00:00"}
        assert untouched.subplot_name == "Pressure"

    def test_moving_an_unknown_id_is_a_no_op(self, annotation_set):
        moved = annotation_set.with_moved(
            "missing",
            data=self.NEW_DATA,
            plot_name="loop",
            subplot_name=None,
            trace_metadata=None,
        )
        assert moved.to_dicts() == annotation_set.to_dicts()

    def test_source_set_is_unchanged(self, annotation_set):
        before = annotation_set.to_dicts()
        self._moved(annotation_set)
        assert annotation_set.to_dicts() == before
