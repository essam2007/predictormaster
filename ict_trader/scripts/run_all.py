#!/usr/bin/env python
"""One command to run the whole research deck: build the UI (if needed), seed demo data
(if the store is empty), and serve the API + UI from a single port.

    python scripts/run_all.py            # build UI if missing, seed if empty, then serve
    python scripts/run_all.py --no-build --no-seed

Open the printed URL. The UI and JSON API are served together, so only one port is needed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import uvicorn

from ict_trader.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"


def _build_frontend() -> None:
    if DIST.is_dir():
        return
    npm = shutil.which("npm")
    if not npm:
        print("! npm not found — the UI won't be served. Install Node, or run the JSON API "
              "only. (You can still use the API + scripts.)")
        return
    print("building the research deck UI (first run only)…")
    subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


async def _seed_if_empty() -> None:
    from ict_trader.domain.enums import TradeMode
    from ict_trader.store.db import Database
    from ict_trader.store.repositories import Repository

    s = get_settings()
    db = Database(s.db_url)
    await db.create_all()
    async with db.session() as sess:
        existing = await Repository(sess).list_trades(TradeMode.BACKTEST)
    await db.dispose()
    if existing:
        return
    print("store empty — seeding sample trades so the deck has data…")
    from demo_seed import _run as seed_run  # type: ignore
    await seed_run()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--no-seed", action="store_true")
    args = p.parse_args()

    if not args.no_build:
        _build_frontend()
    if DIST.is_dir():
        os.environ.setdefault("ICT_TRADER_STATIC_DIR", str(DIST))
    if not args.no_seed:
        asyncio.run(_seed_if_empty())

    s = get_settings()
    url = f"http://{s.api_host}:{s.api_port}"
    print(f"\n  research deck:  {url}\n  API docs:       {url}/docs\n")
    uvicorn.run("ict_trader.api.app:create_app", factory=True,
                host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # allow `import demo_seed`
    main()
