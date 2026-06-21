---
title: Fair Value Gap (FVG)
type: concept
tags: [concept, fvg, imbalance, ict]
created: 2026-06-21
status: metadata
---

# Fair Value Gap (FVG)

The imbalance primitive. An **FVG** is a 3-candle pattern where strong
**displacement** leaves a gap that candle **bodies** don't overlap — an
inefficiency the market tends to revisit ("rebalance").

## Definition
- **Bullish FVG:** gap between candle-1 high and candle-3 low (price ran up fast).
- **Bearish FVG:** gap between candle-1 low and candle-3 high.
- Created by **displacement** (a decisive, body-heavy move), not a lazy drift.

## House rules (this strategy)
- **"Mitigated" = a body close through** the gap, **not** a 50% wick tap. (The
  deck's detectors deliberately use body-close logic.)
- FVGs are used **in line with [[Daily Bias]]** and in discount/premium context.

## Why it matters
An FVG that **fails to hold** becomes the entry signal — see
[[Inverse FVG (IFVG) — DodgysDD Model]]. In line with bias it's a target/retest
zone; inverted it's a reversal trigger.

## Related
- [[Inverse FVG (IFVG) — DodgysDD Model]] · [[FVG + IFVG Combo & V-Shape]] · [[Liquidity & LRLR]]
- Code: FVG detector (body-close mitigation) — [[Strategy ↔ Code Map]]

## Sources
- TrendSpider — *Fair Value Gap Trading Strategy*: https://trendspider.com/learning-center/fair-value-gap-trading-strategy/
- FluxCharts — *Inversion Fair Value Gaps (IFVG) Explained*: https://www.fluxcharts.com/articles/inversion-fair-value-gaps-ifvg-explained
