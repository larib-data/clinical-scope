"""
Tests for ``deduplicate_then_sort_index`` (issue #57): the ``other`` datasource's
dedup-*then*-sort order, which keeps the first row in *file* order on a timestamp
collision (a non-stable ``sort_index`` would otherwise decide arbitrarily), plus the
copy-skipping when the index is already unique / already sorted.
"""

import numpy as np
import pandas as pd

from clinical_scope.io.file_utils import deduplicate_then_sort_index


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
