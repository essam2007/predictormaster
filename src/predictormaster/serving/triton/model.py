"""Triton Python backend entrypoint.

Triton calls `TritonPythonModel.execute` for every batch. This file is
deployed at /opt/triton/models/pm_meta_ensemble/1/model.py.
"""
from __future__ import annotations

# Import inside class init only — Triton's environment is GPU-bound.

class TritonPythonModel:  # pragma: no cover - integration
    def initialize(self, args):
        import json
        import pickle
        from pathlib import Path

        cfg = json.loads(args["model_config"])
        artifact_dir = Path(cfg["parameters"]["artifact_dir"]["string_value"])
        with (artifact_dir / "model.pkl").open("rb") as fh:
            self.model = pickle.load(fh)

    def execute(self, requests):
        import numpy as np
        import triton_python_backend_utils as pb_utils

        responses = []
        for req in requests:
            x = pb_utils.get_input_tensor_by_name(req, "features").as_numpy()
            probs = self.model.predict_proba(x)
            ep = self.model.epistemic_variance(x).reshape(-1, 1)
            responses.append(
                pb_utils.InferenceResponse(
                    output_tensors=[
                        pb_utils.Tensor("probabilities", probs.astype(np.float32)),
                        pb_utils.Tensor("epistemic_var", ep.astype(np.float32)),
                    ]
                )
            )
        return responses

    def finalize(self):
        self.model = None
