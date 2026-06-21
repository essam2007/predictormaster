---
date: YYYY-MM-DD
instrument: NQ            # traded instrument (ES is the correlation pair)
session: NY-AM           # NY-AM | macro | silver_bullet | lunch | NY-PM
day_of_week:             # Mon..Fri (Tue/Wed preferred, Fri avoid)
grade:                   # A+ | A | A- | B+ | B | B- | C+ | C | C- | D
status: ILLUSTRATIVE     # ILLUSTRATIVE (worked example) | LIVE (real fill)
# --- structured tags (feed the deck's training dataset) ---
two_stage_smt:           # true | false
smt_stage:               # 0 | 1 | 2
psp_tf:                  # none | 5m | 15m
htf_delivery_tf:         # none | 1h | 4h
daily_bias_intact:       # true | false
drawn_liquidity:         # PDH | PDL | session_high | session_low | equal_highs | ...
lrlr:                    # clean | half | runs_out_early | none
path_clean:              # true | false
moved_to_be_early:       # true | false  (the leak — be honest)
side:                    # long | short
killzone:                # ny_am | silver_bullet | lunch | none
quarter_idx:             # 0..3 within the 6h session
---

# {{date}} — {{instrument}} {{side}} — Grade {{grade}}

## 1. Pre-market context
- **News (ForexFactory / red folder):**
- **Macro / micro / risks / M&A:**
- **Daily bias + why:**

## 2. Markup (levels & PD-arrays)
- **PDH / PDL / session H-L / equal pools:**
- **HTF FVG (1h/4h):**
- **LTF FVG / IFVG (5m/15m):**
- **Point(s) of interest:**
- **Drawn liquidity (target / ERL):**

## 3. Trigger sequence
- **SSMT:** ES vs NQ — who swept, who held; Stage-1 (HTF) … Stage-2 (90m) …
- **PSP:** timeframe + the same-timestamp opposing close.
- **The gap that formed (entry trigger):**

## 4. Execution
- **Entry:**         (price + why here)
- **Stop:**          (beyond the IFVG extreme + buffer)
- **Target(s):**     (interim IRL → ERL)
- **R:R:**
- **LRLR assessment / management plan:**  (hold runner / partials / BE where LRLR runs out)

## 5. Grade & reasoning
- **Pillars present:** 2-stage SSMT ▢ · 5/15m PSP ▢ · HTF delivery ▢ · daily bias ▢ · LRLR ▢
- **Grade = A+ minus (missing pillars):**  → **{{grade}}**
- **Why this grade:**

## 6. Would you take it?  (my prediction, for you to critique)
- **My call:** take / pass — because …
- **Your verdict:** ⬜ (you fill this — this is the training signal)
