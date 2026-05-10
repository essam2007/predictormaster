from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Settings:
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    feature_store_online_url: str = field(
        default_factory=lambda: os.environ.get("FS_ONLINE_URL", "redis://localhost:6379/0")
    )
    feature_store_offline_path: Path = field(
        default_factory=lambda: Path(os.environ.get("FS_OFFLINE_PATH", "/tmp/pm_offline"))
    )
    mlflow_tracking_uri: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_TRACKING_URI", "file:./mlruns")
    )
    timescale_dsn: str = field(
        default_factory=lambda: os.environ.get(
            "TIMESCALE_DSN", "postgresql://pm:pm@localhost:5432/pm"
        )
    )
    kafka_bootstrap: str = field(
        default_factory=lambda: os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
    )
    triton_url: str = field(
        default_factory=lambda: os.environ.get("TRITON_URL", "localhost:8001")
    )
    random_seed: int = 1729

    def load_yaml(self, name: str) -> dict:
        path = self.project_root / "configs" / f"{name}.yaml"
        with path.open() as fh:
            return yaml.safe_load(fh)


SETTINGS = Settings()
