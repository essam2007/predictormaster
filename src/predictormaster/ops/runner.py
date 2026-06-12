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
DEFAULT_LOGGER_SCRIPT = Path("scripts/run_snapshot_logger.py")
DEFAULT_LOGGER_STATE_PATH = Path("logs/.ops_logger_state.json")


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

            # ``python -u`` + PYTHONUNBUFFERED forces line-buffered output
            # on the child's stdout/stderr. Without this, prints land in
            # a block buffer that never flushes until the child exits —
            # the dashboard then shows an empty log even though the bot
            # is running. This bug burned hours of "zero fills?" debugging.
            args = [
                sys.executable, "-u", str(script),
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

            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            proc = subprocess.Popen(
                args, cwd=str(self.project_root),
                stdout=stdout_f, stderr=stderr_f,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            # Immediate-crash detection — see SnapshotLoggerManager.start
            time.sleep(1.0)
            if proc.poll() is not None:
                try:
                    stderr_tail = stderr_path.read_text(
                        errors="replace"
                    ).splitlines()[-15:]
                except OSError:
                    stderr_tail = []
                raise RuntimeError(
                    f"live_runner exited immediately with code {proc.returncode}. "
                    f"stderr tail:\n  " + "\n  ".join(stderr_tail or ["(empty)"])
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

    def recent_stderr(self, n_lines: int = 40) -> list[str]:
        path = self.project_root / "logs" / "runner_stderr.log"
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


# ============================================================================
# Snapshot-logger sidecar manager
# ----------------------------------------------------------------------------
# The book-snapshot logger runs as a long-lived sidecar alongside the runner.
# Its responsibilities are completely independent (it records markets via
# its own discovery loop) so we manage it with a dedicated, simpler class —
# no live-mode confirmation, fewer knobs, single state file.
# ============================================================================


@dataclass
class LoggerState:
    pid: int | None = None
    started_at_utc: str | None = None
    snapshot_interval: float | None = None
    discovery_interval: float | None = None
    market_limit: int | None = None
    output_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__}

    def is_active(self) -> bool:
        return self.pid is not None


@dataclass
class SnapshotLoggerManager:
    project_root: Path
    state_path: Path = DEFAULT_LOGGER_STATE_PATH
    script_path: Path = DEFAULT_LOGGER_SCRIPT
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _state: LoggerState = field(default_factory=LoggerState, init=False, repr=False)
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        sp = self.project_root / self.state_path
        if not sp.exists():
            return
        try:
            blob = json.loads(sp.read_text())
        except (OSError, json.JSONDecodeError):
            return
        st = LoggerState(**{k: v for k, v in blob.items()
                            if k in LoggerState.__annotations__})
        if st.pid is not None and not _pid_alive(st.pid):
            st = LoggerState()
        self._state = st

    def _save_locked(self) -> None:
        sp = self.project_root / self.state_path
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(self._state.to_dict(), indent=2))

    def _reconcile_locked(self) -> None:
        if self._state.pid is None:
            return
        if not _pid_alive(self._state.pid):
            self._proc = None
            self._state = LoggerState()
            self._save_locked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._reconcile_locked()
            base = self._state.to_dict()
            base["running"] = self._state.is_active()
            base["pid_alive"] = (self._state.pid is not None
                                 and _pid_alive(self._state.pid))
            # diagnostic: snapshot count
            snap_dir = (Path(self._state.output_dir)
                        if self._state.output_dir
                        else self.project_root / "logs" / "book_snapshots")
            try:
                files = list(snap_dir.glob("snap-*.jsonl")) if snap_dir.exists() else []
                base["snapshot_files"] = len(files)
                base["snapshot_bytes"] = sum(p.stat().st_size for p in files)
            except OSError:
                base["snapshot_files"] = None
                base["snapshot_bytes"] = None
            return base

    def start(self, *, snapshot_interval: float = 5.0,
              discovery_interval: float = 900.0,
              market_limit: int = 80,
              output_dir: Path | None = None) -> dict[str, Any]:
        if snapshot_interval < 1.0:
            raise ValueError("snapshot_interval must be ≥ 1s (PM rate limits)")
        if discovery_interval < 60.0:
            raise ValueError("discovery_interval must be ≥ 60s")
        if not 1 <= market_limit <= 500:
            raise ValueError("market_limit must be in [1, 500]")
        outdir = output_dir or (self.project_root / "logs" / "book_snapshots")
        with self._lock:
            self._reconcile_locked()
            if self._state.is_active():
                raise RuntimeError(f"snapshot logger already running (pid={self._state.pid})")
            script = self.project_root / self.script_path
            if not script.exists():
                raise FileNotFoundError(f"snapshot logger script not found at {script}")

            args = [
                sys.executable, "-u", str(script),
                "--snapshot-interval", str(snapshot_interval),
                "--discovery-interval", str(discovery_interval),
                "--market-limit", str(market_limit),
                "--output-dir", str(outdir),
                "--verbose",
            ]
            log_dir = self.project_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_f = (log_dir / "snapshot_logger_stdout.log").open("a", buffering=1)
            stderr_f = (log_dir / "snapshot_logger_stderr.log").open("a", buffering=1)
            stdout_f.write(f"\n--- started {datetime.now(timezone.utc).isoformat()} ---\n")
            stderr_f.write(f"\n--- started {datetime.now(timezone.utc).isoformat()} ---\n")
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            proc = subprocess.Popen(
                args, cwd=str(self.project_root),
                stdout=stdout_f, stderr=stderr_f,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            # Immediate-crash detection: a misconfigured logger (missing
            # dep, bad cwd, syntax error) dies in <1s. Catch that here
            # and surface the stderr tail in the error message — much
            # better than letting it look "started" then flip to dead.
            time.sleep(1.0)
            if proc.poll() is not None:
                try:
                    stderr_tail = (log_dir / "snapshot_logger_stderr.log").read_text(
                        errors="replace"
                    ).splitlines()[-15:]
                except OSError:
                    stderr_tail = []
                raise RuntimeError(
                    f"snapshot logger exited immediately with code {proc.returncode}. "
                    f"stderr tail:\n  " + "\n  ".join(stderr_tail or ["(empty)"])
                )
            self._proc = proc
            self._state = LoggerState(
                pid=proc.pid,
                started_at_utc=datetime.now(timezone.utc).isoformat(),
                snapshot_interval=snapshot_interval,
                discovery_interval=discovery_interval,
                market_limit=market_limit,
                output_dir=str(outdir),
            )
            self._save_locked()
            logger.info("snapshot logger started pid=%d", proc.pid)
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
            deadline = time.time() + timeout
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.2)
            if _pid_alive(pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)
            self._proc = None
            self._state = LoggerState()
            self._save_locked()
            return {"stopped": True, "pid": pid}

    def recent_stdout(self, n_lines: int = 60) -> list[str]:
        path = self.project_root / "logs" / "snapshot_logger_stdout.log"
        if not path.exists():
            return []
        try:
            return path.read_text(errors="replace").splitlines()[-n_lines:]
        except OSError:
            return []
