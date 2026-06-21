# Training Plan — capturing your discretionary edge into the engine

> Goal: get my grading to match yours setup-for-setup, then let the deck deploy the strategy
> "exactly when you would." You trade on intuition; this turns that intuition into a labeled
> dataset + calibrated detector weights + an edge-case rulebook.

## The loop (human-in-the-loop, you drive the corrections)
```
   (1) I mark up setups to the rubric  ──►  (2) you critique: grade + take/pass + WHY
            ▲                                            │
            │                                            ▼
   (5) calibrate detector weights        (3) I log your correction as a labeled example
       so my auto-grade == your grade           (the "edge case")
            ▲                                            │
            └──────────  (4) repeat on fresh setups  ◄───┘
```
This is exactly the `/loop` you started — it advances on **your critique**, not a timer. Reply
with grades/verdicts and I produce the next, sharper batch.

## Phases
- **P1 — Formalize (now).** `Grading-Rubric.md` + `Glossary.md` + `Morning-Routine.md`. You
  correct them. ← we are here.
- **P2 — Label a corpus.** Build ~30–50 graded setups (start with the 5 worked examples here;
  then real ones). Each becomes a row with the rubric tags + your verdict.
- **P3 — Wire real data.** Your TradingView **bar-feed** already streams real NQ/ES candles into
  the deck; or share chart exports / screenshots. I mark up real setups the same way.
- **P4 — Calibrate.** Run the deck's per-bucket analytics + component-lift on the labeled corpus;
  tune the aggregator weights so my **auto-grade ≈ your grade** (measure agreement / inter-rater
  reliability). Encode every edge case you teach into the detector rules + `Edge-Cases.md`.
- **P5 — Validate & deploy.** I grade unseen setups; you spot-check; iterate until we agree at a
  high rate. Then the engine flags A+ setups live exactly on your criteria.

## Tooling (decided)
- **Obsidian vault** = `ict_trader/journal/` — markdown, mobile-friendly for morning markups,
  version-controlled, and each setup's front-matter tags export to the deck's **training
  dataset** (`/api/dataset`). One artifact, two uses (human review + ML features).
- **The deck** — structured analytics, the detector suite that auto-grades, the dataset export.
- **Not installed by me:** the Obsidian *app* (your Mac — obsidian.md, "Open folder as vault").
- **Optional:** if you want me to mirror your exact **Notion** template, connect the Notion
  integration and point me at the page — I'll match its layout (I won't browse your Notion
  without you pointing me there).

## What I need from you to accelerate
1. Answer the 5 open questions in `Grading-Rubric.md` (the grade mechanics).
2. Critique the 5 setups in `Setups/` — grade + take/pass + why.
3. Tell me how real chart data will reach me (bar-feed live / CSV export / screenshots).
