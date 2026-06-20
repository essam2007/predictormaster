from __future__ import annotations

from tests.conftest import mk_bar, series_from

from ict_trader.detectors.psp import PSPDetector, is_psp
from ict_trader.detectors.smt import SMTDetector, detect_smt
from ict_trader.domain.bars import CoBar
from ict_trader.domain.enums import Side, Symbol, Timeframe


def test_bullish_smt_es_sweeps_nq_holds():
    # Both form a swing low around index 2, then ES makes a LOWER low while NQ holds.
    es = series_from([
        (10, 10.5, 9.5, 10),
        (10, 10.2, 9.0, 9.2),
        (9.2, 9.4, 8.0, 8.2),    # swing low 8.0 (the level)
        (8.3, 9.0, 8.4, 8.8),
        (8.8, 9.0, 7.0, 7.2),    # ES sweeps below 8.0 -> 7.0
    ], symbol=Symbol.ES)
    nq = series_from([
        (10, 10.5, 9.5, 10),
        (10, 10.2, 9.0, 9.2),
        (9.2, 9.4, 8.0, 8.2),    # swing low 8.0
        (8.3, 9.0, 8.4, 8.8),
        (8.8, 9.0, 8.1, 8.5),    # NQ holds above 8.0 -> 8.1
    ], symbol=Symbol.NQ)
    div = detect_smt(es, nq, Side.LONG, strength=1)
    assert div is not None
    assert div["sweeper"] == "ES" and div["holder"] == "NQ"


def test_no_smt_when_both_sweep():
    es = series_from([
        (10, 10.5, 9.5, 10), (10, 10.2, 9, 9.2), (9.2, 9.4, 8, 8.2),
        (8.3, 9, 8.4, 8.8), (8.8, 9, 7, 7.2),
    ], symbol=Symbol.ES)
    nq = series_from([
        (10, 10.5, 9.5, 10), (10, 10.2, 9, 9.2), (9.2, 9.4, 8, 8.2),
        (8.3, 9, 8.4, 8.8), (8.8, 9, 7, 7.1),   # both sweep below 8
    ], symbol=Symbol.NQ)
    assert detect_smt(es, nq, Side.LONG, strength=1) is None


def test_smt_detector_refuses_degraded():
    det = SMTDetector(stage=1, strength=1)
    es = series_from([(1, 2, 0.5, 1.5)] * 6, symbol=Symbol.ES)
    nq = series_from([(1, 2, 0.5, 1.5)] * 5, symbol=Symbol.NQ)  # length mismatch
    st = det.update(es, nq, Side.LONG)
    assert st.present is False and st.payload.get("degraded") is True


def test_psp_opposing_closes():
    es_up = mk_bar(0, 10, 11, 9.9, 10.8, symbol=Symbol.ES)   # bullish
    nq_dn = mk_bar(0, 10, 10.1, 9, 9.2, symbol=Symbol.NQ)    # bearish
    assert is_psp(es_up, nq_dn) is True


def test_psp_doji_excluded():
    es = mk_bar(0, 10, 10.05, 9.95, 10.0, symbol=Symbol.ES)  # doji
    nq = mk_bar(0, 10, 11, 9, 9.2, symbol=Symbol.NQ)
    assert is_psp(es, nq) is False


def test_psp_detector_bias_agreement():
    # bullish setup: NQ closes up, ES closes down -> long agrees
    es = mk_bar(0, 10, 10.1, 9, 9.2, symbol=Symbol.ES)
    nq = mk_bar(0, 10, 11, 9.9, 10.8, symbol=Symbol.NQ)
    cobar = CoBar(ts_open=es.ts_open, timeframe=Timeframe.M5, es=es, nq=nq)
    st = PSPDetector().update(cobar, Side.LONG, inside_htf_fvg=True)
    assert st.present is True
    assert st.payload["nq_dir"] == "long" and st.payload["es_dir"] == "short"
