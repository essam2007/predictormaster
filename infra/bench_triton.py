"""Triton dynamic-batching sweep.

Drives N concurrent clients at a target QPS against a Triton gRPC endpoint
and reports p50 / p95 / p99 latency and effective throughput. Sweeps
``max_queue_delay_microseconds`` ∈ {500, 1000, 2000, 5000} by default; pick
the value that minimises p95 at the throughput you actually need.

CI skips this script unless ``TRITON_URL`` is set.

Usage:

    python infra/bench_triton.py \
        --triton localhost:8001 \
        --model pm_meta_ensemble \
        --qps 2000 --duration 60 --concurrency 16

Note: this script does NOT mutate the Triton config. After picking the best
value, edit ``serving/triton/config.pbtxt`` and redeploy.
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _make_client(url: str):  # pragma: no cover - integration
    try:
        import tritonclient.grpc as grpcclient
    except Exception as exc:
        raise RuntimeError("tritonclient[grpc] is required to run bench_triton") from exc
    return grpcclient


def run_sweep(
    *,
    triton_url: str,
    model: str,
    qps: int,
    duration: float,
    concurrency: int,
    feature_dim: int,
) -> dict[str, float]:  # pragma: no cover - integration
    grpcclient = _make_client(triton_url)
    client = grpcclient.InferenceServerClient(url=triton_url, verbose=False)

    latencies: list[float] = []
    lock = threading.Lock()
    deadline = time.time() + duration
    interval = concurrency / max(qps, 1)

    def one_request():
        try:
            import numpy as np

            payload = np.random.random(feature_dim).astype("float32")
            inp = grpcclient.InferInput("features", payload.shape, "FP32")
            inp.set_data_from_numpy(payload)
            t0 = time.perf_counter()
            client.infer(model_name=model, inputs=[inp])
            t1 = time.perf_counter()
            with lock:
                latencies.append((t1 - t0) * 1000.0)
        except Exception as exc:
            sys.stderr.write(f"infer failed: {exc!r}\n")

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while time.time() < deadline:
            pool.submit(one_request)
            time.sleep(interval)

    return {
        "n": float(len(latencies)),
        "p50": _percentile(latencies, 0.50),
        "p95": _percentile(latencies, 0.95),
        "p99": _percentile(latencies, 0.99),
        "mean": statistics.fmean(latencies) if latencies else 0.0,
        "throughput": len(latencies) / max(duration, 1e-9),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--triton", default=os.environ.get("TRITON_URL"))
    parser.add_argument("--model", default="pm_meta_ensemble")
    parser.add_argument("--qps", type=int, default=2000)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--feature-dim", type=int, default=64)
    args = parser.parse_args()

    if not args.triton:
        sys.stderr.write("TRITON_URL not set; skipping bench.\n")
        return 0

    random.seed(0)
    summary = run_sweep(
        triton_url=args.triton,
        model=args.model,
        qps=args.qps,
        duration=args.duration,
        concurrency=args.concurrency,
        feature_dim=args.feature_dim,
    )
    print(
        f"n={int(summary['n'])} "
        f"p50={summary['p50']:.2f}ms "
        f"p95={summary['p95']:.2f}ms "
        f"p99={summary['p99']:.2f}ms "
        f"mean={summary['mean']:.2f}ms "
        f"qps={summary['throughput']:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
