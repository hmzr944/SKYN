"""
XGBoost training pipeline.
Trains one model per symbol, validates with walk-forward.
"""
import os
import pickle
import logging
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional

import xgboost as xgb
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from .features import build_features, make_labels

logger = logging.getLogger(__name__)

# XGBoost hyperparameters — tuned for financial time-series
XGB_PARAMS = {
    "n_estimators":    400,
    "max_depth":       5,
    "learning_rate":   0.05,
    "subsample":       0.8,
    "colsample_bytree":0.7,
    "reg_alpha":       0.1,
    "reg_lambda":      1.0,
    "min_child_weight":5,
    "scale_pos_weight":1.2,
    "eval_metric":     "logloss",
    "use_label_encoder": False,
    "random_state":    42,
    "n_jobs":          -1,
}


class ModelBundle:
    def __init__(self, model: xgb.XGBClassifier, scaler: RobustScaler,
                 feature_names: list, train_metrics: dict, symbol: str):
        self.model = model
        self.scaler = scaler
        self.feature_names = feature_names
        self.train_metrics = train_metrics
        self.symbol = symbol

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        feat = build_features(df)
        feat = feat[self.feature_names].fillna(0)
        X = self.scaler.transform(feat)
        return self.model.predict_proba(X)[:, 1]


def train_symbol(
    df: pd.DataFrame,
    symbol: str,
    tp_pct: float = 0.02,
    sl_pct: float = 0.01,
    max_bars: int = 48,
    min_samples: int = 200,
) -> Optional[ModelBundle]:
    """
    Train XGBoost model for one symbol.
    Uses time-series split (no future data leakage).
    """
    if df is None or len(df) < min_samples * 2:
        logger.warning("%s: not enough data (%d rows)", symbol, len(df) if df is not None else 0)
        return None

    feat_df = build_features(df)
    labels  = make_labels(df, tp_pct=tp_pct, sl_pct=sl_pct, max_bars=max_bars)

    # Align and drop NaN
    combined = pd.concat([feat_df, labels.rename("label")], axis=1).dropna()
    if len(combined) < min_samples:
        logger.warning("%s: insufficient clean samples (%d)", symbol, len(combined))
        return None

    feature_names = [c for c in combined.columns if c != "label"]
    X_all = combined[feature_names].values
    y_all = combined["label"].values

    # Time-series split: 80% train, 20% validation (no shuffle!)
    split = int(len(X_all) * 0.8)
    X_train, X_val = X_all[:split], X_all[split:]
    y_train, y_val = y_all[:split], y_all[split:]

    # Scale
    scaler = RobustScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s   = scaler.transform(X_val)

    # Train
    model = xgb.XGBClassifier(**XGB_PARAMS)
    model.fit(
        X_train_s, y_train,
        eval_set=[(X_val_s, y_val)],
        verbose=False,
    )

    # Validate
    val_proba = model.predict_proba(X_val_s)[:, 1]
    val_pred  = (val_proba >= 0.55).astype(int)

    metrics = {
        "accuracy":  round(accuracy_score(y_val, val_pred), 4),
        "precision": round(precision_score(y_val, val_pred, zero_division=0), 4),
        "recall":    round(recall_score(y_val, val_pred, zero_division=0), 4),
        "f1":        round(f1_score(y_val, val_pred, zero_division=0), 4),
        "n_train":   int(split),
        "n_val":     int(len(X_val)),
        "pos_rate":  round(float(y_all.mean()), 4),
    }

    logger.info(
        "%s trained | acc=%.3f prec=%.3f recall=%.3f f1=%.3f | %d/%d samples",
        symbol, metrics["accuracy"], metrics["precision"],
        metrics["recall"], metrics["f1"], split, len(X_all)
    )

    return ModelBundle(model, scaler, feature_names, metrics, symbol)


def save_models(bundles: Dict[str, ModelBundle], path: str):
    os.makedirs(path, exist_ok=True)
    for sym, bundle in bundles.items():
        safe = sym.replace("/", "_").replace("-", "_")
        with open(os.path.join(path, f"{safe}.pkl"), "wb") as f:
            pickle.dump(bundle, f)


def load_models(path: str) -> Dict[str, ModelBundle]:
    bundles = {}
    if not os.path.isdir(path):
        return bundles
    for fname in os.listdir(path):
        if not fname.endswith(".pkl"):
            continue
        with open(os.path.join(path, fname), "rb") as f:
            bundle = pickle.load(f)
        bundles[bundle.symbol] = bundle
    return bundles
