"""Feature engineering + leakage-safe panel windows.

Split rule (enforced here, tested in tests/test_leakage.py): a (sample, horizon) pair belongs to the split of
its TARGET year: train <= 2014, val 2015-2019, test >= 2020. Inputs may reach back into earlier years (that is
information available at forecast time). Every fitted statistic (scalers, winsor bounds, income tiers,
MASE scale) uses rows with year <= TRAIN_END only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED

TARGET = "co2_mt"
TRAIN_END, VAL_END = 2014, 2019
HORIZONS = (1, 2, 3, 4, 5)
REPORT_HORIZONS = (1, 3, 5)
WINDOW = 10

FEATURE_GROUPS: dict[str, list[str]] = {
    "energy": ["edgar_power_mt", "coal_generation_gwh", "gas_generation_gwh", "hydro_generation_gwh",
               "nuclear_generation_gwh", "renewable_share_pct", "grid_emission_factor", "coal_dependence",
               "electricity_consumption_gwh", "per_capita_electricity_kwh", "tnd_losses_pct", "cea_available"],
    "economy": ["gsdp_const_cr", "gsdp_growth_pct", "industry_share_pct", "manufacturing_share_pct",
                "construction_share_pct", "edgar_industry_mt", "edgar_cement_mt", "gsdp_imputed"],
    "demography": ["population_mn", "urban_population_pct", "population_density"],
    "transport": ["edgar_road_mt", "road_share", "highway_length_km", "diesel_sales_kt", "petrol_sales_kt"],
    "climate": ["avg_temp_c", "cooling_degree_days", "heating_degree_days", "monsoon_rainfall_mm", "drought_year"],
    "policy": ["covid_dummy", "lockdown_stringency", "renewable_target_dummy", "ev_policy_dummy",
               "ujala_led_dummy", "pat_scheme_dummy", "nsm_phase", "ndc_phase"],
    "history": ["co2_log", "co2_lag1", "co2_lag3", "co2_lag5", "co2_rolling_mean_5y", "co2_growth_yoy",
                "carbon_intensity", "per_capita_co2", "edgar_buildings_mt"],
}
# "known future" covariates for TFT decoder (deterministic calendars/policies)
KNOWN_FUTURE = ["covid_dummy", "renewable_target_dummy", "ujala_led_dummy", "pat_scheme_dummy", "nsm_phase", "ev_policy_dummy",
                "ndc_phase"]
LOG1P = ["co2_mt", "edgar_power_mt", "edgar_industry_mt", "edgar_road_mt", "edgar_cement_mt", "edgar_buildings_mt",
         "coal_generation_gwh", "gas_generation_gwh", "hydro_generation_gwh", "nuclear_generation_gwh",
         "gsdp_const_cr", "population_mn", "population_density", "electricity_consumption_gwh", "highway_length_km",
         "diesel_sales_kt", "petrol_sales_kt", "pol_sales_kt",
         "co2_lag1", "co2_lag3", "co2_lag5", "co2_rolling_mean_5y"]
REGIONS = ["North", "Central", "East", "West", "South", "Northeast"]


def split_of(year) -> np.ndarray:
    y = np.asarray(year)
    return np.where(y <= TRAIN_END, "train", np.where(y <= VAL_END, "val", "test"))


def load_panel() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "india_states_panel.parquet")


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Derived features. Target-derived features use only past values (shift >= 1)."""
    df = df.sort_values(["state_code", "year"]).copy()
    # any source may be unavailable (download failure / manual RBI files absent) -> NaN columns, not crashes
    for c in ("edgar_power_mt", "edgar_road_mt", "edgar_industry_mt", "edgar_cement_mt", "edgar_buildings_mt",
              "hydro_generation_gwh", "nuclear_generation_gwh", "coal_generation_gwh", "gas_generation_gwh",
              "gsdp_cr", "gsdp_const_cr", "population_mn", *KNOWN_FUTURE):
        if c not in df:
            df[c] = np.nan
    g = df.groupby("state_code")
    co2 = df[TARGET]
    df["co2_log"] = np.log1p(co2)
    df["co2_lag1"] = g[TARGET].shift(1)
    df["co2_lag3"] = g[TARGET].shift(3)
    df["co2_lag5"] = g[TARGET].shift(5)
    df["co2_rolling_mean_5y"] = g[TARGET].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["co2_growth_yoy"] = g[TARGET].pct_change(fill_method=None) * 100
    df["per_capita_co2"] = co2 / df.population_mn  # tCO2/person (Mt/mn)
    df["carbon_intensity"] = co2 * 1e6 / df.gsdp_const_cr  # tCO2 per ₹ crore (2011-12 prices)
    df["gsdp_growth_pct"] = g.gsdp_const_cr.pct_change(fill_method=None) * 100
    df["coal_dependence"] = df.edgar_power_mt / co2
    df["road_share"] = df.edgar_road_mt / co2
    gen = df.filter(like="_generation_gwh").sum(axis=1, min_count=1)
    # CEA baseline DB covers conventional grid plants only -> share of large hydro+nuclear (non-fossil) in that fleet
    df["renewable_share_pct"] = 100 * df[["hydro_generation_gwh", "nuclear_generation_gwh"]].sum(axis=1, min_count=1) / gen
    for num, col in (("industry_gsva_cr", "industry_share_pct"), ("manufacturing_gsva_cr", "manufacturing_share_pct"),
                     ("construction_gsva_cr", "construction_share_pct")):
        df[col] = 100 * df[num] / df.gsdp_cr if num in df else np.nan
    for cols in FEATURE_GROUPS.values():
        for c in cols:
            if c not in df:
                df[c] = np.nan
    # income tier from train-period per-capita GSDP (terciles) — data-driven stand-in for RBI categories
    pc = (df.gsdp_const_cr / df.population_mn)[df.year <= TRAIN_END].groupby(df.state_code).mean()
    tiers = pd.qcut(pc.rank(method="first"), 3, labels=["low", "middle", "high"])
    df["income_group"] = df.state_code.map(tiers).astype(str)
    df["census_region"] = df.region
    return df


