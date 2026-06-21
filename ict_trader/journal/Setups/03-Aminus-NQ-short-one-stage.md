---
date: 2026-06-18
instrument: NQ
session: silver_bullet
day_of_week: Thu
grade: A-
status: ILLUSTRATIVE
two_stage_smt: false
smt_stage: 1
psp_tf: 15m
htf_delivery_tf: 4h
daily_bias_intact: true
drawn_liquidity: PDL
lrlr: clean
path_clean: true
moved_to_be_early: false
side: short
killzone: silver_bullet
quarter_idx: 2
---

# 2026-06-18 — NQ short — Grade A-  (missing: only one-stage SSMT)

## 1. Pre-market context
- **News:** none in the 10:00–11:00 Silver Bullet window.
- **Daily bias + why:** **bearish** — daily rejecting a premium 4h FVG; lower highs.

## 2. Markup
- PDH 21,840 (buyside, just swept) · **PDL 21,690** = drawn liquidity (target).
- **HTF FVG (4h):** bearish **21,815–21,845** (premium delivery zone). ✅
- **LTF IFVG (5m):** bearish inversion at 21,822.
- **Drawn liquidity:** **PDL 21,690**, clean lane below (no opposing 4h/1h FVG between).

## 3. Trigger sequence
- **SSMT:** at 10:08 ET **NQ sweeps PDH** (21,842) while **ES holds** below its high → **Stage 1**,
  bearish. **BUT** there is **no nested Stage-2** divergence on the 90m leg (ES and NQ move
  together after) → **one-stage only**. ❌ (this is the single downgrade)
- **PSP:** 15m opposing close at 10:15 ET. ✅
- **Entry trigger:** 5m bearish IFVG inside the 4h FVG.

## 4. Execution
- **Entry:** 21,822 · **Stop:** 21,850 (28 pts, above the 21,842 sweep + buffer).
- **Targets:** interim 21,760 → ERL **PDL 21,690** (≈ +132 / ~4.7R).
- **LRLR:** clean to PDL → hold runner.

## 5. Grade & reasoning
- **Pillars present:** **2-stage SSMT ❌ (one-stage)** · 15m PSP ✅ · 4h HTF ✅ · daily bias ✅ · clean LRLR ✅
- **Grade = A-** (A+ minus one step for one-stage-instead-of-two — your stated example).
- **Why:** everything A+ except the divergence is single-stage, so confirmation is a notch weaker.

## 6. Would you take it?
- **My call:** **take** — one-stage SSMT + 4h premium FVG + clean draw to PDL is still high quality;
  A- is a "yes" for me. (Tell me if you'd want the second stage before committing.)
- **Your verdict:** ⬜
