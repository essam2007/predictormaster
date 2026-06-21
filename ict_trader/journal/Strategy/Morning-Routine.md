# Morning Routine — the pre-session markup (as you described it)

> This is the process I'll encode as the deck's "context" gate. Each step maps to data the
> engine can capture so my markup matches yours.

## 1. News & macro check (before the screen)
- **Economic calendar / ForexFactory** — scan for high-impact **red-folder** news today.
- If a red folder hits the session (8:30 ET CPI/NFP, FOMC, etc.) → note the window; stand aside
  around it.
- **Earnings reports**, overall **macro** + **micro** news, global **risks**, **M&A** — anything
  that could move the market and set the day's lean.

## 2. If clear (e.g. a quiet Monday) → markup ~8:00–8:30 ET
- Mark the **levels**: PDH/PDL, session highs/lows, equal highs/lows, key HTF FVGs.
- Set the **daily bias** from the macro read + HTF structure.
- Mark **HTF fair value gaps** (1h/4h) and **LTF fair value gaps** (5m/15m).
- Mark **points of interest** — where I'd want to enter.
- Mark **where I'm looking for SSMT**, and **where it would deliver to** if it fires (the drawn
  liquidity / ERL).

## 3. Wait for the setup
- Let price come to a POI; watch the ES↔NQ pair for the **SSMT** (ideally two-stage) and the
  **PSP** on 5m/15m.
- When the **second-stage gap forms** at the level → that's the trigger to take it.
- Grade it on the spot with the rubric → A+ down to whatever pillars are present.

## What the engine captures per step (so my markup == yours)
| Your step | Engine signal |
|---|---|
| Red-folder news window | news/day filter (hard gate) |
| Daily bias | bias input + HTF structure detector |
| HTF/LTF FVGs, POIs | FVG / IFVG detectors |
| SSMT (1- vs 2-stage) | SMT stage-1 + stage-2 detectors (ES↔NQ) |
| PSP | PSP detector (same-ts opposing closes) |
| Drawn liquidity + LRLR | liquidity + low-resistance-path scan |
| "second-stage gap forms" → enter | aggregator emits EntryIntent |

## To confirm
- Your exact **time** to be at the screen, and how long you give a POI before discarding it.
- Do you require the macro (9:50–10:10) or Silver Bullet (10:00–11:00) window, or is NY-AM enough?
- News: which specific events are *hard* stand-aside vs just "size down / wait 15m"?