@dataclass
class Prep:
    """Train-fitted transforms: log1p, winsor bounds (1/99%), mean/std, median fill."""
    features: list[str]
    lo: pd.Series = field(default=None)
    hi: pd.Series = field(default=None)
    mu: pd.Series = field(default=None)
    sd: pd.Series = field(default=None)
    log_cols: tuple[str, ...] = tuple(LOG1P)

    def _log(self, X: pd.DataFrame) -> pd.DataFrame:
        X = X.astype(float)
        for c in X.columns.intersection(list(self.log_cols)):
            X[c] = np.log1p(X[c].clip(lower=0))
        return X

    def fit(self, df: pd.DataFrame) -> Prep:
        tr = self._log(df.loc[df.year <= TRAIN_END, self.features])
        self.lo, self.hi = tr.quantile(0.01), tr.quantile(0.99)
        tr = tr.clip(self.lo, self.hi, axis=1)
        self.mu, self.sd = tr.mean().fillna(0), tr.std().replace(0, 1).fillna(1)
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        X = self._log(df[self.features]).clip(self.lo, self.hi, axis=1)
        X = (X - self.mu) / self.sd
        return X.fillna(0.0).to_numpy(np.float32)  # 0 == train mean; missingness carried by *_missing columns


def feature_list(df: pd.DataFrame) -> list[str]:
    base = [c for cols in FEATURE_GROUPS.values() for c in cols]
    miss = [c for c in df.columns if c.endswith("_missing")]
    tr = df[df.year <= TRAIN_END]
    return [c for c in dict.fromkeys(base + miss) if c in df and tr[c].notna().any() and tr[c].nunique() > 1]


@dataclass
class Windows:
    X: np.ndarray          # (N, W, F) scaled features
    fut: np.ndarray        # (N, H, K) known-future covariates for target years
    state: np.ndarray      # (N,) state index
    static: np.ndarray     # (N, S) region one-hot + coastal + is_ut + income tier
    y: np.ndarray          # (N, H) log1p(v[t+h]) - log1p(v[t])   (NaN where unavailable)
    base: np.ndarray       # (N,) log1p(v[t])
    origin: np.ndarray     # (N,) origin year t
    codes: list[str]       # state codes (index = state)
    features: list[str]
    scale: np.ndarray      # (N,) per-unit MASE scale on log level (train naive-1 MAE)
    hist: np.ndarray       # (N, W) raw log1p(v) over the input window (for drift / plots)
    final: bool = False    # production refit: train on ALL observed targets, monitor the last 3 target years
    sector: np.ndarray | None = None      # (N,) sector index (v2 state x sector panel); None -> single "TOTAL"
    sectors: tuple[str, ...] = ("TOTAL",)

    def __post_init__(self):
        if self.sector is None:
            self.sector = np.zeros(len(self.state), dtype=int)

    @property
    def unit(self) -> np.ndarray:
        """(N,) index of the forecast series = state * n_sectors + sector."""
        return self.state * len(self.sectors) + self.sector

    def target_years(self) -> np.ndarray:
        return self.origin[:, None] + np.array(HORIZONS)[None, :]

    def mask(self, split: str) -> np.ndarray:
        """(N, H) bool: targets that exist and fall in `split` by target year."""
        ty, ok = self.target_years(), ~np.isnan(self.y)
        if self.final:
            last = ty[ok].max()
            return ok & ((ty <= last - 3) if split == "train" else (ty > last - 3) if split == "val" else False)
        return (split_of(ty) == split) & ok

    def subset(self, idx) -> Windows:
        return Windows(self.X[idx], self.fut[idx], self.state[idx], self.static[idx], self.y[idx], self.base[idx],
                       self.origin[idx], self.codes, self.features, self.scale[idx], self.hist[idx], self.final,
                       self.sector[idx] if self.sector is not None else None, self.sectors)


