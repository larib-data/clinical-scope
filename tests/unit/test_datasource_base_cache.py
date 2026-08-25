"""
Regression tests for the parquet cache behaviour of ``DataSourceBase._load_raw_dataframe``.

Locks in the 2x2 truth table from issue #40:

+---------------------+---------------+--------------------+
| ``quick_load``      | cache exists? | expected behaviour |
+=====================+===============+====================+
| ticked   (True)     | no            | fresh load + write |
| unticked (False)    | no            | fresh load + write |
| ticked   (True)     | yes           | re-use cache       |
| unticked (False)    | yes           | fresh load + write |
+---------------------+---------------+--------------------+

The tests assert observable outcomes only — the DataFrame the caller receives, and
whether the parquet on disk has been written/overwritten — never internal call counts.
That way the tests survive refactors of *how* the cache decision is implemented as
long as the user-visible contract holds.
"""

from pathlib import Path

import pandas as pd
import pytest

import clinical_scope.constants as cst
from clinical_scope.datasource.base import DataSourceBase


def _df_v1() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC")
    return pd.DataFrame({"col": [1.0, 2.0]}, index=idx)


def _df_v2() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC")
    return pd.DataFrame({"col": [10.0, 20.0]}, index=idx)


def _make_fake_source(
    fresh_df: pd.DataFrame,
    *,
    allow_quick_load: bool = True,
    create_source_symlink: bool = False,
    source_file: Path | None = None,
) -> type:
    """
    Build a fresh ``DataSourceBase`` subclass per test.

    Each test gets its own class — no shared mutable state, no reset fixture needed.
    The fake's ``_load`` only returns a frame, like every real datasource: writing the
    parquet cache is the base class's job, and that is precisely what these tests exercise.
    """
    _source_file = source_file

    class _FakeSource(DataSourceBase):
        DATASOURCE_NAME = "fake_source"
        FILE_NAME_DATAFRAME_LOADED = "fake_source.parquet"
        ALLOW_QUICK_LOAD = allow_quick_load
        CREATE_SOURCE_SYMLINK = create_source_symlink

        @classmethod
        def _find_folder(cls, folder_path: Path) -> Path:  # noqa: ARG003
            return folder_path

        @classmethod
        def _find(cls, folder_path: Path) -> Path:
            return _source_file if _source_file is not None else folder_path / "raw_data.bin"

        @classmethod
        def _load(cls, file_path):  # noqa: ARG003
            return fresh_df

    return _FakeSource


def _patient_options(folder: Path, *, quick_load: bool) -> dict:
    return {
        cst.PatientOptions.PathDataFolder.NAME: str(folder),
        cst.PatientOptions.QuickLoad.NAME: quick_load,
    }


@pytest.fixture
def patient_folder(tmp_path: Path) -> Path:
    (tmp_path / cst.FOLDER_NAME_OUTPUT).mkdir()
    return tmp_path


# ---------------------------------------------------------------------------------------------------
# The 2x2 acceptance truth table from issue #40
# ---------------------------------------------------------------------------------------------------
# Each row encodes one cell:
#   - quick_load        : user toggle ("re-use data if already loaded once")
#   - cache_seed        : v1 if a stale parquet pre-exists on disk, None otherwise
#   - fresh_data        : what _load() would return if it actually runs (v1 or v2)
#   - expected_returned : what the caller should receive
#   - expected_on_disk  : what the parquet file should hold afterwards
#
# The (cache_seed, fresh_data) split lets cells 3 and 4 distinguish "cache wins" from
# "fresh wins" by looking at which version was returned/persisted.
@pytest.mark.parametrize(
    ("quick_load", "cache_seed", "fresh_data", "expected_returned", "expected_on_disk"),
    [
        (True,  None, _df_v1(), _df_v1(), _df_v1()),
        (False, None, _df_v1(), _df_v1(), _df_v1()),
        (True,  _df_v1(), _df_v2(), _df_v1(), _df_v1()),  # cache wins, disk untouched
        (False, _df_v1(), _df_v2(), _df_v2(), _df_v2()),  # bug from #40: fresh must overwrite
    ],
    ids=[
        "ticked_no_cache",
        "unticked_no_cache",
        "ticked_with_cache_reuses",
        "unticked_with_cache_overwrites",
    ],
)
def test_quick_load_truth_table(
    patient_folder: Path,
    quick_load: bool,
    cache_seed: pd.DataFrame | None,
    fresh_data: pd.DataFrame,
    expected_returned: pd.DataFrame,
    expected_on_disk: pd.DataFrame,
) -> None:
    cache_path = patient_folder / cst.FOLDER_NAME_OUTPUT / "fake_source.parquet"
    if cache_seed is not None:
        cache_seed.to_parquet(cache_path)

    source = _make_fake_source(fresh_data)
    df, _, _ = source._load_raw_dataframe(
        _patient_options(patient_folder, quick_load=quick_load), database_options={}
    )

    pd.testing.assert_frame_equal(df, expected_returned, check_freq=False)
    assert cache_path.is_file(), "parquet cache must always exist after a successful run"
    pd.testing.assert_frame_equal(
        pd.read_parquet(cache_path),
        expected_on_disk,
        check_freq=False,
        obj="parquet on disk did not match the expected post-condition",
    )


