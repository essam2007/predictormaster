"""Subprocess manager for scripts/live_runner.py.

Owns at most one running ``live_runner`` process at a time. Persists
the (pid, mode, started_at, args) tuple to a state file so an HTTP
server restart doesn't lose track of the running bot — the next API
call re-attaches by PID. If the PID is dead, state is cleared.

Concurrency
-----------
A ``threading.Lock`` guards every state-mutating method. The FastAPI
endpoints all run on a single asyncio loop with a single sync worker
for the blocking subprocess calls, so contention is rare but
defensive locking is still correct.

Live-mode confirmation
----------------------
``start(...)`` with ``mode="live"`` REQUIRES a confirmation token
``LIVE_CONFIRMATION_TOKEN``. The token is a fixed sentinel string —
not a real auth mechanism, but enough to prevent a misclicked button
from firing real orders. The frontend forces the operator to type the
sentinel verbatim into a modal before the POST goes through.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LIVE_CONFIRMATION_TOKEN = "I UNDERSTAND THIS IS REAL MONEY"
DEFAULT_STATE_PATH = Path("logs/.ops_runner_state.json")
DEFAULT_LIVE_RUNNER = Path("scripts/live_runner.py")


@dataclass
class RunnerState:
    pid: int | None = None
    mode: str | None = None
    bankroll: float | None = None
    max_stake: float | None = None
    min_edge: float | None = None
    interval: float | None = None
    started_at_utc: str | None = None
    args: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid, "mode": self.mode, "bankroll": self.bankroll,
            "max_stake": self.max_stake, "min_edge": self.min_edge,
            "interval": self.interval, "started_at_utc": self.started_at_utc,
            "args": list(self.args),
        }

    def is_active(self) -> bool:
        return self.pid is not None


def _pid_alive(pid: int) -> bool:
    """Best-effort POSIX liveness check. Avoids importing psutil."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@dataclass
class RunnerManager:
    project_root: Path
    state_path: Path = DEFAULT_STATE_PATH
    live_runner_script: Path = DEFAULT_LIVE_RUNNER
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _state: RunnerState = field(default_factory=RunnerState, init=False, repr=False)
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._load_state()

    # ---------------- public API ----------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._reconcile_locked()
            base = self._state.to_dict()
            base["running"] = self._state.is_active()
            base["pid_alive"] = (self._state.pid is not None
                                 and _pid_alive(self._state.pid))
            return base

    def start(self, *, mode: str, bankroll: float, max_stake: float,
              min_edge: float, interval: float,
              confirmation: str | None = None,
              extra_args: list[str] | None = None) -> dict[str, Any]:
        if mode not in ("shadow", "paper", "live"):
            raise ValueError(f"invalid mode {mode!r}")
        if mode == "live" and confirmation != LIVE_CONFIRMATION_TOKEN:
            raise PermissionError("live mode requires the exact confirmation token")
        if bankroll <= 0 or max_stake <= 0:
            raise ValueError("bankroll and max_stake must be positive")
        if min_edge < 0 or min_edge > 1:
            raise ValueError("min_edge must be in [0, 1]")
        if interval < 5:
            raise ValueError("interval must be ≥ 5 seconds (Polymarket rate-limits)")

        with self._lock:
            self._reconcile_locked()
            if self._state.is_active():
                raise RuntimeError(f"runner already active (pid={self._state.pid})")

            script = self.project_root / self.live_runner_script
            if not script.exists():
                raise FileNotFoundError(f"live_runner not found at {script}")

            args = [
                sys.executable, str(script),
                "--mode", mode,
                "--bankroll", str(bankroll),
                "--max-stake", str(max_stake),
                "--min-edge", str(min_edge),
                "--interval", str(interval),
            ]
            if extra_args:
                args.extend(extra_args)

            (self.project_root / "logs").mkdir(parents=True, exist_ok=True)
            stdout_path = self.project_root / "logs" / "runner_stdout.log"
            stderr_path = self.project_root / "logs" / "runner_stderr.log"
            stdout_f = stdout_path.open("a", buffering=1)
            stderr_f = stderr_path.open("a", buffering=1)
            stdout_f.write(f"\n--- started {datetime.now(timezone.utc).isoformat()} mode={mode} ---\n")
            stderr_f.write(f"\n--- started {datetime.now(timezone.utc).isoformat()} mode={mode} ---\n")

            proc = subprocess.Popen(
                args, cwd=str(self.project_root),
                stdout=stdout_f, stderr=stderr_f,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._proc = proc
            self._state = RunnerState(
                pid=proc.pid, mode=mode,
                bankroll=bankroll, max_stake=max_stake,
                min_edge=min_edge, interval=interval,
                started_at_utc=datetime.now(timezone.utc).isoformat(),
                args=args,
            )
            self._save_state_locked()
            logger.info("runner started pid=%d mode=%s", proc.pid, mode)
            return self._state.to_dict()

    def stop(self, *, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            self._reconcile_locked()
            if not self._state.is_active():
                return {"stopped": False, "reason": "not running"}
            pid = self._state.pid
            with contextlib.suppress(ProcessLookupError):
                if self._proc is not None:
                    self._proc.terminate()
                else:
                    os.kill(pid, signal.SIGTERM)
            # wait for graceful exit
            deadline = time.time() + timeout
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.2)
            if _pid_alive(pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)
            self._proc = None
            self._state = RunnerState()
            self._save_state_locked()
            logger.info("runner stopped pid=%d", pid)
            return {"stopped": True, "pid": pid}

    def recent_stdout(self, n_lines: int = 80) -> list[str]:
        path = self.project_root / "logs" / "runner_stdout.log"
        if not path.exists():
            return []
        try:
            content = path.read_text(errors="replace").splitlines()
        except OSError:
            return []
        return content[-n_lines:]

    # ---------------- state file ----------------

    def _state_file(self) -> Path:
        return self.project_root / self.state_path

    def _load_state(self) -> None:
        sp = self._state_file()
        if not sp.exists():
            return
        try:
            blob = json.loads(sp.read_text())
        except (OSError, json.JSONDecodeError):
            return
        st = RunnerState(**{k: v for k, v in blob.items()
                            if k in RunnerState.__annotations__})
        if st.pid is not None and not _pid_alive(st.pid):
            # leftover stale state — clear it.
            st = RunnerState()
        self._state = st

    def _save_state_locked(self) -> None:
        sp = self._state_file()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(self._state.to_dict(), indent=2))

    def _reconcile_locked(self) -> None:
        """If we have a pid recorded but it's dead, clear state. Cheap to
        call on every status query."""
        if self._state.pid is None:
            return
        if not _pid_alive(self._state.pid):
            logger.info("runner pid=%d is dead; clearing state", self._state.pid)
            self._proc = None
            self._state = RunnerState()
            self._save_state_locked()
