"""Operator entry point for the ops dashboard.

    python scripts/run_ops.py
    # → http://127.0.0.1:8765

Binds to loopback only by default. To expose on the LAN (NOT
recommended without auth):

    python scripts/run_ops.py --host 0.0.0.0 --port 8765

Reads .env via the FastAPI lifespan hook so balance queries and
credential-presence checks work without manually exporting vars.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predictormaster.ops.app import create_app  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="predictormaster ops dashboard")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (default: 127.0.0.1, loopback only)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true",
                   help="dev-mode auto-reload (don't use in production)")
    args = p.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn is required. Install with:")
        print("    pip install 'uvicorn[standard]' fastapi")
        return 1

    app = create_app()
    print("\npredictormaster ops dashboard")
    print(f"  → http://{args.host}:{args.port}\n")
    if args.host != "127.0.0.1":
        print("  WARNING: binding to non-loopback address. No auth — anyone on the")
        print("           network can stop/start the bot. Use behind a firewall.\n")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload,
                log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
