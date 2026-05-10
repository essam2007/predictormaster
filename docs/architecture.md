# predictormaster: System Architecture and Latency Budgets

```
                        ┌──────────────────────────────────────────────────────┐
                        │                External world                       │
                        └─────────┬───────────────┬───────────────┬────────────┘
                                  │ results       │ injury        │ X firehose
                                  │  ≤ 30 s       │  ≤ 60 s       │  ≤ 500 ms
                ┌─────────────────▼─────┐   ┌─────▼─────┐   ┌─────▼───────┐
                │ Adapters (Source.fetch)│   │ Adapters │   │ Social      │
                │ + Great-Expectations   │   │          │   │ Firehose    │
                └─────────┬─────────────┘   └─────┬─────┘   └─────┬───────┘
                          │ (Kafka topics, ≤ 200 ms end-to-end)
                          ▼
                ┌────────────────────────────────────────────────┐
                │ Feature store writer (PIT, idempotent)         │
                │ online: Redis, p99 read < 1 ms                 │
                │ offline: Parquet on S3, daily compaction       │
                └─────────────────┬──────────────────────────────┘
                                  │
       ┌──────────────────────────┼─────────────────────────────────────────┐
       ▼                          ▼                                         ▼
 ┌──────────────┐         ┌────────────────────────┐                ┌──────────────┐
 │ Statistical  │         │ ML training pipeline   │                │ NLP pipeline │
 │ models       │         │ (Prefect, weekly)      │                │  (online)    │
 │  Dixon-Coles │         │  • walk-forward CV     │                │  sentiment   │
 │  Elo/Glicko  │         │  • MLflow logging      │                │  topics       │
 │  Kalman      │         │  • calibration gate    │                │  contagion   │
 │  Hierarch.   │         │  • model registry push │                └──────┬───────┘
 │  HMM, GP     │         └─────────┬──────────────┘                       │
 └──────┬───────┘                   │                                      │
        │                           ▼                                      │
        │                  ┌────────────────────┐                          │
        │                  │ Triton GPU server  │  inference p50 < 10 ms   │
        │                  │  pm_meta_ensemble  │  ◀──────────────────────┘
        │                  └─────────┬──────────┘
        │                            │
        ▼                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │ Monte Carlo simulator (50k sims < 800 ms on A100)        │
   └────────────────────────────────┬─────────────────────────┘
                                    │
                                    ▼
                  ┌────────────────────────────┐
                  │ /forecast API  (FastAPI)   │  served behind ALB
                  │  cold p99 < 50 ms          │
                  └────────────┬───────────────┘
                               ▼
                  ┌────────────────────────────┐
                  │ Observability:             │
                  │ Prometheus/Grafana,        │
                  │ OpenTelemetry traces       │
                  └────────────────────────────┘
```

## Latency budgets per edge

| Edge                                     | p50      | p99      | Notes                          |
| ---------------------------------------- | -------- | -------- | ------------------------------ |
| Source.fetch → Kafka                     | 60 ms    | 200 ms   | adapter + serialisation        |
| Kafka → feature-store writer             | 30 ms    | 100 ms   | consumer lag SLA               |
| Feature-store online read (Redis)        | 0.4 ms   | 1 ms     | hot keys preloaded             |
| Triton inference (batch 32)              | 6 ms     | 18 ms    | dynamic batching 1 ms window   |
| Monte Carlo 50k sims                     | 320 ms   | 760 ms   | A100 40GB, vectorised CuPy     |
| /forecast end-to-end (cold)              | 14 ms    | 48 ms    | excludes 50k MC; uses cached pmf|
| /forecast end-to-end (with sim)          | 380 ms   | 820 ms   | when client requests fresh sim |

## Scaling policies

* Triton: HPA on GPU utilisation > 65 %.
* Feature-store writer: Kafka consumer lag > 5 s triggers replica scale-out.
* Inference API: HPA on RPS and p95 latency.
* Training: scheduled job, on-demand spot instances; 4-hour budget per
  weekly cycle, < $50 at current spot prices (us-east-1, g5.2xlarge).

## Recovery and degraded modes

* If the social firehose is down, the platform falls back to the lexicon
  scorer and flags affected forecasts with `narrative_uncertainty=high`.
* If Triton is unavailable, the FastAPI server uses an in-process
  Dixon-Coles fit as the fallback predictor (declared in
  `serving/api.py`); calibration is degraded but not undefined.
