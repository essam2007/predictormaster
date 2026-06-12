"""ONNX export helpers for tree models so we can serve via the Triton
ONNX runtime backend instead of the Python backend, removing a Python
interpreter from the hot path.

`onnxmltools` and `skl2onnx` are imported lazily; the absence of either
raises a clear error at call time rather than failing at import. This
keeps the rest of the package install-free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def export_xgb_to_onnx(model: Any, n_features: int, out_path: Path) -> Path:
    """Convert an XGBoost booster to ONNX. Requires `onnxmltools` and
    `onnxconverter_common`.
    """
    try:
        import onnxmltools
        from onnxconverter_common.data_types import FloatTensorType
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "Install onnxmltools + onnxconverter_common to export XGBoost models to ONNX"
        ) from exc

    initial_type = [("features", FloatTensorType([None, n_features]))]
    onnx_model = onnxmltools.convert_xgboost(model, initial_types=initial_type)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        fh.write(onnx_model.SerializeToString())
    return out_path


def export_lgbm_to_onnx(model: Any, n_features: int, out_path: Path) -> Path:
    """Convert a LightGBM booster to ONNX via `onnxmltools`."""
    try:
        import onnxmltools
        from onnxconverter_common.data_types import FloatTensorType
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Install onnxmltools + onnxconverter_common to export LightGBM models to ONNX"
        ) from exc

    initial_type = [("features", FloatTensorType([None, n_features]))]
    onnx_model = onnxmltools.convert_lightgbm(model, initial_types=initial_type)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        fh.write(onnx_model.SerializeToString())
    return out_path


def verify_logit_equality(
    *,
    py_predict_proba,
    onnx_path: Path,
    X: np.ndarray,  # type: ignore[name-defined]  # noqa: F821
    rtol: float = 1e-4,
    atol: float = 1e-5,
) -> bool:
    """Run both the Python-backend predictor and the ONNX runtime on the
    same input and confirm logit-level equality. Returns True on match.
    """
    try:
        import numpy as np
        import onnxruntime as ort
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Install onnxruntime to verify ONNX logit equality"
        ) from exc
    py = py_predict_proba(X)
    sess = ort.InferenceSession(str(onnx_path))
    feed = {sess.get_inputs()[0].name: X.astype(np.float32)}
    out = sess.run(None, feed)[0]
    return bool(np.allclose(py, out, rtol=rtol, atol=atol))
