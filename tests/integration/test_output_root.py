"""Integration tests for output_root redirection (ADR 0003).

When ``output_root`` is set, every generated artifact lands under
``<output_root>/<patient_folder_name>/clinical_scope_output/`` instead of inside the
(possibly read-only) patient folder. These tests pin the two end-to-end guarantees:
the parquet cache is rehomed and the raw folder is left clean, and a shared root behaves
as a browsable Database for batch extraction + ``load_database_annotations``.
"""

from __future__ import annotations

import shutil

from clinical_scope import load_database_annotations
from clinical_scope.dash_api.annotations.io import save_annotations
from clinical_scope.dash_api.annotations.model import Annotation, AnnotationType
from clinical_scope.io.paths import get_output_base
from clinical_scope.wrapper import extract_patient


def _copy_patient(src, dst_parent):
    """Copy a demo patient into a fresh dir (minus any pre-existing cache)."""
    dst = dst_parent / src.name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("clinical_scope_output"))
    return dst


class TestCacheRedirect:
    def test_cache_lands_under_output_root(
        self, patient_full_path, default_database_options, tmp_path
    ):
        patient = _copy_patient(patient_full_path, tmp_path / "data")
        output_root = tmp_path / "scratch"

        results = extract_patient(
            patient,
            default_database_options,
            patient_options={"output_root": str(output_root), "quick_load": False},
        )
        successes = sum(1 for v in results.values() if v is not None)

        redirected = output_root / patient.name / "clinical_scope_output"
        cached = list(redirected.glob("*.parquet"))
        assert cached, "no parquet cache written under output_root"
        assert successes > 0

        # The read-only patient folder must stay untouched — no cache created in place.
        assert not (patient / "clinical_scope_output").exists()


class TestBatchNoCollision:
    def test_two_patients_share_root_without_collision(
        self, patient_full_path, patient_difficult_path, tmp_path
    ):
        output_root = tmp_path / "scratch"
        names = []
        for src in (patient_full_path, patient_difficult_path):
            patient = _copy_patient(src, tmp_path / "data")
            names.append(patient.name)
            extract_patient(patient, patient_options={"output_root": str(output_root)})

        # Each patient gets its own subfolder — the per-patient leaf derives from data_folder.
        for name in names:
            assert (output_root / name / "clinical_scope_output").is_dir()
        assert names[0] != names[1]


class TestSameNameCollision:
    def test_shared_root_same_name_overwrites(self, tmp_path):
        """A shared root keys patients by folder name only, so same-named patients collide.

        Documented limitation (ADR 0003): two *different* Databases that share a patient-folder
        name under the **same** output_root collapse onto one leaf, and the second write
        overwrites the first. This pins the tutorial 'Known limitation' bullet as an executable
        contract — if a future change disambiguated the leaf (e.g. a Database-name hash), this
        test would fail and force the doc to be updated in lockstep.
        """
        output_root = tmp_path / "scratch"
        # Two distinct Databases, each holding an identically named patient folder.
        db_a_patient = tmp_path / "database_a" / "patient_01"
        db_b_patient = tmp_path / "database_b" / "patient_01"

        def _event(label: str) -> Annotation:
            return Annotation(
                type=AnnotationType.TIME_EVENT,
                plot_name="time_series",
                data={"x": "2024-01-01T00:00:00"},
                label=label,
            )

        save_annotations([_event("from_database_a")], get_output_base(db_a_patient, output_root))
        save_annotations([_event("from_database_b")], get_output_base(db_b_patient, output_root))

        # Both patient folders resolve to the very same output leaf...
        assert get_output_base(db_a_patient, output_root) == get_output_base(
            db_b_patient, output_root
        )
        # ...so the shared root holds a single patient and only the last write survived.
        loaded = load_database_annotations(output_root)
        assert len(loaded) == 1
        assert loaded[0].label == "from_database_b"


class TestDatabaseAnnotationsOverRoot:
    def test_load_database_annotations_reads_redirected_root(self, tmp_path):
        """output_root mirrors a Database, so load_database_annotations(root) finds every patient."""
        output_root = tmp_path / "scratch"
        ann = Annotation(
            type=AnnotationType.TIME_EVENT,
            plot_name="time_series",
            data={"x": "2024-01-01T00:00:00"},
            label="evt",
        )
        for patient_name in ("patient_01", "patient_02"):
            patient_folder = tmp_path / "data" / patient_name
            base = get_output_base(patient_folder, output_root)
            save_annotations([ann], base)

        loaded = load_database_annotations(output_root)
        assert len(loaded) == 2
        assert {a.patient for a in loaded} == {"patient_01", "patient_02"}
