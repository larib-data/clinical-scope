"""
Unit tests for plot_assembly._resolve_signal_references.

The three-mode chain carries the whole weight of `grouped_fields`, `global.loop` and `psd`
signal references, and `::` means two different things depending on the datasource: for most
sources a reference is `datasource::raw_name`, but an 'other' file's raw_name is *itself*
`<stem>::<column>`, so `other::waves::art` and `waves::art` must both land on the same signal.
"""

import pytest

from clinical_scope.signal_reference import resolve_signal_references
from clinical_scope.signal_container import Metadata, Signal


def _signal(raw_name: str, name: str, datasource_name: str) -> Signal:
    return Signal(
        raw_name=raw_name,
        name=name,
        metadata=Metadata(datasource_name=datasource_name),
    )


@pytest.fixture
def signals() -> list[Signal]:
    return [
        _signal("Paw", "Airway Pressure", "servo_u"),
        _signal("Vol", "Volume", "servo_u"),
        _signal("waves::art", "Arterial Pressure", "other"),
        _signal("numerics::flow", "Flow", "other"),
    ]


class TestQualifiedNames:
    def test_datasource_qualified_name_resolves(self, signals):
        assert [s.raw_name for s in resolve_signal_references(["servo_u::Paw"], signals)] == [
            "Paw"
        ]

    def test_other_file_signal_resolves_by_full_three_part_name(self, signals):
        matched = resolve_signal_references(["other::waves::art"], signals)
        assert [s.raw_name for s in matched] == ["waves::art"]

    def test_other_file_signal_resolves_by_bare_raw_name(self, signals):
        """`<stem>::<column>` is the raw_name itself — the form the 'other' loader injects."""
        matched = resolve_signal_references(["waves::art"], signals)
        assert [s.raw_name for s in matched] == ["waves::art"]

    def test_unmatched_qualified_reference_resolves_to_nothing(self, signals):
        assert resolve_signal_references(["servo_u::NoSuchSignal"], signals) == []

    def test_unmatched_qualified_reference_warns(self, signals, caplog):
        resolve_signal_references(["servo_u::NoSuchSignal"], signals)
        assert "did not match any signal" in caplog.text

    def test_a_resolved_bare_raw_name_does_not_warn(self, signals, caplog):
        """Falling through from mode 1 to mode 3 is a success, not a near-miss."""
        resolve_signal_references(["waves::art"], signals)
        assert "did not match any signal" not in caplog.text


class TestUnqualifiedNames:
    def test_display_name_resolves(self, signals):
        matched = resolve_signal_references(["Airway Pressure"], signals)
        assert [s.raw_name for s in matched] == ["Paw"]

    def test_raw_name_resolves(self, signals):
        assert [s.raw_name for s in resolve_signal_references(["Vol"], signals)] == ["Vol"]

    def test_ambiguous_display_name_is_dropped_with_a_warning(self, caplog):
        duplicated = [
            _signal("a", "Pressure", "servo_u"),
            _signal("b", "Pressure", "eit"),
        ]
        assert resolve_signal_references(["Pressure"], duplicated) == []
        assert "Ambiguous display name" in caplog.text


class TestCollisionBetweenTheTwoMeanings:
    """A file ``other/servo_u.parquet`` makes ``servo_u::Paw`` a legitimate name for two signals."""

    @pytest.fixture
    def colliding(self) -> list[Signal]:
        return [
            _signal("Paw", "Airway Pressure", "servo_u"),
            _signal("servo_u::Paw", "Paw from dump", "other"),
        ]

    def test_the_datasource_reading_wins(self, colliding):
        matched = resolve_signal_references(["servo_u::Paw"], colliding)
        assert [s.metadata.datasource_name for s in matched] == ["servo_u"]

    def test_the_collision_is_logged(self, colliding, caplog):
        resolve_signal_references(["servo_u::Paw"], colliding)
        assert "Ambiguous signal reference" in caplog.text

    def test_the_log_gives_the_spelling_that_reaches_the_other_signal(self, colliding, caplog):
        resolve_signal_references(["servo_u::Paw"], colliding)
        assert "other::servo_u::Paw" in caplog.text

    def test_that_spelling_does_reach_the_other_signal(self, colliding):
        matched = resolve_signal_references(["other::servo_u::Paw"], colliding)
        assert [s.raw_name for s in matched] == ["servo_u::Paw"]

    def test_no_warning_when_nothing_is_shadowed(self, signals, caplog):
        resolve_signal_references(["servo_u::Paw", "other::waves::art"], signals)
        assert "Ambiguous signal reference" not in caplog.text


class TestMixedReferences:
    def test_references_from_two_sources_resolve_together(self, signals):
        """What a cross-datasource group, loop or PSD relies on."""
        matched = resolve_signal_references(["servo_u::Paw", "other::waves::art"], signals)
        assert [s.raw_name for s in matched] == ["Paw", "waves::art"]

    def test_two_other_files_resolve_together(self, signals):
        matched = resolve_signal_references(["waves::art", "numerics::flow"], signals)
        assert [s.raw_name for s in matched] == ["waves::art", "numerics::flow"]
