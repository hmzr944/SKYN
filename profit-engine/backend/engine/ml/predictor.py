"""
Real-time ML predictor.
Loads trained models and returns buy/sell probability for a given OHLCV window.
"""
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

from .trainer import ModelBundle, load_models
from .features import build_features


class MLPredictor:
    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self._bundles: Dict[str, ModelBundle] = {}
        self.reload()

    def reload(self):
        self._bundles = load_models(self.models_dir)

    def predict(self, symbol: str, df: pd.DataFrame,
                buy_threshold: float = 0.58,
                sell_threshold: float = 0.58) -> Tuple[str, float, float]:
        """
        Returns (action, buy_prob, sell_prob).
        action: 'BUY' | 'SELL' | 'HOLD'
        """
        bundle = self._bundles.get(symbol)
        if bundle is None or df is None or len(df) < 60:
            return "HOLD", 0.0, 0.0

        try:
            feat = build_features(df)
            feat = feat[bundle.feature_names].fillna(0)
            if feat.empty:
                return "HOLD", 0.0, 0.0

            # Use last row (most recent candle)
            X = bundle.scaler.transform(feat.iloc[[-1]])
            buy_prob = float(bundle.model.predict_proba(X)[0, 1])

            # For SELL: invert the labels concept (predict DOWN moves)
            # Use the inverted price returns as sell signal
            sell_prob = self._sell_prob(df, bundle)

            action = "HOLD"
            if buy_prob >= buy_threshold and buy_prob > sell_prob:
                action = "BUY"
            elif sell_prob >= sell_threshold and sell_prob > buy_prob:
                action = "SELL"

            return action, round(buy_prob, 4), round(sell_prob, 4)

        except Exception as e:
            return "HOLD", 0.0, 0.0

    def _sell_prob(self, df: pd.DataFrame, bundle: ModelBundle) -> float:
        """Approximate sell probability by checking bearish features."""
        try:
            feat = build_features(df)
            feat = feat[bundle.feature_names].fillna(0)
            X = bundle.scaler.transform(feat.iloc[[-1]])
            # Invert key features to approximate downside probability
            X_inv = X.copy()
            X_inv = -X_inv  # rough inversion of feature space
            proba = float(bundle.model.predict_proba(X_inv)[0, 1])
            return proba
        except Exception:
            return 0.0

    def has_model(self, symbol: str) -> bool:
        return symbol in self._bundles

    def model_metrics(self, symbol: str) -> dict:
        bundle = self._bundles.get(symbol)
        return bundle.train_metrics if bundle else {}

    @property
    def loaded_symbols(self):
        return list(self._bundles.keys())