# ---------------------------------------------------------------------------------------------------
# The base class owns the write: `_load` transcribes and saves nothing itself (ADR-0010)
# ---------------------------------------------------------------------------------------------------
def test_base_writes_the_cache_a_load_never_saves(patient_folder: Path) -> None:
    """A `_load` that only returns a frame still leaves a readable cache behind."""
    source = _make_fake_source(_df_v1())
    cache_path = patient_folder / cst.FOLDER_NAME_OUTPUT / "fake_source.parquet"

    df, _, _ = source._load_raw_dataframe(
        _patient_options(patient_folder, quick_load=False), database_options={}
    )

    pd.testing.assert_frame_equal(df, _df_v1(), check_freq=False)
    assert cache_path.is_file(), "the base class must write the cache for a saving-free _load"
    pd.testing.assert_frame_equal(pd.read_parquet(cache_path), _df_v1(), check_freq=False)


def test_empty_frame_writes_neither_cache_nor_output_folder(tmp_path: Path) -> None:
    """An empty frame is not worth a cache — nor the output folder it would be written into."""
    empty = pd.DataFrame({"col": []}, index=pd.DatetimeIndex([], tz="UTC"))
    source = _make_fake_source(empty)
    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT

    df, _, _ = source._load_raw_dataframe(
        _patient_options(tmp_path, quick_load=False), database_options={}
    )

    assert df.empty
    assert not output_folder.exists(), "an empty frame must not even create the output folder"


# ---------------------------------------------------------------------------------------------------
# Sanity: a datasource that opts out of caching must never produce a parquet, even when ticked
# ---------------------------------------------------------------------------------------------------
def test_allow_quick_load_false_never_writes_cache(patient_folder: Path) -> None:
    source = _make_fake_source(_df_v1(), allow_quick_load=False)
    cache_path = patient_folder / cst.FOLDER_NAME_OUTPUT / "fake_source.parquet"

    df, _, _ = source._load_raw_dataframe(
        _patient_options(patient_folder, quick_load=True), database_options={}
    )

    pd.testing.assert_frame_equal(df, _df_v1(), check_freq=False)
    assert not cache_path.exists(), (
        "ALLOW_QUICK_LOAD=False is the per-datasource opt-out; no parquet should ever appear"
    )


# ---------------------------------------------------------------------------------------------------
# Symlink behaviour: CREATE_SOURCE_SYMLINK=True creates a relative symlink in the output folder
# ---------------------------------------------------------------------------------------------------
def test_create_source_symlink_creates_symlink(tmp_path: Path) -> None:
    """A non-caching datasource with CREATE_SOURCE_SYMLINK=True must leave a symlink."""
    source_file = tmp_path / "raw_data.parquet"
    _df_v1().to_parquet(source_file)

    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
    output_folder.mkdir()

    source = _make_fake_source(
        _df_v1(),
        allow_quick_load=False,
        create_source_symlink=True,
        source_file=source_file,
    )
    source._load_raw_dataframe(_patient_options(tmp_path, quick_load=False), database_options={})

    symlink_path = output_folder / "fake_source" / source_file.name
    assert symlink_path.is_symlink(), "output folder must contain a symlink to the source file"
    assert symlink_path.resolve() == source_file.resolve(), "symlink must resolve to source file"


def test_symlink_never_replaces_a_file_it_did_not_create(tmp_path: Path) -> None:
    """A real file at the symlink path is left alone: provenance is not worth destroying data."""
    source_file = tmp_path / "raw_data.parquet"
    _df_v1().to_parquet(source_file)

    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
    occupied = output_folder / "fake_source" / "raw_data.parquet"
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"precious")

    source = _make_fake_source(
        _df_v1(),
        allow_quick_load=False,
        create_source_symlink=True,
        source_file=source_file,
    )
    source._load_raw_dataframe(_patient_options(tmp_path, quick_load=False), database_options={})

    assert occupied.read_bytes() == b"precious", "an existing real file must survive untouched"
    assert not occupied.is_symlink()


def test_symlinks_are_namespaced_per_datasource(tmp_path: Path) -> None:
    """A source file sharing a name with another datasource's cache must not reach the root."""
    source_file = tmp_path / "servo_u_loaded.parquet"
    _df_v1().to_parquet(source_file)

    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
    output_folder.mkdir()
    other_cache = output_folder / "servo_u_loaded.parquet"
    other_cache.write_bytes(b"servo_u cache")

    source = _make_fake_source(
        _df_v1(),
        allow_quick_load=False,
        create_source_symlink=True,
        source_file=source_file,
    )
    source._load_raw_dataframe(_patient_options(tmp_path, quick_load=False), database_options={})

    assert other_cache.read_bytes() == b"servo_u cache", "another datasource's cache must survive"
    assert (output_folder / "fake_source" / "servo_u_loaded.parquet").is_symlink()


def test_create_source_symlink_false_leaves_no_symlink(tmp_path: Path) -> None:
    """Default CREATE_SOURCE_SYMLINK=False must not create any symlink even when caching is off."""
    source_file = tmp_path / "raw_data.parquet"
    _df_v1().to_parquet(source_file)

    output_folder = tmp_path / cst.FOLDER_NAME_OUTPUT
    output_folder.mkdir()

    source = _make_fake_source(
        _df_v1(),
        allow_quick_load=False,
        create_source_symlink=False,
        source_file=source_file,
    )
    source._load_raw_dataframe(_patient_options(tmp_path, quick_load=False), database_options={})

    assert not any(p.is_symlink() for p in output_folder.iterdir()), (
        "no symlink should appear when CREATE_SOURCE_SYMLINK is False"
    )
