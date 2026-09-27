"""Baselines. All models share one interface:
    fit(w: Windows) -> self            (uses only w.mask("train") targets; may use w.mask("val") for early stopping)
    predict(w: Windows) -> (N, H, 3)   quantiles (P10, P50, P90) of y = log1p(co2[t+h]) - log1p(co2[t])
Point models get P10/P90 from train-residual empirical quantiles per horizon.
"""
from __future__ import annotations

import warnings

import numpy as np

from src.data.features import HORIZONS, Windows

Q = (0.1, 0.5, 0.9)


class _ResidualBands:
    def _bands(self, w: Windows, p50: np.ndarray) -> None:
        m = w.mask("train")
        r = np.where(m, w.y - p50, np.nan)
        self.lo = np.nanquantile(r, 0.1, axis=0)
        self.hi = np.nanquantile(r, 0.9, axis=0)
        # band must contain the point forecast (a biased point model can have all residuals on one side)
        self.lo = np.minimum(np.nan_to_num(self.lo, nan=-0.05), 0.0)
        self.hi = np.maximum(np.nan_to_num(self.hi, nan=0.05), 0.0)

    def _q(self, p50: np.ndarray) -> np.ndarray:
        return np.stack([p50 + self.lo, p50, p50 + self.hi], -1)


class Naive(_ResidualBands):
    """Random walk: co2[t+h] = co2[t]. (Annual data -> seasonal naive coincides with naive.)"""
    name = "naive"

    def fit(self, w):
        self._bands(w, np.zeros_like(w.y))
        return self

    def predict(self, w):
        return self._q(np.zeros((len(w.y), len(HORIZONS))))


class Drift(_ResidualBands):
    """Random walk with drift = mean log growth over the input window."""
    name = "drift"

    def _p50(self, w):
        slope = np.nanmean(np.diff(w.hist, axis=1), axis=1)
        return np.nan_to_num(slope)[:, None] * np.array(HORIZONS)[None, :]

    def fit(self, w):
        self._bands(w, self._p50(w))
        return self

    def predict(self, w):
        return self._q(self._p50(w))


def _flat(w: Windows, last_k: int = 3) -> np.ndarray:
    """Last k years of features flattened + state one-hot + statics."""
    oh = np.eye(len(w.codes), dtype=np.float32)[w.state]
    parts = [w.X[:, -last_k:, :].reshape(len(w.X), -1), oh, w.static]
    if len(w.sectors) > 1:
        parts.append(np.eye(len(w.sectors), dtype=np.float32)[w.sector])
    return np.hstack(parts)


class RidgePanel(_ResidualBands):
    """Global panel ridge, one model per horizon."""
    name = "ridge"

    def __init__(self, alpha: float = 10.0):
        self.alpha = alpha

    def fit(self, w):
        from sklearn.linear_model import Ridge

        X, m = _flat(w), w.mask("train")
        self.models = [Ridge(alpha=self.alpha).fit(X[m[:, h]], w.y[m[:, h], h]) for h in range(len(HORIZONS))]
        self._bands(w, self._p50(w))
        return self

    def _p50(self, w):
        X = _flat(w)
        return np.stack([mdl.predict(X) for mdl in self.models], 1)

    def predict(self, w):
        return self._q(self._p50(w))


class LightGBMPanel:
    """Global LightGBM with quantile objectives, one booster per (horizon, quantile)."""
    name = "lightgbm"

    def __init__(self, n_estimators: int = 300, learning_rate: float = 0.03, num_leaves: int = 15, seed: int = 42):
        self.kw = dict(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                       min_child_samples=10, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                       random_state=seed, verbose=-1, deterministic=True, force_row_wise=True,
                       n_jobs=1)  # tiny data; multi-threaded libomp deadlocks with torch on macOS

    def _X(self, w):
        return np.hstack([w.X[:, -1, :], w.X[:, -3, :] if w.X.shape[1] >= 3 else w.X[:, 0, :],
                          w.static, w.sector[:, None].astype(np.float32), w.state[:, None].astype(np.float32)])

    def feature_names(self, w):
        return (w.features + [f"{f}_t-2" for f in w.features] + [f"static_{i}" for i in range(w.static.shape[1])]
                + ["sector_id", "state_id"])

    def fit(self, w):
        import lightgbm as lgb

        X, m = self._X(w), w.mask("train")
        self.models = {}
        for h in range(len(HORIZONS)):
            for q in Q:
                self.models[h, q] = lgb.LGBMRegressor(objective="quantile", alpha=q, **self.kw).fit(
                    X[m[:, h]], w.y[m[:, h], h], categorical_feature=[X.shape[1] - 2, X.shape[1] - 1])
        return self

    def predict(self, w):
        X = self._X(w)
        out = np.stack([np.stack([self.models[h, q].predict(X) for q in Q], -1) for h in range(len(HORIZONS))], 1)
        return np.sort(out, -1)  # enforce non-crossing quantiles


class LightGBMPerSector:
    """One LightGBMPanel per sector (spec: 'LightGBM per sector'); rows of other sectors are never seen."""
    name = "lightgbm_sector"

    def __init__(self, **kw):
        self.kw = kw

    def fit(self, w):
        self.models = {k: LightGBMPanel(**self.kw).fit(w.subset(np.flatnonzero(w.sector == k))) for k in np.unique(w.sector)}
        return self

    def predict(self, w):
        out = np.zeros((len(w.y), len(HORIZONS), 3))
        for k, m in self.models.items():
            sel = np.flatnonzero(w.sector == k)
            if len(sel):
                out[sel] = m.predict(w.subset(sel))
        return out


class ARIMAPerState:
    """ARIMA(1,1,0) with drift on log CO2, refit per (state, origin) — top-N emitters only (compute cost)."""
    name = "arima"

    def __init__(self, df, top_n: int = 10):
        self.df, self.top_n = df, top_n

    def fit(self, w):
        tr = self.df[self.df.year <= 2014]
        self.states = set(tr.groupby("state_code").co2_mt.mean().nlargest(self.top_n).index)
        return self

    def predict(self, w):
        from statsmodels.tsa.arima.model import ARIMA

        H = len(HORIZONS)
        out = np.full((len(w.y), H, 3), np.nan)
        series = {c: g.set_index("year").co2_mt for c, g in self.df.groupby("state_code")}
        for i in range(len(w.y)):
            code = w.codes[w.state[i]]
            if code not in self.states:
                continue
            s = np.log1p(series[code].loc[: w.origin[i]].dropna())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = ARIMA(s.to_numpy(), order=(1, 1, 0), trend="t").fit().get_forecast(H)
            mu, ci = fc.predicted_mean, fc.conf_int(alpha=0.2)
            out[i] = np.stack([ci[:, 0], mu, ci[:, 1]], -1) - s.iloc[-1]
        return out
