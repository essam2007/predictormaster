# Runbook: Tuning Triton Dynamic Batching

## When to run

* Whenever inference p95 latency exceeds the SLA in `docs/slas.md`.
* After deploying a new model version that changes the inference graph.
* Quarterly, as a baseline maintenance task.

## Inputs

* `TRITON_URL` exported (gRPC port; `localhost:8001` locally,
  `pm-triton:8001` inside the cluster).
* The model under test must be live in the registry.
* A representative input size — the script's `--feature-dim` flag
  defaults to 64.

## Procedure

1. Sweep four dynamic-batching delays:

   ```bash
   for d in 500 1000 2000 5000; do
     # edit serving/triton/config.pbtxt -> max_queue_delay_microseconds
     # redeploy the model
     python infra/bench_triton.py \
       --triton "$TRITON_URL" \
       --qps   2000 \
       --duration 60 \
       --concurrency 16
   done
   ```

   Record `(p95, throughput)` for each delay value.

2. Pick the smallest delay whose p95 stays below the SLA target at the
   target throughput. Increasing the delay raises p95 monotonically but
   trades for higher throughput; the elbow is usually 1000 µs.

3. Commit the chosen value into
   `src/predictormaster/serving/triton/config.pbtxt`, redeploy.

4. Verify post-change with one more run of `bench_triton.py` and
   attach the JSON output to the incident / change ticket.

## Switching the tree-model backend

For `pm_meta_ensemble` the XGBoost / LightGBM members benefit from the
ONNX backend. To switch:

1. Export with
   `predictormaster.serving.triton.onnx_export.export_xgb_to_onnx`.
2. Replace `platform: "python"` with `platform: "onnxruntime_onnx"` in
   `config.pbtxt` and update the `instance_group` to reflect actual
   GPU/CPU availability.
3. Run
   `verify_logit_equality(py_predict_proba=..., onnx_path=..., X=golden_set)`
   on a 10k-row golden set; require equality at `rtol=1e-4, atol=1e-5`.
4. Re-run the dynamic-batching sweep — the elbow shifts left because
   the per-request CPU time drops.

## Rollback

The previous `config.pbtxt` lives in git history; revert and redeploy.
There is no schema change associated with batching tuning.