def static_matrix(df: pd.DataFrame, codes: list[str]) -> np.ndarray:
    s = df.drop_duplicates("state_code").set_index("state_code").loc[codes]
    reg = np.stack([(s.region == r).to_numpy(float) for r in REGIONS], 1)
    inc = s.income_group.map({"low": 0.0, "middle": 0.5, "high": 1.0}).fillna(0.5).to_numpy()[:, None]
    return np.hstack([reg, s.coastal.to_numpy(float)[:, None], s.is_ut.to_numpy(float)[:, None], inc]).astype(np.float32)


def make_windows(df: pd.DataFrame, window: int = WINDOW, prep: Prep | None = None, target: str = TARGET,
                 features: list[str] | None = None, sectors: tuple[str, ...] | None = None,
                 log_cols: list[str] | None = None) -> tuple[Windows, Prep]:
    """One sample per (unit, origin year t); unit = state, or (state, sector) when `sectors` is given and df has a
    `sector` column. Origins near the panel end carry NaN targets (used for forecasting)."""
    keys = ["state_code", "sector"] if sectors else ["state_code"]
    df = df.sort_values([*keys, "year"]).reset_index(drop=True)
    feats = features or feature_list(df)
    prep = prep or Prep(feats, log_cols=tuple(log_cols) if log_cols else tuple(LOG1P)).fit(df)
    Xall = prep.transform(df)
    fut_all = df[KNOWN_FUTURE].fillna(0).to_numpy(np.float32)
    codes = sorted(df.state_code.unique())
    secs = tuple(sectors) if sectors else ("TOTAL",)
    stat = static_matrix(df, codes)
    H = max(HORIZONS)
    out: dict[str, list] = {k: [] for k in ("X", "fut", "state", "sector", "static", "y", "base", "origin", "scale", "hist")}
    st_arr = df.state_code.to_numpy()
    se_arr = df.sector.to_numpy() if sectors else None
    for si, code in enumerate(codes):
        for ki, sec in enumerate(secs):
            sel = st_arr == code if se_arr is None else (st_arr == code) & (se_arr == sec)
            idx = np.flatnonzero(sel)
            years = df.year.to_numpy()[idx]
            ylog = np.log1p(df[target].to_numpy()[idx].clip(min=0))
            tr = ylog[years <= TRAIN_END]
            scale = np.nanmean(np.abs(np.diff(tr))) if len(tr) > 2 else np.nan
            scale = scale if np.isfinite(scale) and scale > 1e-6 else max(0.05 * float(np.nanmean(tr)) if len(tr) else 0, 1e-4)
            last = len(idx) - 1
            for j in range(window - 1, len(idx)):
                if np.isnan(ylog[j]):
                    continue
                tgt = np.full(H, np.nan)
                fut = np.zeros((H, len(KNOWN_FUTURE)), np.float32)
                for h in range(1, H + 1):
                    if j + h <= last:
                        tgt[h - 1] = ylog[j + h] - ylog[j]
                        fut[h - 1] = fut_all[idx[j + h]]
                    else:  # beyond panel: carry last known policy state (calendar dummies extend deterministically)
                        fut[h - 1] = fut_all[idx[last]]
                        fut[h - 1, 0] = 0.0  # covid_dummy
                out["X"].append(Xall[idx[j - window + 1: j + 1]])
                out["fut"].append(fut)
                out["state"].append(si)
                out["sector"].append(ki)
                out["static"].append(stat[si])
                out["y"].append(tgt)
                out["base"].append(ylog[j])
                out["origin"].append(years[j])
                out["scale"].append(scale)
                out["hist"].append(ylog[j - window + 1: j + 1])
    w = Windows(np.stack(out["X"]), np.stack(out["fut"]), np.array(out["state"]), np.stack(out["static"]),
                np.stack(out["y"]).astype(np.float32), np.array(out["base"]), np.array(out["origin"]),
                codes, feats, np.array(out["scale"]), np.stack(out["hist"]), False, np.array(out["sector"]), secs)
    return w, prep


def build(window: int = WINDOW) -> tuple[pd.DataFrame, Windows, Prep]:
    df = engineer(load_panel())
    w, prep = make_windows(df, window)
    return df, w, prep
