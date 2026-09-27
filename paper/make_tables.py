"""Regenerate paper/tables/*.tex from results/ (run after training): `python paper/make_tables.py`."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "tables"
OUT.mkdir(exist_ok=True)
m = pd.read_csv(ROOT / "results" / "tables" / "metrics.csv")
a = m[(m.state_code == "ALL") & m.horizon.isin([1, 3, 5]) & ((m.level == "state") if "level" in m else True)]
NAMES = {"naive": "Naive (RW)", "drift": "RW + drift", "ridge": "Ridge (panel)", "lightgbm": "LightGBM (panel)",
         "arima": "ARIMA$^\\dagger$", "lstm": "LSTM + emb.", "gru": "GRU + emb.", "tcn": "TCN + emb.",
         "seq2seq_attn": "Seq2Seq-Attn", "tft": "TFT-lite", "deepar": "DeepAR-style"}

for split in ("val", "test"):
    t = a[a.split == split].pivot_table(index="model", columns="horizon", values=["mase", "reconciled_mase", "smape"])
    t = t.sort_values(("mase", 5))
    best = {h: t[("mase", h)].min() for h in (1, 3, 5)}
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"Model & MASE$_1$ & MASE$_3$ & MASE$_5$ & MinT MASE$_5$ & sMAPE$_5$ \\", r"\midrule"]
    for mdl, r in t.iterrows():
        cell = lambda h: (f"\\textbf{{{r[('mase', h)]:.2f}}}" if r[("mase", h)] == best[h] else f"{r[('mase', h)]:.2f}")  # noqa: E731
        lines.append(f"{NAMES.get(mdl, mdl)} & {cell(1)} & {cell(3)} & {cell(5)} & "
                     f"{r[('reconciled_mase', 5)]:.2f} & {r[('smape', 5)]:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / f"leaderboard_{split}.tex").write_text("\n".join(lines) + "\n")

imp = sorted((ROOT / "results" / "tables").glob("importance_*.csv"))
if imp:
    d = pd.concat(pd.read_csv(p) for p in imp).pivot_table(index="group", columns="model", values="importance")
    cols = list(d.columns)
    lines = [r"\begin{tabular}{l" + "r" * len(cols) + "}", r"\toprule",
             "Group & " + " & ".join(NAMES.get(c, c) for c in cols) + r" \\", r"\midrule"]
    lines += [f"{g} & " + " & ".join(f"{v:.3f}" for v in r) + r" \\" for g, r in d.iterrows()]
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "importance.tex").write_text("\n".join(lines) + "\n")
print("wrote", sorted(p.name for p in OUT.glob("*.tex")))

# ---- v2: state x sector ---------------------------------------------------------------------------------
NAMES.update({"lightgbm_sector": "LightGBM (per sector)", "mt_gru": "MT-GRU (ours)", "mt_tft": "MT-TFT (ours)"})
if "level" in m:
    s = m[(m.level == "state_sector") & (m.state_code == "ALL") & (m.sector == "ALL") & (m.split == "test") & m.horizon.isin([1, 3, 5])]
    if len(s):
        t = s.pivot_table(index="model", columns="horizon", values=["mase", "reconciled_mase"]).sort_values(("reconciled_mase", 5))
        best = {h: t[("reconciled_mase", h)].min() for h in (1, 3, 5)}
        lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
                 r" & \multicolumn{3}{c}{MASE (unreconciled)} & \multicolumn{3}{c}{MASE (two-level MinT)} \\",
                 r"Model & $h{=}1$ & $h{=}3$ & $h{=}5$ & $h{=}1$ & $h{=}3$ & $h{=}5$ \\", r"\midrule"]
        for mdl, r in t.iterrows():
            rc = [(f"\\textbf{{{r[('reconciled_mase', h)]:.2f}}}" if r[("reconciled_mase", h)] == best[h] else f"{r[('reconciled_mase', h)]:.2f}") for h in (1, 3, 5)]
            lines.append(f"{NAMES.get(mdl, mdl)} & " + " & ".join(f"{r[('mase', h)]:.2f}" for h in (1, 3, 5)) + " & " + " & ".join(rc) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}"]
        (OUT / "leaderboard_sector_test.tex").write_text("\n".join(lines) + "\n")
        per = m[(m.level == "state_sector") & (m.state_code == "ALL") & (m.sector != "ALL") & (m.split == "test") & (m.horizon == 5)]
        p = per.pivot_table(index="sector", columns="model", values="reconciled_mase")
        cols = [c for c in ("naive", "lightgbm", "gru", "tft", "mt_gru", "mt_tft") if c in p]
        lines = [r"\begin{tabular}{l" + "r" * len(cols) + "}", r"\toprule", "Sector & " + " & ".join(NAMES.get(c, c) for c in cols) + r" \\", r"\midrule"]
        lines += [f"{sec.title()} & " + " & ".join(f"{p.loc[sec, c]:.2f}" for c in cols) + r" \\" for sec in p.index]
        lines += [r"\bottomrule", r"\end{tabular}"]
        (OUT / "sector_by_sector_h5.tex").write_text("\n".join(lines) + "\n")
ex_p = ROOT / "results" / "tables" / "experiments.csv"
if ex_p.exists():
    ex = pd.read_csv(ex_p)
    ex = ex[ex.horizon.isin([1, 3, 5])]
    for e in ("E10", "E11", "E12", "E14"):
        d = ex[ex.experiment == e].pivot_table(index=["model", "variant"], columns="horizon", values="mase")
        if d.empty:
            continue
        lines = [r"\begin{tabular}{llrrr}", r"\toprule", r"Model & Variant & $h{=}1$ & $h{=}3$ & $h{=}5$ \\", r"\midrule"]
        lines += [f"{NAMES.get(i[0], i[0])} & {i[1].replace('_', ' ')} & " + " & ".join(f"{r.get(h, float('nan')):.2f}" for h in (1, 3, 5)) + r" \\"
                  for i, r in d.iterrows()]
        lines += [r"\bottomrule", r"\end{tabular}"]
        (OUT / f"{e.lower()}.tex").write_text("\n".join(lines) + "\n")
print("wrote", sorted(p.name for p in OUT.glob("*.tex")))
