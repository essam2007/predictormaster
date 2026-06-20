#!/usr/bin/env python
"""Run the research-deck API: python scripts/run_api.py"""

from __future__ import annotations

import uvicorn

from ict_trader.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("ict_trader.api.app:create_app", factory=True,
                host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    main()
