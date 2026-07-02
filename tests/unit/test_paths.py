"""Unit tests for io.paths — output folder resolution, with and without output_root.

Covers ADR 0003: when ``output_root`` is set, every artifact path is rehomed to
``<output_root>/<patient_folder_name>/clinical_scope_output/`` while keeping the legacy
in-folder layout when it is unset.
"""

from __future__ import annotations

from pathlib import Path

import clinical_scope.constants as cst
from clinical_scope.io.paths import (
    _get_output_folder,
    get_annotations_path,
    get_database_options_path,
    get_datasource_cache_path,
    get_output_base,
    get_patient_options_path,
    get_visualization_path,
)

PATIENT = Path("/data/patient_007")
LEAF = cst.FOLDER_NAME_OUTPUT


class TestOutputBase:
    def test_unset_returns_patient_folder(self):
        assert get_output_base(PATIENT) == PATIENT

    def test_unset_via_empty_string(self):
        # The callbacks pass ``output_root or None``; an empty path falls back to legacy.
        assert get_output_base(PATIENT, "") == PATIENT

    def test_set_nests_under_root_by_name(self):
        assert get_output_base(PATIENT, "/scratch") == Path("/scratch/patient_007")


class TestOutputFolder:
    def test_legacy_layout(self):
        assert _get_output_folder(PATIENT) == PATIENT / LEAF

    def test_redirected_layout(self):
        assert _get_output_folder(PATIENT, "/scratch") == Path("/scratch/patient_007") / LEAF


class TestArtifactPaths:
    """Every public helper resolves both branches consistently."""

    def test_legacy_branch(self):
        assert get_visualization_path(PATIENT) == PATIENT / LEAF / cst.DEFAULT_NAME_VISUALIZATION
        assert (
            get_database_options_path(PATIENT) == PATIENT / LEAF / cst.DEFAULT_NAME_DATABASE_OPTIONS
        )
        assert (
            get_patient_options_path(PATIENT) == PATIENT / LEAF / cst.DEFAULT_NAME_PATIENT_OPTIONS
        )
        assert get_annotations_path(PATIENT) == PATIENT / LEAF / cst.ANNOTATION_FILE_NAME
        assert get_datasource_cache_path(PATIENT, "x.parquet") == PATIENT / LEAF / "x.parquet"

    def test_redirected_branch(self):
        base = Path("/scratch/patient_007") / LEAF
        assert get_visualization_path(PATIENT, "/scratch") == base / cst.DEFAULT_NAME_VISUALIZATION
        assert (
            get_database_options_path(PATIENT, "/scratch")
            == base / cst.DEFAULT_NAME_DATABASE_OPTIONS
        )
        assert (
            get_patient_options_path(PATIENT, "/scratch") == base / cst.DEFAULT_NAME_PATIENT_OPTIONS
        )
        assert get_annotations_path(PATIENT, "/scratch") == base / cst.ANNOTATION_FILE_NAME
        assert get_datasource_cache_path(PATIENT, "x.parquet", "/scratch") == base / "x.parquet"

    def test_annotations_path_on_resolved_base_matches_redirect(self):
        """The annotation channel feeds get_annotations_path an already-resolved base.

        Passing ``get_output_base(...)`` (no output_root) must land in the same place as
        passing the patient folder *with* output_root — this is what keeps the public
        annotation API unchanged under redirection.
        """
        resolved = get_output_base(PATIENT, "/scratch")
        assert get_annotations_path(resolved) == get_annotations_path(PATIENT, "/scratch")
