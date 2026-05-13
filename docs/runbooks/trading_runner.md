# Trading runner — Polymarket execution

`scripts/live_runner.py` is the operator entry point for autonomous
trading on Polymarket. It runs the intra-PM arbitrage detector (α2-poly)
against live order books and pushes the resulting orders through the
`AutonomousExecutor` (kill switch → risk gate → slippage check →
submit → JSONL journal).

The cross-venue scanner (`alpha.cross_venue_arb`) is wired but
detection-only until the Kalshi / sportsbook adapters are populated by
the operator. The intra-PM scanner is self-hedging and runs against
Polymarket alone.

## Modes

| mode   | submits to     | money | use it for                          |
| ------ | -------------- | ----- | ----------------------------------- |
| shadow | journal only   | no    | day-one validation, infra checkout  |
| paper  | `PaperBook`    | no    | slippage realism, multi-week trial  |
| live   | Polymarket CLOB| yes   | nano-live ($15) and above           |

`shadow` auto-promotes to `--promote-to` after `--shadow-first-n`
clean cycles. Live mode refuses to start unless the five `POLY_*`
env vars are present and `py-clob-client` is importable.

## Pre-trade safety

Three independent kill-switch triggers:

  - touch `~/.predictormaster.kill` from any shell
  - export `PREDICTORMASTER_KILL=1` (systemd ExecStopPost hook works)
  - programmatic `KillSwitch.trip(reason)` (for tests / panic)

Reset by deleting the file / unsetting the env var / calling
`.reset()`.

Risk-gate defaults are set inside the script from `--bankroll` and
`--max-stake`:

  - per-bet stake cap = `min(--max-stake, max_stake_pct × bankroll)`
  - daily notional cap = one bankroll
  - intraday drawdown halt = 3 %
  - max book-consume = 20 % of top-of-book depth
  - loss-streak pause = 3 losses → 2 h cool-off

The gate caps oversize requests rather than rejecting outright;
rejection only happens when an already-capped order still breaches
some other limit.

## First run — sequence

```bash
# 0. Activate venv
source venv/bin/activate

# 1. Dry-run: zero network, exercises the preflight + main loop.
python scripts/live_runner.py --dry-run --once

# 2. Real read-only scan in shadow mode.
python scripts/live_runner.py --once --mode shadow --market-limit 100

# 3. Paper-trade 30 minutes against the real order book.
python scripts/live_runner.py --mode paper --interval 60 \
    --bankroll 15 --max-stake 2 --min-edge 0.01

# 4. Inspect what got journalled.
tail -f logs/decisions.jsonl
```

## Going live

Live submission needs the `.env` populated (see `.env.example`). The
$15 USDC + $2 MATIC funding stage covers infrastructure validation
only — fees + slippage will eat a meaningful slice of that on every
fill, so expect to spend the bankroll on the integration test, not
on alpha.

```bash
# Required env (set in .env, auto-loaded):
#   POLY_API_KEY  POLY_API_SECRET  POLY_API_PASSPHRASE
#   POLY_PROXY_ADDRESS  POLY_FUNDER_PK

python scripts/live_runner.py --mode live --interval 60 \
    --bankroll 15 --max-stake 2 --per-arb-stake 2 --min-edge 0.01
```

## Tuning `--min-edge`

The intra-PM scanner subtracts `2 × 2 %` taker fees from the apparent
edge. Order books can move by one tick between the two POSTs, so we
require a margin above noise:

  - `0.005` (0.5 %) — generous; will fire often on thin markets
  - `0.01` (1 %)    — sensible default
  - `0.02` (2 %)    — conservative; rare but cleaner fills

If you see one-sided fills in `decisions.jsonl` (one leg `accepted`,
the other rejected as "kill switch" or "would consume X% of book"),
raise `--min-edge` and reduce `--per-arb-stake`.

## Stage-gate ladder

Promote bankroll only after the prior stage clears its gate:

| stage      | bankroll | max stake | gate to advance                                  |
| ---------- | -------- | --------- | ------------------------------------------------ |
| shadow     | $0       | $0        | 20 clean cycles per α                            |
| paper      | $0       | $0        | 1 week, ≥30 simulated fills, journal review      |
| nano-live  | $15      | $2        | ≥10 real fills, slippage ±25 % of model, no kill |
| micro-live | $100     | $5        | 4 wk, ≥100 bets, walk-forward Sharpe ≥ +0.5      |
| live-A     | $1k      | $20       | continued rising deflated Sharpe                 |
| live-B     | $10k     | $200      | continued positive deflated Sharpe               |

Re-run `scripts/validate_alpha.py` weekly against `logs/decisions.jsonl`
and trip the kill switch if any α falls below its DSR threshold.

## Operating it unattended

For a VPS-hosted continuous run:

```ini
# /etc/systemd/system/predictormaster.service
[Unit]
Description=Predictormaster trading runner
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/op/predictormaster
EnvironmentFile=/home/op/predictormaster/.env
ExecStart=/home/op/predictormaster/venv/bin/python scripts/live_runner.py \
    --mode live --interval 60 --bankroll 15 --max-stake 2 --min-edge 0.01
Restart=on-failure
RestartSec=30
ExecStopPost=/usr/bin/touch /home/op/.predictormaster.kill

[Install]
WantedBy=multi-user.target
```

The `ExecStopPost` hook leaves the kill switch tripped after a stop so
restart-loops don't accidentally trade — clear it manually with
`rm ~/.predictormaster.kill` before the next `systemctl start`.
