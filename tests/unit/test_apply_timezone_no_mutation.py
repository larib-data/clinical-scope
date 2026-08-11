"""
Regression test: ``apply_timezone_to_dataframe`` must localize onto a copy, never mutate
the caller's DataFrame in place.

``df.index = df.index.tz_localize(...)`` rebinds the index *on the passed object*. The
``_format`` overrides that don't copy first (servo_u, servo_u, eit) hand
their caller's DataFrame straight in, so an in-place localize would tz-shift the original —
e.g. polluting a module-scoped ``loaded_df`` test fixture and making a "loaded" snapshot
pass only depending on whether a ``_format`` call ran earlier in the session.

A tz-*naive* input is essential here: a tz-aware input hits the early return and never
reaches the localizing branch, which is exactly why this slipped through before.
"""

import pandas as pd

from clinical_scope.datasource.formatting.timezone import apply_timezone_to_dataframe


def test_apply_timezone_localizes_without_mutating_the_caller_index():
    idx = pd.DatetimeIndex(["2024-01-01 00:00:00", "2024-01-01 00:00:01"], name="datetime_index")
    raw = pd.DataFrame({"col": [1.0, 2.0]}, index=idx)
    assert raw.index.tz is None

    result = apply_timezone_to_dataframe(raw, database_options_specific={}, default_timezone="UTC")

    assert str(result.index.tz) == "UTC"  # localization did happen on the returned frame
    assert raw.index.tz is None  # …but the caller's DataFrame was left untouched
