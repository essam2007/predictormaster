"""Gradient boosting ensemble (XGBoost + LightGBM) with monotonicity hints
and SHAP integration. Importable without xgboost/lightgbm; methods that need
them raise a clear error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:  # optional
    import xgboost as xgb
except Exception:  # pragma: no cover
    xgb = None
try:
    import lightgbm as lgb
except Exception:  # pragma: no cover
    lgb = None
try:
    import shap
except Exception:  # pragma: no cover
    shap = None


@dataclass
class GBMEnsemble:
    """Average of an XGBoost and a LightGBM classifier."""

    xgb_params: dict[str, Any] = field(default_factory=lambda: {
        "objective": "multi:softprob",
        "num_class": 3,
        "max_depth": 6,
        "eta": 0.05,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "min_child_weight": 3,
        "reg_lambda": 1.0,
        "tree_method": "hist",
    })
    lgb_params: dict[str, Any] = field(default_factory=lambda: {
        "objective": "multiclass",
        "num_class": 3,
        "num_leaves": 63,
        "learning_rate": 0.05,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "min_data_in_leaf": 20,
        "lambda_l2": 1.0,
    })
    monotone_constraints: dict[str, int] = field(default_factory=dict)
    n_rounds: int = 800
    early_stopping_rounds: int = 50
    xgb_model: Any = None
    lgb_model: Any = None
    feature_names: list[str] = field(default_factory=list)

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list[str], X_val: np.ndarray, y_val: np.ndarray) -> None:
        if xgb is None or lgb is None:
            raise RuntimeError("xgboost and lightgbm must be installed for GBMEnsemble.fit")
        self.feature_names = feature_names
        if self.monotone_constraints:
            mc = "(" + ",".join(str(self.monotone_constraints.get(f, 0)) for f in feature_names) + ")"
            self.xgb_params["monotone_constraints"] = mc
        dtrain = xgb.DMatrix(X, label=y, feature_names=feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)
        self.xgb_model = xgb.train(
            self.xgb_params,
            dtrain,
            num_boost_round=self.n_rounds,
            evals=[(dval, "val")],
            early_stopping_rounds=self.early_stopping_rounds,
            verbose_eval=False,
        )
        ltrain = lgb.Dataset(X, label=y, feature_name=feature_names)
        lval = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=ltrain)
        self.lgb_model = lgb.train(
            self.lgb_params,
            ltrain,
            num_boost_round=self.n_rounds,
            valid_sets=[lval],
            callbacks=[lgb.early_stopping(self.early_stopping_rounds), lgb.log_evaluation(0)],
        )

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.xgb_model is None or self.lgb_model is None:
            raise RuntimeError("call fit() first")
        p_xgb = self.xgb_model.predict(xgb.DMatrix(X, feature_names=self.feature_names))
        p_lgb = self.lgb_model.predict(X)
        return 0.5 * (p_xgb + p_lgb)

    def shap_values(self, X: np.ndarray) -> np.ndarray:
        if shap is None or self.xgb_model is None:
            raise RuntimeError("shap and a fitted xgb_model required")
        explainer = shap.TreeExplainer(self.xgb_model)
        return explainer.shap_values(X)
