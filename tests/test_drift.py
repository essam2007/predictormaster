from __future__ import annotations

import numpy as np

from predictormaster.validation.drift import ADWIN, PageHinkley


def test_page_hinkley_detects_shift():
    rng = np.random.default_rng(0)
    ph = PageHinkley(threshold=10.0, delta=0.01)
    detected_at = None
    for i in range(2000):
        x = rng.normal(0.0 if i < 1000 else 0.5, 0.1)
        if ph.update(x) and detected_at is None:
            detected_at = i
            break
    assert detected_at is not None
    assert 1000 <= detected_at < 1500


def test_adwin_does_not_alarm_on_stationary():
    rng = np.random.default_rng(2)
    a = ADWIN(delta=0.001)
    alarms = 0
    for _ in range(500):
        if a.update(float(rng.normal(0, 0.1))):
            alarms += 1
    assert alarms == 0
