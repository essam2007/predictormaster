---
date: 2026-06-15
instrument: NQ
session: NY-AM
day_of_week: Mon
grade: B+
status: ILLUSTRATIVE
two_stage_smt: true
smt_stage: 2
psp_tf: 5m
htf_delivery_tf: none
daily_bias_intact: true
drawn_liquidity: session_high
lrlr: clean
path_clean: true
moved_to_be_early: false
side: long
killzone: ny_am
quarter_idx: 1
---

# 2026-06-15 — NQ long — Grade B+  (missing: no HTF 1h/4h delivery)

## 1. Pre-market context
- **News:** quiet Monday, no red folder.
- **Daily bias + why:** **bullish** but **price is not in any 1h/4h FVG** — the HTF arrays are far
  away; this is a pure intraday continuation, not an HTF-delivery setup.

## 2. Markup
- Session low swept at 21,210 · **session high 21,330** = drawn liquidity.
- **HTF FVG (1h/4h):** **none in play** ❌ — nearest 1h FVG is 120 pts away.
- **LTF FVG/IFVG (5m):** bullish IFVG at 21,236 (the only PD-array supporting entry).

## 3. Trigger sequence
- **SSMT:** two-stage, bullish (NQ sweeps the session low twice, ES holds both). ✅✅
- **PSP:** 5m opposing close at 09:48 ET. ✅
- **Entry trigger:** 5m bullish IFVG.

## 4. Execution
- **Entry:** 21,236 · **Stop:** 21,216 (20 pts) · **Target:** session high **21,330** (+94 / ~4.7R).
- **LRLR:** clean to the session high → hold runner there (intraday draw, not ERL/PDH).

## 5. Grade & reasoning
- **Pillars present:** 2-stage SSMT ✅ · 5m PSP ✅ · **HTF delivery ❌** · daily bias ✅ · clean LRLR ✅
- **Grade = B+** (A+ minus one step for no higher-timeframe delivery — your stated example).
- **Why:** strong LTF trigger + two-stage SSMT + clean intraday draw, but with no 1h/4h FVG
  backing the entry it lacks the HTF context that defines your top grade.

## 6. Would you take it?
- **My call:** **probably pass / very reduced** — without HTF delivery I suspect this is below your
  personal take-threshold even though it's "valid." **This is the one I most want your verdict on**
  — is B+ a take for you, or do you require HTF delivery?
- **Your verdict:** ⬜
