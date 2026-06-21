---
title: Strategy ↔ Code Map
type: bridge
tags: [bridge, code, quantdude-trader]
created: 2026-06-21
status: living
---

# Strategy ↔ Code Map

How each concept note connects to the **`quantdude-trader`** repo (formerly
`ict_trader/`). Exact file paths live in `quantdude-trader/CLAUDE.md`; this maps
*concepts → detectors/components*.

| Concept | Code component (quantdude-trader) | Notes |
|---|---|---|
| [[Quarterly Theory]], [[The Four Quarters (AMD-X)]], [[True Opens]], [[Killzones & Quarter Sequence]] | ET/DST-aware **SessionClock** + Quarterly-AMD phase | 90-min quarters, NY-AM killzone, macro/Silver-Bullet windows |
| [[Daily Bias]] | daily-bias + **1h/4h HTF-delivery** inputs | rubric pillar |
| [[SMT Divergence]], [[Sequential SMT (SSMT)]] | **SMT detector** (stage-1 + nested stage-2) | true nested 2-stage SMT = roadmap |
| [[Precision Swing Point (PSP)]] | **PSP detector** (opposing ES/NQ candle closes) | 5–15m confirmation |
| [[Fair Value Gap (FVG)]] | **FVG detector** | mitigation = **body close**, not 50% tap |
| [[Inverse FVG (IFVG) — DodgysDD Model]] | **IFVG / LTF-trigger detector** | inverts on **body close**; emits entry + stop |
| [[FVG + IFVG Combo & V-Shape]] | confluence aggregator + **`analytics/trade_analyzer.py`** | the graded setup |
| [[Liquidity & LRLR]] | Liquidity/ERL target + **low-resistance-path scan** | simplified clean-vs-congested today |

## The grading loop
- **Auto-detect grader:** `analytics/trade_analyzer.py` → 6 weighted elements → 0–1 score → A–D grade.
- **Scanner:** `analytics/setup_scanner.py` + `scripts/scan_setups.py` surface candidates on real OHLC.
- **Narrative grade:** `llm/grader.py` (optional Claude pass; no-ops without `ANTHROPIC_API_KEY`).
- **Rubric source of truth:** `quantdude-trader/journal/Strategy/Grading-Rubric.md`
  (5 pillars: two-stage SSMT, 5/15m PSP, 1h/4h HTF delivery, daily bias,
  drawn-liquidity + LRLR; one letter-step down per missing pillar).

## Calibration goal
Make the auto-grade match **your** grade. The concept notes here + your
calendar-marked [[FVG + IFVG Combo & V-Shape]] examples are the training signal
for folding SMT/HTF into the numeric score.

## Related
- [[00 - Knowledge Base MOC]] · [[_Source Catalog]]
