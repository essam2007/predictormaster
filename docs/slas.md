# Service-Level Agreements

| Component              | Refresh        | Latency budget | Severity | Owner |
| ---------------------- | -------------- | -------------- | -------- | ----- |
| match_results          | 1 min          | 30 s           | critical | DE    |
| injury_reports         | 30 s           | 60 s           | critical | DE    |
| weather                | 10 min         | 15 s           | warning  | DE    |
| public_consensus       | 15 s           | 20 s           | critical | DE    |
| social_firehose        | continuous     | 500 ms p95     | critical | DE    |
| feature-store online   | continuous     | 1 ms p99       | critical | Platform |
| Triton inference       | continuous     | 10 ms p50      | critical | Platform |
| /forecast API (cold)   | continuous     | 50 ms p99      | critical | Platform |
| Weekly retrain         | 168 h          | 4 h            | warning  | Research |
| Calibration audit      | 24 h           | 5 min          | critical | Research |

## Signal half-lives (drives retrain frequency)

| Signal class           | Estimated half-life | Retrain trigger      |
| ---------------------- | ------------------- | -------------------- |
| Latent team strength   | 30–40 days (NBA)    | weekly               |
| Player form (tennis)   | 7–10 days           | daily online updates |
| Injury contagion       | hours               | streaming online     |
| Lineup news            | minutes             | streaming online     |
| Sentiment polarity     | 24–48 hours         | streaming aggregate  |

These figures inform the Ornstein-Uhlenbeck calibration in
`docs/derivations/ou_strength.md` and the cadence of the Prefect
schedules.
