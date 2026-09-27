"""Optuna tuning on validation MASE: `python -m src.train.tune --models lstm,tft --trials 30`.
Writes configs/tuned/<model>.yaml (picked up automatically by src.train.run). Seeded TPE sampler."""
from __future__ import annotations

import argparse

import optuna
import yaml

from src.data.cache import ROOT
from src.data.features import build, make_windows
from src.train.run import DEEP, load_config, make_model


def objective(name, df, seed):
    def f(trial):
        window = trial.suggest_categorical("window", [6, 8, 10])
        p = {"lr": trial.suggest_float("lr", 1e-4, 5e-3, log=True),
             "hidden": trial.suggest_categorical("hidden", [16, 32, 64, 128]),
             "n_layers": trial.suggest_int("n_layers", 1, 3),
             "dropout": trial.suggest_float("dropout", 0.2, 0.4),
             "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True),
             "max_epochs": 200, "patience": 20}
        w, _ = make_windows(df, window)
        m = make_model(name, p, df, seed).fit(w)
        return m.best_val_mase
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEEP))
    ap.add_argument("--trials", type=int, default=30)
    a = ap.parse_args()
    cfg = load_config()
    df, _, _ = build(cfg["window"])
    out = ROOT / "configs" / "tuned"
    out.mkdir(parents=True, exist_ok=True)
    for name in a.models.split(","):
        study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=cfg["seed"]))
        study.optimize(objective(name, df, cfg["seed"]), n_trials=a.trials)
        best = dict(study.best_params)
        best.pop("window")  # window is global; reported for reference
        (out / f"{name}.yaml").write_text(yaml.safe_dump({**best, "best_val_mase": study.best_value,
                                                          "best_window": study.best_params["window"]}))
        print(name, study.best_value, study.best_params)


if __name__ == "__main__":
    main()
