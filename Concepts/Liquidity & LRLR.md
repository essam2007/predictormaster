---
title: Liquidity & LRLR
type: concept
tags: [concept, liquidity, lrlr, target, ict]
created: 2026-06-21
status: metadata
---

# Liquidity & LRLR

**What price is hunting** (the fuel) and **the path it takes** (the road).

## Liquidity pools
Resting orders cluster where stops sit:
- **BSL** (buy-side liquidity) — above equal **highs** / old highs
- **SSL** (sell-side liquidity) — below equal **lows** / old lows
- **ERL / IRL** — External (range extremes) vs Internal (FVGs inside range) liquidity

A move's **target** is usually the opposing liquidity pool. The
[[The Four Quarters (AMD-X)|Q2 manipulation]] *sweeps* one pool to fuel the Q3 run
into the other.

## LRLR — Low-Resistance Liquidity Run
The "clean lane." After the sweep + reversal, price runs fastest toward a target
when the path is **uncongested** — few opposing FVGs/structure in the way (a
**low-resistance** path) vs a choppy, high-resistance lane.
- Prefer setups whose target sits at the end of a **clean LRLR**.
- Drawn liquidity + LRLR is a rubric pillar in the trader repo.

> [!note] Detector simplification
> The deck's current LRLR scan is a simplified "clean vs congested" heuristic —
> a true drawn-liquidity + LRLR model is on the roadmap.

## Related
- [[SMT Divergence]] · [[Fair Value Gap (FVG)]] · [[FVG + IFVG Combo & V-Shape]] · [[Daily Bias]]
- Code: Liquidity/ERL target + low-resistance-path scan — [[Strategy ↔ Code Map]]

## Sources
- innercircletrader.net — *ICT Killzones / liquidity*: https://innercircletrader.net/tutorials/master-ict-kill-zones/
- LuxAlgo — *ICT Unicorn Model* (liquidity + FVG confluence): https://www.luxalgo.com/blog/ict-unicorn-model-strategy-how-to-use/
