# Grading Rubric — ICT + Quarterly-Theory intraday reversal (NQ/ES)

> **Source of truth for how setups are graded.** You (the trader) own this — correct anything
> I got wrong. Everything I code in the deck's detectors/aggregator will be calibrated to
> reproduce these grades on your own fills.

## The five A+ pillars
A setup is **A+** only when ALL five hold:

1. **Two-stage SSMT** — Stage-1 HTF SMT (ES↔NQ divergence at a recognized liquidity level) **+**
   Stage-2 nested SMT (90-minute / lower timeframe), both pointing the same direction.
2. **PSP on 5m or 15m** — a precision swing point: same-timestamp opposing closes between ES and
   NQ at the reversal swing.
3. **HTF delivery / FVG on 1h or 4h (≥ 1h)** — a higher-timeframe fair value gap delivering price
   in the bias direction.
4. **Daily bias intact** — the daily directional read still holds (not invalidated intrasession).
5. **Drawn liquidity + low-resistance range (LRLR)** — a defined opposing liquidity target with a
   clean path to it: ideally all the way, or at least ~half, with breakeven managed to where the
   LRLR runs out.

## Downgrade ladder — each missing/degraded pillar = one step down
Scale: **A+ → A → A− → B+ → B → B− → C+ → C → C− → D**

Start at A+ and drop one letter-step per missing/degraded pillar. Your stated examples,
encoded:

| What's missing / degraded | Resulting grade (your words) |
|---|---|
| Drawn liquidity / LRLR absent | **A** |
| Only one-stage SSMT (not two) | **A−** |
| No higher-timeframe delivery (LTF only) | **B+** |
| (further misses each drop another step) | B, B−, C+ … |

## Management implication of the LRLR pillar
- **Clean LRLR all the way to the drawn liquidity** → hold the runner to it (ERL).
- **LRLR ~half way** → take partials, manage the remainder.
- **LRLR runs out before the target** → *that* is the breakeven point — **not** the first
  pullback. (Moving to BE on the first pullback is the documented leak this whole project exists
  to kill.)

## Hard filters (set in the morning, before any setup)
- High-impact / red-folder news window (8:30 ET CPI/NFP, FOMC) → stand aside.
- Day-of-week lean (Tue/Wed preferred, Fri avoid).
- Killzone: NY AM; 9:50–10:10 macro; 10:00–11:00 Silver Bullet.

## Open questions for you to resolve (so I encode it EXACTLY)
1. Is **daily bias** a hard gate (break it ⇒ no trade at any grade) or a gradable pillar?
2. Exact **step order** when several pillars are missing at once — strict left-to-right above, or
   are some pillars weighted heavier?
3. Does **PSP timeframe** (5m vs 15m) change the grade, or only its presence?
4. "Two-stage SSMT" — must Stage-2 also be an ES↔NQ pair sweep, or can it be nested intra-NQ
   structure?
5. Minimum **LRLR cleanliness** to still call it A+ — how many opposing PD-arrays are allowed in
   the path before it's no longer "low resistance"?

> Answer these in-line (edit this file) or in chat and I'll lock them into the detector weights.
