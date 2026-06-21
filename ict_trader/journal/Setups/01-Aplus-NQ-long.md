---
date: 2026-06-16
instrument: NQ
session: NY-AM
day_of_week: Tue
grade: A+
status: ILLUSTRATIVE
two_stage_smt: true
smt_stage: 2
psp_tf: 5m
htf_delivery_tf: 1h
daily_bias_intact: true
drawn_liquidity: PDH
lrlr: clean
path_clean: true
moved_to_be_early: false
side: long
killzone: ny_am
quarter_idx: 1
---

# 2026-06-16 — NQ long — Grade A+

## 1. Pre-market context
- **News (ForexFactory / red folder):** none in session (next red folder is Thu). Clear to trade.
- **Macro / micro / risks / M&A:** risk-on tone overnight, tech bid, no single-name shock.
- **Daily bias + why:** **bullish** — daily printing higher lows into an unfilled daily FVG;
  prior day closed strong off its lows.

## 2. Markup (levels & PD-arrays)
- **PDL 21,380 · PDH 21,620** · equal lows (sellside) stacked at **21,395**.
- **HTF FVG (1h):** bullish **21,440–21,470** (the POI / delivery zone, discount half of range).
- **LTF FVG / IFVG (5m):** bearish 5m FVG at 21,446–21,458 that later inverts.
- **POI:** the 1h FVG overlapping the swept equal-lows.
- **Drawn liquidity (target / ERL):** **PDH 21,620** (buyside).

## 3. Trigger sequence
- **SSMT:** at 09:38 ET **NQ sweeps** the equal-lows/PDL (prints 21,378) while **ES holds** above
  its prior low → **Stage 1** (HTF, at PDL). A nested 90m leg then sees NQ sweep a 5m equal-low at
  21,402 while ES again holds → **Stage 2**. Both bullish → **two-stage SSMT**. ✅
- **PSP:** 5m candle **09:42 ET** — NQ closes down, ES closes up (opposing same-ts close). ✅
- **The gap that formed (entry trigger):** the 5m bearish FVG (21,446–21,458) gets a **body close
  above** → flips to a bullish **IFVG**; enter off its mid.

## 4. Execution
- **Entry:** **21,452** (IFVG mid, inside the 1h FVG).
- **Stop:** **21,428** (below the IFVG extreme + buffer; below the 21,378 sweep is the invalidation
  floor).
- **Target(s):** interim IRL **21,540** (partials) → ERL **PDH 21,620**.
- **R:R:** risk 24 pts → ERL +168 pts ≈ **7R**.
- **LRLR assessment / management plan:** **clean** — no opposing 1h FVG between entry and PDH;
  hold the runner to PDH, partial at 21,540. **No breakeven on the first pullback.**

## 5. Grade & reasoning
- **Pillars present:** 2-stage SSMT ✅ · 5m PSP ✅ · 1h HTF delivery ✅ · daily bias ✅ · clean LRLR ✅
- **Grade = A+** (all five).
- **Why:** textbook — HTF discount FVG, two-stage ES↔NQ divergence into PDL sellside, PSP confirms
  the turn, clean lane to PDH.

## 6. Would you take it?  (my prediction, for you to critique)
- **My call:** **take**, full size, hold runner to PDH. This is the model's A+ archetype.
- **Your verdict:** ⬜
