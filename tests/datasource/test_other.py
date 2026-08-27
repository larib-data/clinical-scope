"""
Tests for other (generic) datasource — auto datetime detection, per-file grouping.

It has a custom main() that processes files individually rather than using _load().
"""

import copy
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import clinical_scope.constants as cst
from clinical_scope.database_options_parser import (
    normalize_database_options,
    validate_database_options,
)


class TestFind:
    def test_find_folder_returns_path(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        assert folder is not None
        assert folder.is_dir()

    def test_find_returns_list(self, patient_difficult_path, other_cls):
        """Other is MULTI_FILE — _find() should return a list."""
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extensions(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        for p in result:
            assert p.suffix in (".csv", ".parquet")


class TestMainPipeline:
    """The 'other' datasource has a custom main() — test the full pipeline."""

    def test_main_returns_signals(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        assert isinstance(signals, list)
        assert len(signals) > 0

    def test_main_signals_have_data(self, patient_difficult_path):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        for sig in signals:
            assert sig.data.x is not None
            assert sig.data.y is not None
            assert len(sig.data.x) > 0


class TestExtract:
    """The 'other' datasource does not support extract() — each file is its own signal group."""

    def test_extract_returns_none(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        df = other_cls.extract(patient_options, {})
        assert df is None, (
            "other.extract() must return None (multi-file datasource has no single-DataFrame representation)"
        )


# ---------------------------------------------------------------------------
# Per-file config tests (other::filename feature)
# ---------------------------------------------------------------------------

PATIENT_OPTIONS = {
    "datetime_start": None,
    "datetime_end": None,
    "quick_load": False,
}


class TestFieldDisplayFiltering:
    """field_display in an other::filename section filters signals to the listed columns."""

    def test_per_file_field_display_limits_signals(self, patient_difficult_path):
        """Only the listed columns are returned when per-file field_display is set."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}

        db_opts = {
            "other::waves_first_half_filtered": {
                "field_display": ["Solar8000/HR", "Solar8000/PLETH_SPO2"],
            }
        }
        normalize_database_options(db_opts)
        signals = ds.MAIN_MODULE(patient_options, db_opts["other"])

        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        returned_cols = {s.raw_name.split("::", 1)[1] for s in file_signals}
        assert returned_cols == {"Solar8000/HR", "Solar8000/PLETH_SPO2"}

    def test_no_field_display_returns_all_columns(self, patient_difficult_path):
        """When no field_display is configured, all numeric columns are returned."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}

        signals = ds.MAIN_MODULE(patient_options, {})

        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        # The parquet file has 6 columns — all should be loaded
        assert len(file_signals) == 6


class TestSignalOptionApplication:
    """Signal options (label, unit, color, range) are applied from database_options."""

    def _run_main(self, patient_difficult_path, db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        return ds.MAIN_MODULE(patient_options, db_opts)

    def test_per_file_label_applied(self, patient_difficult_path):
        """Signal label from other::filename section is applied to sig.name."""

        db_opts = {
            "other::waves_first_half_filtered": {
                "signals": {"Solar8000/HR": {"label": "Heart Rate (custom)"}}
            }
        }
        normalize_database_options(db_opts)
        signals = self._run_main(patient_difficult_path, db_opts["other"])

        hr = next(
            (s for s in signals if s.raw_name == "waves_first_half_filtered::Solar8000/HR"), None
        )
        assert hr is not None, "HR signal not found"
        assert hr.name == "Heart Rate (custom)"

    def test_no_config_uses_column_name_as_label(self, patient_difficult_path):
        """Without any signal config, sig.name defaults to the raw column name."""
        signals = self._run_main(patient_difficult_path, {})

        hr = next(
            (s for s in signals if s.raw_name == "waves_first_half_filtered::Solar8000/HR"), None
        )
        assert hr is not None
        assert hr.name == "Solar8000/HR"


class TestGroupedFields:
    """Per-file grouped_fields from other::filename section are injected into database_options."""

    def _run_main_and_get_db_opts(self, patient_difficult_path, global_db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        ds.MAIN_MODULE(patient_options, global_db_opts)
        return global_db_opts

    def test_per_file_grouped_fields_injected_with_prefix(self, patient_difficult_path):
        """Both the group name and its signal references are scoped to the file."""

        db_opts = {
            "other::waves_first_half_filtered": {
                "grouped_fields": {
                    "Vital signs": ["Solar8000/HR", "Solar8000/PLETH_SPO2"],
                }
            }
        }
        normalize_database_options(db_opts)
        result = self._run_main_and_get_db_opts(patient_difficult_path, db_opts["other"])

        groups = result.get("grouped_fields", {})
        group_name = "waves_first_half_filtered::Vital signs"
        assert group_name in groups
        assert "waves_first_half_filtered::Solar8000/HR" in groups[group_name]
        assert "waves_first_half_filtered::Solar8000/PLETH_SPO2" in groups[group_name]

    def test_group_by_file_creates_auto_group(self, patient_difficult_path):
        """When group_by_file=True (default) and no custom groups, file stem is the group name."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {
            **PATIENT_OPTIONS,
            "data_folder": str(patient_difficult_path),
            "other": {"group_by_file": True},
        }
        db_opts = {}
        ds.MAIN_MODULE(patient_options, db_opts)

        groups = db_opts.get("grouped_fields", {})
        assert "waves_first_half_filtered" in groups

    def test_group_by_file_false_no_auto_group(self, patient_difficult_path):
        """When group_by_file=False, no grouped_fields are injected."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {
            **PATIENT_OPTIONS,
            "data_folder": str(patient_difficult_path),
            "other": {"group_by_file": False},
        }
        db_opts = {}
        ds.MAIN_MODULE(patient_options, db_opts)

        assert "grouped_fields" not in db_opts


def _run_other_main(db_opts: dict, patient_path) -> list:
    """Normalize *db_opts*, run the 'other' datasource over *patient_path*, return its signals."""
    normalize_database_options(db_opts)
    from clinical_scope.datasource.registry import DataSource

    ds = DataSource.get_subclass_by_name("other")
    return ds.MAIN_MODULE({**PATIENT_OPTIONS, "data_folder": str(patient_path)}, db_opts["other"])


def _run_other_with(db_opts: dict, patient_path) -> dict:
    """As :func:`_run_other_main`, but returning the ``other`` section the run populated."""
    _run_other_main(db_opts, patient_path)
    return db_opts["other"]


class TestLoopConfig:
    """Per-file loop definitions from other::filename are injected into database_options."""

    def test_per_file_loop_injected_with_prefix(self, patient_difficult_path):
        """Both the loop name and its signal references are scoped to the file."""

        section = _run_other_with(
            {
                "other::waves_first_half_filtered": {
                    "loop": {"HR vs SpO2": ["Solar8000/HR", "Solar8000/PLETH_SPO2"]}
                }
            },
            patient_difficult_path,
        )

        loop = section.get("loop", {})
        assert "waves_first_half_filtered::HR vs SpO2" in loop
        assert loop["waves_first_half_filtered::HR vs SpO2"] == [
            "waves_first_half_filtered::Solar8000/HR",
            "waves_first_half_filtered::Solar8000/PLETH_SPO2",
        ]

    def test_same_loop_name_in_two_files_does_not_collide(self, tmp_path):
        """Two files may each declare a loop called 'PV' without one erasing the other."""
        _write_other_patient(tmp_path, [("waves", ".parquet"), ("numerics", ".csv")])

        section = _run_other_with(
            {
                "other::waves": {"loop": {"PV": ["art", "paw"]}},
                "other::numerics": {"loop": {"PV": ["art", "paw"]}},
            },
            tmp_path,
        )

        assert section.get("loop", {}) == {
            "waves::PV": ["waves::art", "waves::paw"],
            "numerics::PV": ["numerics::art", "numerics::paw"],
        }

    def test_a_malformed_loop_does_not_cost_the_whole_file(self, tmp_path):
        """
        A bad loop entry is one skipped plot, not a skipped file.

        It used to be the file: scoping a per-file loop walked the config assuming a list, so
        a hand-written scalar raised inside the per-file try/except and took every signal in
        that file down with it. The walk is the plot type's own now, and it hands back a shape
        it does not recognise for assembly to report and skip.
        """
        _write_other_patient(tmp_path, [("waves", ".parquet")])

        section = _run_other_with(
            {"other::waves": {"loop": {"PV": "art"}}},
            tmp_path,
        )

        assert section.get("loop", {}) == {"waves::PV": "art"}
        assert section.get("grouped_fields", {}), "the file's signals still loaded"


class TestSpectrogramConfig:
    """Per-file spectrogram definitions from other::filename are injected into database_options."""

    def test_per_file_spectrogram_injected_with_prefix(self, patient_difficult_path):
        """The bare 'signal' name is prefixed with file_stem::, other keys pass through as-is."""

        section = _run_other_with(
            {
                "other::waves_first_half_filtered": {
                    "spectrogram": {
                        "HR spectrogram": {"signal": "Solar8000/HR", "freq_range": [0.5, 30.0]}
                    }
                }
            },
            patient_difficult_path,
        )

        spectrogram = section.get("spectrogram", {})
        assert spectrogram["waves_first_half_filtered::HR spectrogram"] == {
            "signal": "waves_first_half_filtered::Solar8000/HR",
            "freq_range": [0.5, 30.0],
        }


class TestPsdConfig:
    """Per-file psd definitions from other::filename are injected into database_options."""

    def test_per_file_psd_injected_with_prefix(self, patient_difficult_path):
        """A psd entry's signals are scoped to the file, in both dict and shorthand form."""

        section = _run_other_with(
            {
                "other::waves_first_half_filtered": {
                    "psd": {
                        "HR psd": {
                            "signals": [
                                "Solar8000/HR",
                                {"signal": "Solar8000/PLETH_SPO2", "label": "SpO2"},
                            ],
                            "freq_range": [0.5, 30.0],
                        }
                    }
                }
            },
            patient_difficult_path,
        )

        psd = section.get("psd", {})
        assert psd["waves_first_half_filtered::HR psd"] == {
            "signals": [
                "waves_first_half_filtered::Solar8000/HR",
                {"signal": "waves_first_half_filtered::Solar8000/PLETH_SPO2", "label": "SpO2"},
            ],
            "freq_range": [0.5, 30.0],
        }

    def test_psd_overlays_signals_from_two_different_files(self, tmp_path):
        """One PSD subplot may compare channels living in separate files under other/."""
        from clinical_scope.plot_types.psd.plot import build as build_psd_signals

        folder = tmp_path / "other"
        folder.mkdir(parents=True)
        index = pd.date_range("2004-09-15 08:00:00", periods=2560, freq="10ms")
        seconds = (index - index[0]).total_seconds().to_numpy()
        for stem, freq_hz in (("waves", 5.0), ("numerics", 12.0)):
            pd.DataFrame(
                {"signal": np.sin(2 * np.pi * freq_hz * seconds)},
                index=pd.DatetimeIndex(index, name="datetime_index"),
            ).to_parquet(folder / f"{stem}.parquet")

        db_opts = {"other": {}}
        signals = _run_other_main(db_opts, tmp_path)

        psd_signals = build_psd_signals(
            signals,
            "cross-file",
            {"signals": ["waves::signal", "numerics::signal"], "freq_range": [1.0, 20.0]},
        )

        assert [signal.raw_name for signal in psd_signals] == [
            "cross-file::waves::signal",
            "cross-file::numerics::signal",
        ]


class TestPerFilePatientOptions:
    """Standalone ``other::<stem>`` blocks in patient_options scope time_shift/group_by_file."""

    # The two files in Patient_difficult_format/other/ that survive datetime detection.
    PER_FILE = "waves_first_half_filtered"
    SIBLING = "waves_naive_index_filtered"

    def _run_main(self, patient_difficult_path, patient_options_extra, db_opts=None):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {
            **PATIENT_OPTIONS,
            "data_folder": str(patient_difficult_path),
            **patient_options_extra,
        }
        db_opts = {} if db_opts is None else db_opts
        return ds.MAIN_MODULE(patient_options, db_opts), db_opts

    def _first_timestamp(self, signals, file_stem):
        file_signals = [s for s in signals if s.raw_name.startswith(f"{file_stem}::")]
        assert file_signals, f"no signals loaded for {file_stem}"
        return file_signals[0].data.x[0]

    def test_per_file_group_by_file_overrides_generic(self, patient_difficult_path):
        """A per-file block wins over the generic 'other' one for the file it names."""
        _, db_opts = self._run_main(
            patient_difficult_path,
            {
                "other": {"group_by_file": True},
                f"other::{self.PER_FILE}": {"group_by_file": False},
            },
        )
        groups = db_opts.get("grouped_fields", {})
        assert self.PER_FILE not in groups
        assert self.SIBLING in groups

    def test_undeclared_file_inherits_generic_block(self, patient_difficult_path):
        """A file with no other::<stem> entry keeps using the shared 'other' options."""
        _, db_opts = self._run_main(
            patient_difficult_path,
            {
                "other": {"group_by_file": False},
                f"other::{self.PER_FILE}": {"group_by_file": True},
            },
        )
        groups = db_opts.get("grouped_fields", {})
        assert self.PER_FILE in groups
        assert self.SIBLING not in groups

    def test_per_file_time_shift_leaves_sibling_untouched(self, patient_difficult_path):
        """time_shift applies to the named file only — the whole point of per-file scoping."""
        import pandas as pd

        baseline, _ = self._run_main(patient_difficult_path, {})
        shifted, _ = self._run_main(
            patient_difficult_path, {f"other::{self.PER_FILE}": {"time_shift": 3600.0}}
        )

        delta = self._first_timestamp(shifted, self.PER_FILE) - self._first_timestamp(
            baseline, self.PER_FILE
        )
        assert delta == pd.Timedelta(hours=1)
        assert self._first_timestamp(shifted, self.SIBLING) == self._first_timestamp(
            baseline, self.SIBLING
        )

    def test_partial_per_file_block_falls_back_per_field(self, patient_difficult_path):
        """A per-file block naming only time_shift still inherits generic group_by_file."""
        _, db_opts = self._run_main(
            patient_difficult_path,
            {
                "other": {"group_by_file": False},
                f"other::{self.PER_FILE}": {"time_shift": 60.0},
            },
        )
        assert "grouped_fields" not in db_opts


class TestNormalizeDatabaseOptions:
    """Unit tests for database_options_parser.normalize_database_options()."""

    def test_injects_files_key(self):

        db = {"other::my_file": {"signals": {"col": {"label": "Col"}}}}
        normalize_database_options(db)
        assert "other" in db
        assert "files" in db["other"]
        assert "my_file" in db["other"]["files"]

    def test_creates_bare_other_section_if_missing(self):

        db = {"other::only_file": {}}
        normalize_database_options(db)
        assert db.get("other") == {"files": {"only_file": {}}}

    def test_merges_with_existing_other_section(self):

        db = {
            "other": {"field_display": ["only_file::col"]},
            "other::only_file": {"signals": {"col": {"label": "Col"}}},
        }
        normalize_database_options(db)
        assert "field_display" in db["other"]  # existing key preserved
        assert db["other"]["files"]["only_file"]["signals"]["col"]["label"] == "Col"

    def test_noop_when_no_per_file_keys(self):

        db = {"other": {"signals": {}}, "servo_u": {}}
        original = dict(db)
        normalize_database_options(db)
        assert db == original

    def test_source_keys_are_moved_not_copied(self):

        db = {"other::my_file": {"signals": {}}}
        normalize_database_options(db)
        assert "other::my_file" not in db
        assert "my_file" in db["other"]["files"]

    def test_is_idempotent(self):

        db = {"other::my_file": {"signals": {"col": {"label": "Col"}}}}
        normalize_database_options(db)
        once = copy.deepcopy(db)
        normalize_database_options(db)
        assert db == once

    def test_each_per_file_issue_is_reported_once(self):
        """Both spellings surviving normalization made every other:: issue log twice."""
        db = {"other::my_file": {"not_a_real_key": {}}}
        normalize_database_options(db)
        paths = [issue.path for issue in validate_database_options(db)]
        assert len(paths) == len(set(paths))


class TestTimezone:
    """Timezone is applied via additional_informations.timezone in database_options."""

    def _run_main(self, patient_difficult_path, db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        return ds.MAIN_MODULE(patient_options, db_opts)

    def test_tz_aware_parquet_timezone_is_preserved(self, patient_difficult_path):
        """Timezone already embedded in a parquet file is preserved through the pipeline."""
        # The test parquet file stores Europe/Paris timestamps — they must not be stripped.
        signals = self._run_main(patient_difficult_path, {})
        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        assert len(file_signals) > 0
        for sig in file_signals:
            assert str(sig.data.timezone) == "Europe/Paris"


def _write_other_patient(root, stems_with_suffixes):
    """Build a throwaway patient folder whose other/ holds one file per (stem, suffix)."""
    folder = root / "other"
    folder.mkdir(parents=True, exist_ok=True)
    index = pd.date_range("2004-09-15 08:00:00", periods=10, freq="1s", name="datetime_index")
    for stem, suffix in stems_with_suffixes:
        df = pd.DataFrame({"art": range(10), "paw": range(10, 20)}, index=index)
        if suffix == ".parquet":
            df.to_parquet(folder / f"{stem}{suffix}")
        else:
            df.to_csv(folder / f"{stem}{suffix}")
    return folder


class TestStemDeduplication:
    """A folder holding both extensions for one stem must not load the file twice."""

    def test_parquet_shadows_csv_of_the_same_stem(self, tmp_path, other_cls):
        _write_other_patient(tmp_path, [("waves", ".parquet"), ("waves", ".csv")])
        found = other_cls._find(other_cls._find_folder(tmp_path))
        assert [path.name for path in found] == ["waves.parquet"]

    def test_distinct_stems_are_all_kept(self, tmp_path, other_cls):
        _write_other_patient(tmp_path, [("waves", ".parquet"), ("numerics", ".csv")])
        found = other_cls._find(other_cls._find_folder(tmp_path))
        assert sorted(path.name for path in found) == ["numerics.csv", "waves.parquet"]

    def test_signals_are_not_duplicated(self, tmp_path, other_cls):
        _write_other_patient(tmp_path, [("waves", ".parquet"), ("waves", ".csv")])
        signals = other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, {})
        raw_names = [sig.raw_name for sig in signals]
        assert sorted(raw_names) == ["waves::art", "waves::paw"]


class TestPerFileTraceOptions:
    """A trace_options block in an other::<stem> section overrides the datasource default."""

    def _signals(self, tmp_path, other_cls, db_opts):
        _write_other_patient(tmp_path, [("waves", ".parquet")])
        return other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, db_opts)

    def test_default_mode_without_config(self, tmp_path, other_cls):
        signals = self._signals(tmp_path, other_cls, {})
        assert all(sig.trace.mode == "lines" for sig in signals)

    def test_per_file_mode_overrides_the_default(self, tmp_path, other_cls):
        db_opts = {"files": {"waves": {"trace_options": {"mode": "lines+markers"}}}}
        signals = self._signals(tmp_path, other_cls, db_opts)
        assert signals
        assert all(sig.trace.mode == "lines+markers" for sig in signals)

    def test_unset_keys_keep_the_datasource_value(self, tmp_path, other_cls):
        """Merging, not replacing: line_width survives an override that only sets mode."""
        db_opts = {"files": {"waves": {"trace_options": {"mode": "lines+markers"}}}}
        signals = self._signals(tmp_path, other_cls, db_opts)
        assert all(sig.trace.line.width == 1.5 for sig in signals)

    def test_a_files_options_do_not_leak_to_its_neighbours(self, tmp_path, other_cls):
        _write_other_patient(tmp_path, [("waves", ".parquet"), ("numerics", ".parquet")])
        db_opts = {"files": {"waves": {"trace_options": {"mode": "lines+markers"}}}}
        signals = other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, db_opts)
        modes = {sig.raw_name.split("::")[0]: sig.trace.mode for sig in signals}
        assert modes["waves"] == "lines+markers"
        assert modes["numerics"] == "lines"


class TestSourceSymlink:
    """'other' writes no parquet cache, so a symlink is the output folder's only provenance."""

    def test_each_loaded_file_is_symlinked(self, tmp_path, other_cls):
        source_folder = _write_other_patient(
            tmp_path, [("waves", ".parquet"), ("numerics", ".csv")]
        )
        other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, {})

        symlink_folder = tmp_path / cst.FOLDER_NAME_OUTPUT / "other"
        for name in ("waves.parquet", "numerics.csv"):
            link = symlink_folder / name
            assert link.is_symlink()
            assert link.resolve() == (source_folder / name).resolve()

    def test_symlink_is_relative_so_the_folder_stays_movable(self, tmp_path, other_cls):
        _write_other_patient(tmp_path, [("waves", ".parquet")])
        other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, {})
        link = tmp_path / cst.FOLDER_NAME_OUTPUT / "other" / "waves.parquet"
        assert not Path(os.readlink(link)).is_absolute()

    def test_symlink_cannot_collide_with_another_datasource_cache(self, tmp_path, other_cls):
        """An 'other' file named like a cache must not land on that cache's path."""
        _write_other_patient(tmp_path, [("servo_u_loaded", ".parquet")])
        output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
        output_folder.mkdir(parents=True, exist_ok=True)
        cache = output_folder / "servo_u_loaded.parquet"
        cache.write_bytes(b"servo_u cache")

        other_cls.main({**PATIENT_OPTIONS, "data_folder": str(tmp_path)}, {})

        assert cache.read_bytes() == b"servo_u cache"
        assert (output_folder / "other" / "servo_u_loaded.parquet").is_symlink()
