from __future__ import annotations

import pandas as pd
import pytest

from predictormaster.data.quality import (
    DataQualityError,
    Suite,
    column_present,
    in_range,
    no_nulls,
    unique,
)


def test_suite_passes_clean_df():
    df = pd.DataFrame({"x": [0.1, 0.5, 0.9], "id": [1, 2, 3]})
    s = Suite("clean", [
        column_present("x"),
        no_nulls("x"),
        in_range("x", 0.0, 1.0),
        unique(["id"]),
    ])
    out = s.run(df)
    assert out["rows"] == 3


def test_suite_blocks_critical_failure():
    df = pd.DataFrame({"x": [0.1, None, 5.0], "id": [1, 1, 1]})
    s = Suite("dirty", [
        no_nulls("x"),
        in_range("x", 0.0, 1.0),
        unique(["id"]),
    ])
    with pytest.raises(DataQualityError):
        s.run(df)
