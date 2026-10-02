"""
GridSense Delhi - LightGBM Quantile Forecasting Engine
Trains multi-quantile (P10, P50, P90) models per entity.
Walk-forward backtesting. SHAP explanations. Solar net demand adjustment.
"""
import numpy as np
import pandas as pd
import lightgbm as lgb
import logging
import json
import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

QUANTILES = [0.1, 0.5, 0.9]
MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models")
os.makedirs(MODEL_DIR, exist_ok=True)

# LightGBM base params (tuned for Delhi electricity demand patterns)
BASE_PARAMS = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "max_depth": 8,
    "num_leaves": 63,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "n_jobs": -1,
    "verbose": -1,
}


class GridSenseLGBMForecaster:
    """
    LightGBM quantile regression forecaster for a single entity (discom/state).
    Trains three models: P10, P50, P90.
    """

    def __init__(self, entity_code: str):
        self.entity_code = entity_code
        self.models: Dict[float, lgb.LGBMRegressor] = {}
        self.feature_names: List[str] = []
        self.model_version: str = ""
        self.trained_at: Optional[datetime] = None
        self.train_metrics: Dict = {}

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
    ):
        """Train P10, P50, P90 models."""
        self.feature_names = list(X_train.columns)
        self.trained_at = datetime.now(timezone.utc)
        self.model_version = self.trained_at.strftime("%Y%m%d_%H%M%S")

        for q in QUANTILES:
            params = {**BASE_PARAMS, "objective": "quantile", "alpha": q}
            model = lgb.LGBMRegressor(**params)
            eval_set = [(X_val, y_val)] if (X_val is not None and y_val is not None) else None
            model.fit(
                X_train, y_train,
                eval_set=eval_set,
                callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)]
                if eval_set else [lgb.log_evaluation(-1)],
            )
            self.models[q] = model
            logger.info(f"[LGBM] {self.entity_code} Q{int(q*100)} trained with {model.best_iteration_} iters")

        if X_val is not None and y_val is not None:
            self._compute_metrics(X_val, y_val)

        self.save()

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with p10, p50, p90 columns."""
        results = {}
        for q in QUANTILES:
            if q in self.models:
                results[f"p{int(q*100)}"] = self.models[q].predict(X)
        return pd.DataFrame(results, index=X.index)

    def shap_top_features(self, X_row: pd.DataFrame, top_n: int = 5) -> List[Dict]:
        """Compute SHAP values for P50 model, return top N contributors."""
        try:
            import shap
            model = self.models.get(0.5)
            if model is None:
                return []
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(X_row)
            if len(sv.shape) == 1:
                sv = sv.reshape(1, -1)
            mean_abs = np.abs(sv[0])
            feat_importance = sorted(
                zip(self.feature_names, sv[0], mean_abs),
                key=lambda x: x[2], reverse=True
            )
            result = []
            for name, val, abs_val in feat_importance[:top_n]:
                result.append({
                    "feature": name,
                    "shap_value": float(val),
                    "abs_shap": float(abs_val),
                    "direction": "increases_demand" if val > 0 else "decreases_demand",
                    "plain_english": _shap_to_english(name, val, X_row)
                })
            return result
        except Exception as exc:
            logger.warning(f"[SHAP] Failed: {exc}")
            return []

    def _compute_metrics(self, X_val: pd.DataFrame, y_val: pd.Series):
        """Compute validation metrics for P50."""
        preds = self.predict(X_val)
        p50 = np.asarray(preds["p50"], dtype=np.float64)
        actual = np.asarray(y_val, dtype=np.float64)
        mask = actual > 0
        mae = float(np.mean(np.abs(p50[mask] - actual[mask])))
        mape = float(np.mean(np.abs((p50[mask] - actual[mask]) / actual[mask])) * 100)
        rmse = float(np.sqrt(np.mean((p50[mask] - actual[mask]) ** 2)))
        r2 = float(1 - np.sum((actual[mask] - p50[mask])**2) / np.sum((actual[mask] - actual[mask].mean())**2))
        self.train_metrics = {"mae": mae, "mape": mape, "rmse": rmse, "r2": r2}
        logger.info(f"[LGBM] {self.entity_code} val metrics — MAPE:{mape:.2f}% MAE:{mae:.1f}MW RMSE:{rmse:.1f}MW R²:{r2:.4f}")

    def save(self):
        path = os.path.join(MODEL_DIR, f"{self.entity_code}.pkl")
        with open(path, "wb") as f:
            pickle.dump({
                "models": self.models,
                "feature_names": self.feature_names,
                "trained_at": self.trained_at,
                "model_version": self.model_version,
                "train_metrics": self.train_metrics,
            }, f)
        logger.info(f"[LGBM] Model saved: {path}")

    def load(self) -> bool:
        path = os.path.join(MODEL_DIR, f"{self.entity_code}.pkl")
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.models = data["models"]
        self.feature_names = data["feature_names"]
        self.trained_at = data.get("trained_at")
        self.model_version = data.get("model_version", "unknown")
        self.train_metrics = data.get("train_metrics", {})
        logger.info(f"[LGBM] Model loaded: {self.entity_code} v{self.model_version}")
        return True


def _shap_to_english(feature: str, shap_val: float, X_row: pd.DataFrame) -> str:
    """Convert SHAP feature importance to a plain-English sentence."""
    direction = "increased" if shap_val > 0 else "decreased"
    mw = abs(shap_val)
    try:
        val = float(X_row[feature].iloc[0])
    except Exception:
        val = None

    templates = {
        "temperature": f"Temperature {val:.1f}°C {direction} demand by ~{mw:.0f} MW",
        "apparent_temperature": f"Feels-like temperature {val:.1f}°C {direction} demand by ~{mw:.0f} MW",
        "cooling_degree_hours": f"Cooling degree hours ({val:.1f}) {direction} demand by ~{mw:.0f} MW",
        "heat_index": f"Heat index {val:.1f}°C {direction} demand by ~{mw:.0f} MW",
        "is_holiday": f"{'Holiday' if val else 'Workday'} pattern {direction} demand by ~{mw:.0f} MW",
        "is_weekend": f"{'Weekend' if val else 'Weekday'} pattern {direction} demand by ~{mw:.0f} MW",
        "hour_sin": f"Hour of day (peak cycle) {direction} demand by ~{mw:.0f} MW",
        "cloud_cover": f"Cloud cover {val:.0f}% {direction} demand by ~{mw:.0f} MW",
        "shortwave_radiation": f"Solar radiation {val:.0f} W/m² {direction} demand by ~{mw:.0f} MW",
        "lag_24h": f"Yesterday same hour demand ({val:.0f} MW) {direction} today's by ~{mw:.0f} MW",
        "lag_168h": f"Last week same hour demand ({val:.0f} MW) {direction} today's by ~{mw:.0f} MW",
        "roll_mean_24h": f"24-hour rolling mean ({val:.0f} MW) {direction} demand by ~{mw:.0f} MW",
        "is_festival_season": f"Festival season {'boosted' if shap_val > 0 else 'dampened'} demand by ~{mw:.0f} MW",
        "us_aqi": f"Air quality index {val:.0f} {direction} demand by ~{mw:.0f} MW (HVAC/filtering load)",
    }
    if feature in templates:
        return templates[feature]
    return f"{feature.replace('_', ' ').title()} {direction} demand by ~{mw:.0f} MW"


def solar_net_demand(
    gross_demand_mw: float,
    installed_capacity_mw: float,
    ghi_wm2: float,
    cloud_cover_pct: float,
    temperature_c: float,
    gamma: float = 0.004,  # temperature derating coefficient (%/°C)
) -> Dict:
    """
    Calculate rooftop solar generation and net demand.
    Formula: P_solar = C_installed * (GHI/1000) * (1 - gamma*(T-25)) * (1 - 0.75 * cloud^3)
    """
    if ghi_wm2 is None or ghi_wm2 <= 0:
        return {"solar_mw": 0.0, "net_demand_mw": gross_demand_mw, "solar_contribution_pct": 0.0}

    cloud_fraction = (cloud_cover_pct or 0) / 100.0
    temp_factor = 1 - gamma * ((temperature_c or 25) - 25)
    cloud_factor = 1 - 0.75 * cloud_fraction ** 3
    solar_mw = installed_capacity_mw * (ghi_wm2 / 1000) * temp_factor * cloud_factor
    solar_mw = max(0.0, min(solar_mw, installed_capacity_mw))  # clamp
    net_mw = max(0.0, gross_demand_mw - solar_mw)
    solar_pct = (solar_mw / gross_demand_mw * 100) if gross_demand_mw > 0 else 0.0

    return {
        "solar_mw": round(solar_mw, 2),
        "net_demand_mw": round(net_mw, 2),
        "solar_contribution_pct": round(solar_pct, 2),
        "ghi_wm2": ghi_wm2,
        "cloud_cover_pct": cloud_cover_pct,
        "temperature_c": temperature_c,
        "installed_capacity_mw": installed_capacity_mw,
    }


def run_backtest(
    entity_code: str,
    feature_df: pd.DataFrame,
    target: pd.Series,
    n_splits: int = 5,
) -> Dict:
    """
    Walk-forward cross-validation backtesting.
    Returns per-split and overall MAPE, MAE, RMSE.
    """
    results = []
    n = len(feature_df)
    split_size = n // (n_splits + 1)

    for i in range(n_splits):
        train_end = split_size * (i + 1)
        val_end = min(train_end + split_size, n)
        X_tr = feature_df.iloc[:train_end].dropna()
        y_tr = target.iloc[:train_end][X_tr.index]
        X_val = feature_df.iloc[train_end:val_end].dropna()
        y_val = target.iloc[train_end:val_end][X_val.index]

        if len(X_tr) < 50 or len(X_val) < 5:
            continue

        fc = GridSenseLGBMForecaster(f"{entity_code}_backtest")
        fc.train(X_tr, y_tr)
        preds = fc.predict(X_val)
        p50 = np.asarray(preds["p50"], dtype=np.float64)
        actual = np.asarray(y_val, dtype=np.float64)
        mask = actual > 0
        if mask.sum() == 0:
            continue
        mape = float(np.mean(np.abs((p50[mask] - actual[mask]) / actual[mask])) * 100)
        mae = float(np.mean(np.abs(p50[mask] - actual[mask])))
        rmse = float(np.sqrt(np.mean((p50[mask] - actual[mask])**2)))
        results.append({"split": i+1, "mape": mape, "mae": mae, "rmse": rmse, "n_val": int(mask.sum())})

    if results:
        overall_mape = float(np.mean([r["mape"] for r in results]))
        overall_mae  = float(np.mean([r["mae"] for r in results]))
        overall_rmse = float(np.mean([r["rmse"] for r in results]))
        return {"splits": results, "overall_mape": overall_mape, "overall_mae": overall_mae, "overall_rmse": overall_rmse}
    return {"splits": [], "overall_mape": None, "overall_mae": None, "overall_rmse": None}
