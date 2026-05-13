"""
Unit tests for the public load_annotations function in wrapper.py.

Tests the auto-detection logic for the two source types:
1. Direct JSON file (path ends in .json)
2. Patient folder (any other path) — resolves to <folder>/clinical_scope_output/annotations.json
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from clinical_scope import load_annotations
from clinical_scope.constants import ANNOTATION_KEY
from clinical_scope.dash_api.annotations.model import (
    Annotation,
    AnnotationType,
)

TWO_ANNOTATIONS = 2


# ==================================================================================================
# Fixtures
# ==================================================================================================

@pytest.fixture
def sample_annotations() -> list[Annotation]:
    return [
        Annotation(
            type=AnnotationType.TIME_EVENT,
            plot_name="time_series",
            data={"x": "2024-01-01T00:00:00"},
            label="Test Event 1",
        ),
        Annotation(
            type=AnnotationType.TIME_WINDOW,
            plot_name="time_series",
            data={"x0": "2024-01-01T00:00:00", "x1": "2024-01-01T01:00:00"},
            label="Test Window 1",
        ),
    ]


@pytest.fixture
def envelope_json(sample_annotations) -> str:
    """Create a JSON envelope with annotations."""
    return json.dumps({ANNOTATION_KEY: [a.to_dict() for a in sample_annotations]}, indent=2)


# ==================================================================================================
# Test: Auto-detection logic
# ==================================================================================================

class TestAutoDetection:
    """Test that the path type is correctly auto-detected."""

    def test_json_suffix_resolves_to_direct_file(self):
        """Path ending in .json should be treated as a direct file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "annotations.json"
            json_path.write_text("[]")

            with patch(
                "clinical_scope.wrapper._load_annotations_from_path",
                return_value=[],
            ) as mock:
                load_annotations(json_path)

                # Should load from the json_path directly, not json_path/annotations.json
                mock.assert_called_once_with(json_path)

    def test_other_path_resolves_to_patient_folder(self):
        """Any non-JSON path should be treated as a patient folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Patient01"
            patient_path.mkdir()

            with patch(
                "clinical_scope.wrapper._load_annotations_from_path",
                return_value=[],
            ) as mock:
                load_annotations(patient_path)

                # Should resolve to Patient01/clinical_scope_output/annotations.json
                mock.assert_called_once_with(
                    patient_path / "clinical_scope_output" / "annotations.json"
                )


# ==================================================================================================
# Test: Envelope format validation
# ==================================================================================================

class TestEnvelopeFormat:
    """Test that only the correct envelope format is accepted."""

    def test_returns_empty_for_non_envelope_json(self):
        """Non-envelope JSON (bare list or other structure) should be rejected."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("[]")
            f.flush()

        annotations = load_annotations(f.name)
        assert annotations == []

    def test_loads_from_envelope(self, envelope_json):
        """Valid envelope should load annotations correctly."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write(envelope_json)
            f.flush()

        annotations = load_annotations(f.name)

        assert len(annotations) == TWO_ANNOTATIONS
        assert isinstance(annotations[0], Annotation)
