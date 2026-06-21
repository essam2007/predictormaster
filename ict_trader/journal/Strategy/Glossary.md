# Glossary — my current understanding (correct me)

> These are *my* definitions as I'll code them. Where I'm wrong, fix the line — that correction
> is a training signal.

- **SSMT (Sequential/Smart-Money Tool divergence)** — ES and NQ disagree at a liquidity level:
  one index sweeps the level (takes the high/low), the other refuses to. Bullish when one makes a
  *lower* low and the other holds; bearish when one makes a *higher* high and the other holds.
  - **Two-stage** — the divergence appears at the HTF level (Stage 1) and again on a nested 90m /
    lower-TF leg (Stage 2), same direction. Strongest confirmation.
- **PSP (Precision Swing Point)** — at the reversal candle, ES and NQ print **opposing closes on
  the same timestamp** (one closes up, the other down). Read on 5m or 15m here.
- **FVG (Fair Value Gap)** — 3-candle imbalance (bull: `low[i] > high[i-2]`). HTF FVG = bias/POI;
  price delivering back into it from the correct half of the range (discount for longs).
- **IFVG (Inverse FVG)** — an FVG that an opposing **body close** trades through, flipping its
  polarity; the LTF entry trigger. Stop sits just beyond the IFVG extreme.
- **HTF delivery** — price reaching/working a 1h or 4h FVG/PD-array in the bias direction.
- **Daily bias** — the directional read from the daily/HTF + the morning macro markup.
- **Drawn liquidity** — the objective the move is *drawn toward*: PDH/PDL, session highs/lows,
  equal highs/lows, relative-equal pools. The runner target (ERL).
- **LRLR (Low-Resistance Liquidity Run)** — a clean path between entry and the drawn liquidity
  with few/no opposing PD-arrays in the way. "Low resistance range" = how clean that lane is.
- **ERL / IRL** — External Range Liquidity (the draw, e.g. PDH/PDL) vs Internal Range Liquidity
  (FVGs/interim pools you scale at on the way).
- **Killzones** — NY AM; 9:50–10:10 ET macro; 10:00–11:00 Silver Bullet.
- **Quarterly Theory / AMD** — 6h sessions × 90m quarters; Accumulation → Manipulation →
  Distribution. The manipulation leg is where the sweep/SSMT typically forms.

## Where I most expect to be wrong (tell me)
- The exact mechanical trigger for "two-stage" vs "one-stage".
- Whether PSP must be *exactly* same-timestamp or within a tolerance.
- How you personally define "low resistance" cleanliness (count of opposing arrays? size?).
