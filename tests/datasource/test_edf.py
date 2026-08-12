"""Tests for edf datasource — multi-file EDF/EDF+ binary format."""

import datetime

import numpy as np
import pandas as pd
import pyedflib
import pytest

from clinical_scope.datasource.sources.edf.find_load_format import _unique_labels, read_edf_file


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, edf_cls):
    folder = edf_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("edf folder not found in demo_patient")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, edf_cls):
    file_path = edf_cls._find(ds_folder)
    assert file_path is not None
    return edf_cls._load(file_path, None)


def _write_edf(path, start_datetime, sample_rate=4, seconds=2, labels=("chan A", "chan B")):
    """Write a minimal EDF+ file — used to exercise header cases the demo file doesn't cover."""
    headers = [
        {
            "label": label,
            "dimension": "uV",
            "sample_frequency": sample_rate,
            "physical_min": -100.0,
            "physical_max": 100.0,
            "digital_min": -32768,
            "digital_max": 32767,
            "transducer": "",
            "prefilter": "",
        }
        for label in labels
    ]
    writer = pyedflib.EdfWriter(str(path), len(headers), file_type=pyedflib.FILETYPE_EDFPLUS)
    writer.setSignalHeaders(headers)
    writer.setStartdatetime(start_datetime)
    writer.writeSamples([np.zeros(sample_rate * seconds) for _ in headers])
    writer.close()
    return path


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_list(self, ds_folder, edf_cls):
        """edf is MULTI_FILE — _find() should return a list."""
        result = edf_cls._find(ds_folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extension(self, ds_folder, edf_cls):
        result = edf_cls._find(ds_folder)
        for p in result:
            assert p.suffix == ".edf"


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_datetime_index(self, loaded_df):
        assert isinstance(loaded_df.index, pd.DatetimeIndex)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0

    def test_load_has_columns(self, loaded_df):
        assert len(loaded_df.columns) >= 1

    def test_load_sorted_index(self, loaded_df):
        assert loaded_df.index.is_monotonic_increasing

    def test_load_unique_index(self, loaded_df):
        assert loaded_df.index.is_unique

    def test_load_index_is_naive(self, loaded_df):
        """_load leaves the timezone to _format, like every other source."""
        assert loaded_df.index.tz is None

    def test_load_columns_are_channel_labels(self, loaded_df):
        assert list(loaded_df.columns) == ["chan 1", "chan 2", "chan 3"]

    def test_load_columns_are_numeric(self, loaded_df):
        assert all(pd.api.types.is_numeric_dtype(loaded_df[c]) for c in loaded_df.columns)

    def test_load_concatenates_both_files(self, loaded_df):
        """Two contiguous 60 s files at 128 Hz."""
        assert len(loaded_df) == 15360

    def test_load_sample_cadence(self, loaded_df):
        """128 Hz -> 7.8125 ms between samples."""
        step = loaded_df.index[1] - loaded_df.index[0]
        assert step == pd.Timedelta(seconds=1 / 128)


class TestReadSingleFile:
    def test_annotation_channel_is_not_a_signal(self, ds_folder):
        """'EDF Annotations' is EDF+ bookkeeping, never a column."""
        df = read_edf_file(sorted(ds_folder.glob("*.edf"))[0])
        assert "EDF Annotations" not in df.columns

    def test_mixed_sample_rates_share_one_index(self, tmp_path):
        """A slower channel is padded with NaN on the union index, not resampled."""
        path = tmp_path / "mixed.edf"
        headers = []
        for label, rate in (("fast", 8), ("slow", 2)):
            headers.append(
                {
                    "label": label,
                    "dimension": "uV",
                    "sample_frequency": rate,
                    "physical_min": -100.0,
                    "physical_max": 100.0,
                    "digital_min": -32768,
                    "digital_max": 32767,
                    "transducer": "",
                    "prefilter": "",
                }
            )
        writer = pyedflib.EdfWriter(str(path), 2, file_type=pyedflib.FILETYPE_EDFPLUS)
        writer.setSignalHeaders(headers)
        writer.setStartdatetime(datetime.datetime(2024, 5, 4, 12, 0, 0))  # noqa: DTZ001
        writer.writeSamples([np.ones(16), np.ones(4)])
        writer.close()

        df = read_edf_file(path)
        assert len(df) == 16
        assert df["fast"].notna().sum() == 16
        assert df["slow"].notna().sum() == 4


class TestUniqueLabels:
    def test_distinct_labels_untouched(self):
        assert _unique_labels(["Fp1", "F7"]) == ["Fp1", "F7"]

    def test_repeated_labels_get_suffixed(self):
        assert _unique_labels(["EEG", "EEG", "EEG"]) == ["EEG", "EEG_2", "EEG_3"]


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, edf_cls):
    return edf_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None

    def test_format_anchors_demo_file_to_recording_start(self, formatted_df):
        """The demo files are undated; patient_options_full places them on the demo's own day."""
        first = formatted_df.index[0].tz_convert("Europe/Paris")
        assert first == pd.Timestamp("2004-09-15 08:12:33", tz="Europe/Paris")


