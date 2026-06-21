---
date: 2026-06-17
instrument: NQ
session: NY-AM
day_of_week: Wed
grade: A
status: ILLUSTRATIVE
two_stage_smt: true
smt_stage: 2
psp_tf: 5m
htf_delivery_tf: 1h
daily_bias_intact: true
drawn_liquidity: none
lrlr: runs_out_early
path_clean: false
moved_to_be_early: false
side: long
killzone: ny_am
quarter_idx: 1
---

# 2026-06-17 — NQ long — Grade A  (missing: clean drawn liquidity / LRLR)

## 1. Pre-market context
- **News:** none in session.
- **Macro:** mildly risk-on; nothing decisive.
- **Daily bias + why:** **bullish**, but price is **mid-range** on the daily (not coming off a
  clean discount), so the "draw" above is ambiguous.

## 2. Markup
- PDH 21,705 (far, and the path to it is congested) · no clean equal-highs to target.
- **HTF FVG (1h):** bullish 21,560–21,585 — valid POI.
- **LTF IFVG (5m):** inverts at 21,572.
- **Drawn liquidity (target):** **none clean** — between price and PDH sit **two opposing 1h
  FVGs** (21,640–21,660 and 21,680–21,700); no low-resistance lane.

## 3. Trigger sequence
- **SSMT:** two-stage, bullish (NQ sweeps a session low, ES holds; nested repeat). ✅✅
- **PSP:** 5m opposing close at 09:55 ET. ✅
- **Entry trigger:** 5m bullish IFVG inside the 1h FVG.

## 4. Execution
- **Entry:** 21,572 · **Stop:** 21,550 (22 pts) · **Targets:** first opposing 1h FVG **21,640**
  (≈ +68 / 3R) — and that's where it stops being clean.
- **LRLR assessment / management plan:** **runs out early** — clean only to ~21,640, then opposing
  arrays. Plan: take the move to 21,640, then **breakeven exactly there** (where the LRLR runs
  out) and let any runner be a free option. *This is the "BE where the low-resistance range runs
  out" case from your rubric — not the first pullback.*

## 5. Grade & reasoning
- **Pillars present:** 2-stage SSMT ✅ · 5m PSP ✅ · 1h HTF ✅ · daily bias ✅ · **clean LRLR ❌**
- **Grade = A** (A+ minus the drawn-liquidity / LRLR pillar — your stated "no liquidity → A").
- **Why:** the trigger stack is A+, but there's no clean draw to a defined external pool, so the
  expectancy/− runner is capped; downgraded one step.

## 6. Would you take it?
- **My call:** **take, reduced** — same trigger quality, but I manage to BE at 21,640 and don't
  expect a clean ERL run. Worth it for the 3R to the first array.
- **Your verdict:** ⬜
