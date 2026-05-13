"""Live runner — the operator's entry point.

What it does, in one loop iteration:

1. Preflight (kill switch armed, env present where needed, journal writable).
2. Discover open Polymarket sports markets (Gamma API).
3. For each market, fetch YES + NO order books and run the intra-PM
   arbitrage detector (``alpha.intra_poly_arb``). Cross-venue
   detection (``alpha.cross_venue_arb``) is wired but disabled by
   default until Kalshi / sportsbook adapters are populated.
4. For each opportunity above ``--min-edge``, build two ``IOC`` orders
   and push them through ``AutonomousExecutor``. Mode is set by
   ``--mode`` (shadow / paper / live).

Modes
-----
  shadow  — log decisions; never POST. Safe day-one default. After
            ``--shadow-first-n`` clean cycles, auto-promotes to
            ``--promote-to``.
  paper   — synthesise fills against the real OB via PaperBook. No
            money at risk. Useful for measuring slippage realism.
  live    — sign and POST orders to Polymarket. Requires the five
            POLY_* env vars. **You will lose money if the strategy
            is broken**; the risk budget caps the damage.

Usage
-----
    # Dry-run with a fake transport (no network):
    python scripts/live_runner.py --mode shadow --once --dry-run

    # Real one-shot scan, shadow mode:
    python scripts/live_runner.py --mode shadow --once

    # Loop every 60 s in paper mode:
    python scripts/live_runner.py --mode paper --interval 60

    # Live (requires .env with POLY_* creds):
    python scripts/live_runner.py --mode live --interval 60 \\
        --bankroll 15 --max-stake 2 --min-edge 0.01

Exit gracefully with Ctrl-C or by touching ~/.predictormaster.kill.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Make project root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Auto-load .env if present (no error if missing).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from predictormaster.alpha.intra_poly_arb import (  # noqa: E402
    OutcomePair,
    to_orders,
)
from predictormaster.alpha.intra_poly_arb import (
    scan as scan_intra,
)
from predictormaster.data.ingestion import sources as ingest_sources  # noqa: E402
from predictormaster.data.ingestion.sources import _get_json  # noqa: E402
from predictormaster.execution.autonomous_executor import (  # noqa: E402
    AutonomousExecutor,
)
from predictormaster.execution.kill_switch import KillSwitch  # noqa: E402
from predictormaster.execution.paper_book import PaperBook  # noqa: E402
from predictormaster.execution.polymarket_clob import PolymarketCLOB  # noqa: E402
from predictormaster.execution.risk_gates import RiskBudget, RiskGate  # noqa: E402

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

REQUIRED_LIVE_ENV = (
    "POLY_API_KEY", "POLY_API_SECRET", "POLY_API_PASSPHRASE",
    "POLY_PROXY_ADDRESS", "POLY_FUNDER_PK",
)


# ---------------- HTTP transports ----------------

def _real_http(url: str, params: dict | None = None) -> dict:
    """Stdlib JSON GET. Used by both the Gamma adapter (via set_http)
    and the CLOB read endpoints."""
    if params:
        # Stringify everything (Gamma rejects bare bools in some versions).
        qp = {k: ("true" if v is True else "false" if v is False else str(v))
              for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(qp)}"
    req = urllib.request.Request(url, headers={"User-Agent": "predictormaster/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        # Surface body for debugging; downstream caller decides how to recover.
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {body[:200]}") from e
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {}


def _fake_http(_url: str, _params: dict | None = None) -> dict:
    """Stub that lets --dry-run exercise the code path with zero network."""
    return {}


# ---------------- Preflight ----------------

@dataclass
class PreflightReport:
    ok: bool
    notes: list[str]


def preflight(mode: str, kill: KillSwitch, journal_path: Path) -> PreflightReport:
    notes: list[str] = []
    ok = True

    if not kill.armed():
        notes.append(f"FAIL kill switch tripped: {kill.tripped_reason()}")
        ok = False
    else:
        notes.append("OK   kill switch armed")

    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a"):
            pass
        notes.append(f"OK   journal writable: {journal_path}")
    except OSError as e:
        notes.append(f"FAIL journal not writable: {e}")
        ok = False

    if mode == "live":
        missing = [k for k in REQUIRED_LIVE_ENV if not os.environ.get(k)]
        if missing:
            notes.append(f"FAIL live mode requires env: {', '.join(missing)}")
            ok = False
        else:
            notes.append("OK   POLY_* credentials present")
        try:
            import py_clob_client  # noqa: F401
            notes.append("OK   py-clob-client importable")
        except ImportError:
            notes.append("FAIL py-clob-client not installed (pip install py-clob-client)")
            ok = False
    else:
        notes.append(f"INFO mode={mode} — live creds not required")

    return PreflightReport(ok=ok, notes=notes)


# ---------------- Market discovery ----------------

def _parse_token_ids(raw) -> tuple[str, str] | None:
    """Gamma returns clobTokenIds as a JSON-encoded string OR a list."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    return (str(raw[0]), str(raw[1]))


