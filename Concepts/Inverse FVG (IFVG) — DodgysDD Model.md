---
title: Inverse FVG (IFVG) — DodgysDD Model
type: concept
tags: [concept, ifvg, fvg, entry-model, dodgysdd]
created: 2026-06-21
status: transcript-needed
sources:
  - "https://www.youtube.com/@DodgysDD"
  - "https://youtu.be/qt3nyykeBC0"
---

# Inverse FVG (IFVG) — DodgysDD Model

The **entry trigger**. An IFVG is a [[Fair Value Gap (FVG)]] that **failed to
hold** — price displaces *through* it in the opposite direction, so the broken gap
is now used as support/resistance the *other* way. Popularised by **DodgysDD
(Ryan Wilson)**.

## The rule-based sequence
1. **Liquidity sweep** — price takes a prior swing high/low ([[Liquidity & LRLR]]).
2. **Displacement** — a strong body-to-body move accelerates *back through* the FVG, inverting it.
3. **Entry** — on the IFVG forming (by wick or close, per the model) / its retest;
   **stop** just beyond the sweep extreme; **target** the next opposing liquidity.

> [!important] House rule vs. DodgysDD
> The deck's IFVG detector inverts **only on a body close**, not a wick. DodgysDD's
> model allows inversion "by a candle wick **or** close." Decide which you want the
> grader to use — paste the channel's exact rules to settle it. `transcript-needed`.

## Best context
Most effective on **NQ/ES during the NY session**, in line with [[Daily Bias]],
inside a [[Killzones & Quarter Sequence|killzone]], with [[Sequential SMT (SSMT)]]
/ [[Precision Swing Point (PSP)]] confluence → the [[FVG + IFVG Combo & V-Shape]]
entry.

## Related
- [[Fair Value Gap (FVG)]] · [[FVG + IFVG Combo & V-Shape]] · [[Liquidity & LRLR]]
- Code: IFVG detector (body-close inversion, emits entry + stop) — [[Strategy ↔ Code Map]]

## Sources
- DodgysDD channel: https://www.youtube.com/@DodgysDD
- *iFVG Ultimate+ | DodgysDD* (indicator writeup): https://www.tradingview.com/script/JOUhqb85-iFVG-Ultimate-DodgysDD/
- FluxCharts — *Inversion Fair Value Gaps (IFVG) Explained*: https://www.fluxcharts.com/articles/inversion-fair-value-gaps-ifvg-explained
- innercircletrader.net — *ICT Inversion Fair Value Gap*: https://innercircletrader.net/tutorials/ict-inversion-fair-value-gap/