class TestUndatedRecording:
    """EDF+ writes 01.01.85 when the start date is unknown — `recording_start` places it."""

    @pytest.fixture
    def undated_df(self, tmp_path, edf_cls):
        path = _write_edf(tmp_path / "undated.edf", datetime.datetime(1985, 1, 1, 9, 30))  # noqa: DTZ001
        return edf_cls._load([path], None)

    @staticmethod
    def _first(df, edf_cls, recording_start=None):
        specific = {"recording_start": recording_start} if recording_start else {}
        formatted = edf_cls._format(df, {"data_folder": "", "edf": specific}, {})
        return formatted.index[0].tz_convert("Europe/Paris")

    def test_loads_on_the_sentinel_date(self, undated_df):
        assert undated_df.index[0] == pd.Timestamp("1985-01-01 09:30:00")

    def test_date_only_keeps_the_files_time_of_day(self, undated_df, edf_cls):
        """Only the date was scrubbed — the header's 09:30 must survive."""
        assert self._first(undated_df, edf_cls, "2024-05-04") == pd.Timestamp(
            "2024-05-04 09:30:00", tz="Europe/Paris"
        )

    def test_full_timestamp_places_the_first_sample(self, undated_df, edf_cls):
        """Date and time both scrubbed — the typed instant wins over the header's."""
        assert self._first(undated_df, edf_cls, "2024-05-04 22:15:00") == pd.Timestamp(
            "2024-05-04 22:15:00", tz="Europe/Paris"
        )

    def test_without_recording_start_the_sentinel_date_is_kept(self, undated_df, edf_cls):
        assert self._first(undated_df, edf_cls).date() == datetime.date(1985, 1, 1)

    def test_an_already_parsed_date_still_keeps_the_files_time_of_day(self, undated_df, edf_cls):
        """A Timestamp reads as date-only, like the equivalent string: 09:30 must survive."""
        assert self._first(undated_df, edf_cls, pd.Timestamp("2024-05-04")) == pd.Timestamp(
            "2024-05-04 09:30:00", tz="Europe/Paris"
        )

    def test_epoch_start_is_treated_as_undated(self, tmp_path, edf_cls):
        path = _write_edf(tmp_path / "epoch.edf", datetime.datetime(1970, 1, 1, 0, 0))  # noqa: DTZ001
        df = edf_cls._load([path], None)
        assert self._first(df, edf_cls, "2024-05-04 22:15:00") == pd.Timestamp(
            "2024-05-04 22:15:00", tz="Europe/Paris"
        )

    def test_multi_file_spacing_survives_anchoring(self, tmp_path, edf_cls):
        """Anchoring shifts the whole recording, it does not collapse the gap between files."""
        _write_edf(tmp_path / "a.edf", datetime.datetime(1985, 1, 1, 0, 0), seconds=2)  # noqa: DTZ001
        _write_edf(tmp_path / "b.edf", datetime.datetime(1985, 1, 1, 0, 1), seconds=2)  # noqa: DTZ001
        df = edf_cls._load(sorted(tmp_path.glob("*.edf")), None)
        formatted = edf_cls._format(
            df, {"data_folder": "", "edf": {"recording_start": "2024-05-04 10:00:00"}}, {}
        )
        assert formatted.index[-1] - formatted.index[0] == pd.Timedelta(seconds=61.75)


class TestDatedRecording:
    """A file that states its own date keeps it — `recording_start` only fills a gap."""

    @pytest.fixture
    def dated_df(self, tmp_path, edf_cls):
        path = _write_edf(tmp_path / "dated.edf", datetime.datetime(2024, 3, 1, 7, 0))  # noqa: DTZ001
        return edf_cls._load([path], None)

    def test_recording_start_is_ignored(self, dated_df, edf_cls):
        patient_options = {"data_folder": "", "edf": {"recording_start": "2024-05-04 22:15:00"}}
        formatted = edf_cls._format(dated_df, patient_options, {})
        assert formatted.index[0].tz_convert("Europe/Paris") == pd.Timestamp(
            "2024-03-01 07:00:00", tz="Europe/Paris"
        )


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "edf"

    def test_loaded_snapshot(self, loaded_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            loaded_df, SNAPSHOT_DIR / self._DS / "loaded.parquet", update=update_snapshots
        )

    def test_formatted_snapshot(self, formatted_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            formatted_df, SNAPSHOT_DIR / self._DS / "formatted.parquet", update=update_snapshots
        )
