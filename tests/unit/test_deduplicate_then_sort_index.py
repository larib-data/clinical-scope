"""
Tests for ``deduplicate_then_sort_index`` (issue #57): the ``other`` datasource's
dedup-*then*-sort order, which keeps the first row in *file* order on a timestamp
collision (a non-stable ``sort_index`` would otherwise decide arbitrarily), plus the
copy-skipping when the index is already unique / already sorted.

Also covers the warning a drop emits, including the per-file context ``other`` threads
into it: discarding rows in silence was this function's failure mode until it spoke up.
"""

import logging

import numpy as np
import pandas as pd

from clinical_scope.datasource.sources.other.find_load_format import OtherDataSource
from clinical_scope.io.time_axis import deduplicate_then_sort_index


def test_already_sorted_and_unique_is_returned_without_copying():
    idx = pd.date_range("2024-01-01", periods=5, freq="1s", tz="UTC")
    df = pd.DataFrame({"col": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)

    result = deduplicate_then_sort_index(df)

    pd.testing.assert_frame_equal(result, df)
    assert np.shares_memory(result["col"].to_numpy(), df["col"].to_numpy())


def test_unsorted_index_is_sorted():
    idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"]).tz_localize("UTC")
    df = pd.DataFrame({"col": [3.0, 1.0, 2.0]}, index=idx)

    result = deduplicate_then_sort_index(df)

    assert list(result.index) == sorted(df.index)
    assert list(result["col"]) == [1.0, 2.0, 3.0]


def test_duplicate_index_keeps_first_in_file_order_not_sorted_order():
    # The two 08:00:01 rows are non-adjacent in file order ("a" then "c"). Deduplicating
    # first commits to "a" (file-order-first) *before* sorting can shuffle the collision —
    # this is the semantic sort-then-dedup would not guarantee.
    idx = pd.to_datetime(
        ["2024-01-01 08:00:01", "2024-01-01 08:00:02", "2024-01-01 08:00:01"]
    ).tz_localize("UTC")
    df = pd.DataFrame({"col": ["a", "b", "c"]}, index=idx)

    result = deduplicate_then_sort_index(df)

    assert list(result.index) == sorted(set(df.index))
    assert list(result["col"]) == ["a", "b"]


TIME_AXIS_LOGGER = "clinical_scope.io.time_axis"


def _time_axis_warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == TIME_AXIS_LOGGER and record.levelno == logging.WARNING
    ]


def test_dropped_rows_are_warned_about_once_with_the_dropped_and_total_counts(caplog):
    # 8 rows over 3 distinct stamps (4 + 3 + 1). Dropped (5), kept (3) and the number of
    # stamps that collided (2) are all different numbers, so "5 of 8" can only be the
    # dropped-of-total pair -- not a kept count and not a count of colliding stamps.
    idx = pd.to_datetime(
        [
            "2024-01-01 08:00:00",
            "2024-01-01 08:00:00",
            "2024-01-01 08:00:00",
            "2024-01-01 08:00:00",
            "2024-01-01 08:00:01",
            "2024-01-01 08:00:01",
            "2024-01-01 08:00:01",
            "2024-01-01 08:00:02",
        ]
    ).tz_localize("UTC")
    df = pd.DataFrame({"col": range(8)}, index=idx)

    with caplog.at_level(logging.WARNING):
        result = deduplicate_then_sort_index(df)

    # The survivors are the first row of each stamp group, not the rows that had no twin.
    assert list(result["col"]) == [0, 4, 7]
    messages = _time_axis_warnings(caplog)
    assert len(messages) == 1
    assert "5 of 8" in messages[0]
    # For a log line the prose is the whole contract -- there is no return value or state
    # to check it against. "Kept 5 of 8" carries the same digits and the opposite meaning,
    # and "the rows that had duplicate twins" names the wrong survivors. Pin those two
    # load-bearing words; the phrasing around them stays free to change.
    assert "drop" in messages[0].lower()
    assert "first" in messages[0].lower()
    # No context was given, so the message must not trail an empty source clause.
    assert " from " not in messages[0]


def test_no_duplicates_emits_no_warning(caplog):
    idx = pd.to_datetime(["2024-01-01 08:00:02", "2024-01-01 08:00:00"]).tz_localize("UTC")
    df = pd.DataFrame({"col": [2.0, 0.0]}, index=idx)

    with caplog.at_level(logging.WARNING):
        deduplicate_then_sort_index(df)

    assert _time_axis_warnings(caplog) == []


def test_context_is_named_in_the_warning(caplog):
    idx = pd.to_datetime(["2024-01-01 08:00:00", "2024-01-01 08:00:00"]).tz_localize("UTC")
    df = pd.DataFrame({"col": [0.0, 1.0]}, index=idx)

    with caplog.at_level(logging.WARNING):
        deduplicate_then_sort_index(df, context="waves.csv")

    assert "waves.csv" in _time_axis_warnings(caplog)[0]


def _write_other_patient_with_colliding_timestamps(root) -> None:
    """A patient folder whose other/waves.csv holds 6 rows over 2 timestamps."""
    folder = root / "other"
    folder.mkdir(parents=True, exist_ok=True)
    stamps = ["2024-01-01 08:00:00"] * 3 + ["2024-01-01 08:00:01"] * 3
    pd.DataFrame({"datetime": stamps, "art": range(6)}).to_csv(folder / "waves.csv", index=False)


def test_main_names_the_file_whose_rows_were_dropped(tmp_path, caplog):
    _write_other_patient_with_colliding_timestamps(tmp_path)
    patient_options = {
        "data_folder": str(tmp_path),
        "datetime_start": None,
        "datetime_end": None,
        "quick_load": False,
    }

    with caplog.at_level(logging.WARNING):
        OtherDataSource.main(patient_options, {})

    messages = _time_axis_warnings(caplog)
    assert len(messages) == 1
    assert "4 of 6" in messages[0]
    assert "waves.csv" in messages[0]


def test_inspect_names_the_file_whose_rows_were_dropped(tmp_path, caplog):
    _write_other_patient_with_colliding_timestamps(tmp_path)
    patient_options = {
        "data_folder": str(tmp_path),
        "datetime_start": None,
        "datetime_end": None,
        "quick_load": False,
    }

    with caplog.at_level(logging.WARNING):
        OtherDataSource.inspect(patient_options, {})

    messages = _time_axis_warnings(caplog)
    assert len(messages) == 1
    assert "4 of 6" in messages[0]
    assert "waves.csv" in messages[0]