def _discover_pairs(limit: int) -> list[OutcomePair]:
    """Pull live binary markets from Gamma with order books enabled.

    We intentionally don't filter by sport tag — Gamma's /markets payload
    no longer includes tags reliably, and an arb on any binary market is
    still an arb. The operator caps blast radius via --max-stake.
    """
    out: list[OutcomePair] = []
    try:
        body = _get_json(
            f"{GAMMA_BASE}/markets",
            {
                "limit": limit, "active": "true", "closed": "false",
                "order": "liquidity", "ascending": "false",
            },
        )
    except Exception as e:
        print(f"[discover] gamma fetch failed: {e}", file=sys.stderr)
        return out
    items = body if isinstance(body, list) else (body.get("data") or body.get("markets") or [])
    for r in items:
        if not (r.get("enableOrderBook") or r.get("acceptingOrders")):
            continue
        if r.get("closed"):
            continue
        tokens = _parse_token_ids(r.get("clobTokenIds"))
        if tokens is None:
            continue
        out.append(OutcomePair(
            condition_id=str(r.get("id") or r.get("conditionId") or ""),
            question=str(r.get("question", "")),
            yes_token_id=tokens[0],
            no_token_id=tokens[1],
        ))
    return out


# ---------------- Main loop ----------------

def _one_cycle(
    *,
    executor: AutonomousExecutor,
    clob: PolymarketCLOB,
    market_limit: int,
    min_edge: float,
    per_arb_stake_usd: float,
) -> int:
    """Run a single scan + execute pass. Returns the number of orders dispatched."""
    pairs = _discover_pairs(market_limit)
    if not pairs:
        print("[cycle] no live binary markets discovered")
        return 0
    arbs = scan_intra(clob, pairs, min_edge=min_edge)
    if not arbs:
        print(f"[cycle] scanned {len(pairs)} markets, no arbs above {min_edge:.1%}")
        return 0
    dispatched = 0
    for a in arbs:
        try:
            yes_o, no_o = to_orders(a, total_stake_usd=per_arb_stake_usd)
        except ValueError as e:
            print(f"[cycle] skip {a.condition_id}: {e}")
            continue
        d1 = executor.execute(alpha="intra_poly_arb", req=yes_o)
        d2 = executor.execute(alpha="intra_poly_arb", req=no_o)
        dispatched += 2
        print(
            f"[arb] {a.question[:60]!r} edge={a.edge:.2%} "
            f"YES={d1.accepted}/{d1.rejection_reason or 'ok'} "
            f"NO={d2.accepted}/{d2.rejection_reason or 'ok'}"
        )
        if not d1.accepted or not d2.accepted:
            # One-sided fill is dangerous; we don't retry. The journal
            # records both attempts so operator can hedge manually.
            print("[arb] WARNING one-sided execution; review decisions.jsonl")
    return dispatched


def main() -> int:
    p = argparse.ArgumentParser(description="Predictormaster live runner")
    p.add_argument("--mode", choices=("shadow", "paper", "live"), default="shadow")
    p.add_argument("--promote-to", choices=("paper", "live"), default="paper",
                   help="Mode shadow auto-promotes to after --shadow-first-n cycles")
    p.add_argument("--shadow-first-n", type=int, default=10)
    p.add_argument("--interval", type=float, default=0.0,
                   help="Seconds between cycles (0 ⇒ one shot)")
    p.add_argument("--once", action="store_true", help="Single cycle then exit")
    p.add_argument("--bankroll", type=float, default=15.0, help="USDC bankroll")
    p.add_argument("--max-stake", type=float, default=2.0,
                   help="Hard per-bet stake cap in USDC")
    p.add_argument("--per-arb-stake", type=float, default=2.0,
                   help="USDC committed per arbitrage opportunity (split across legs)")
    p.add_argument("--min-edge", type=float, default=0.01,
                   help="Minimum after-fee edge to act on (0.01 = 1 pct)")
    p.add_argument("--market-limit", type=int, default=100,
                   help="Max Gamma markets to inspect per cycle")
    p.add_argument("--journal", type=Path, default=Path("logs/decisions.jsonl"))
    p.add_argument("--dry-run", action="store_true",
                   help="Use a stub HTTP transport (no network). Forces mode=shadow.")
    args = p.parse_args()

    if args.dry_run:
        args.mode = "shadow"
        ingest_sources.set_http(_fake_http)
        http_fn = _fake_http
    else:
        ingest_sources.set_http(_real_http)
        http_fn = _real_http

    kill = KillSwitch()
    clob = PolymarketCLOB(http=http_fn)
    paper = PaperBook()
    risk = RiskGate(RiskBudget(
        bankroll_usd=args.bankroll,
        max_stake_usd=args.max_stake,
        max_stake_pct=min(0.20, args.max_stake / max(args.bankroll, 1.0)),
        max_daily_notional_usd=args.bankroll,    # one full bankroll/day cap
        max_daily_drawdown_pct=0.03,
        max_book_consume_pct=0.20,
    ))
    executor = AutonomousExecutor(
        clob=clob, paper=paper, risk=risk, kill=kill,
        mode=args.mode,
        journal_path=args.journal,
        shadow_first_n=args.shadow_first_n,
        promote_to=args.promote_to,
    )

    report = preflight(args.mode, kill, args.journal)
    print("=== Preflight ===")
    for n in report.notes:
        print(f"  {n}")
    if not report.ok:
        print("Preflight failed. Aborting.")
        return 2

    print(f"=== Running in {args.mode!r} mode "
          f"(bankroll=${args.bankroll}, max_stake=${args.max_stake}, "
          f"min_edge={args.min_edge:.2%}) ===")

    try:
        while True:
            try:
                n = _one_cycle(
                    executor=executor,
                    clob=clob,
                    market_limit=args.market_limit,
                    min_edge=args.min_edge,
                    per_arb_stake_usd=args.per_arb_stake,
                )
                print(f"[cycle] dispatched {n} orders")
            except Exception as e:
                # Don't let a single cycle exception kill an unattended loop.
                print(f"[cycle] error: {e!r}", file=sys.stderr)
            if args.once or args.interval <= 0:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nInterrupted, exiting cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
