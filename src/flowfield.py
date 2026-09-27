"""Emission 'mass-flow' direction field for the Windy-style particle layer: `python -m src.flowfield`.

For the latest year and each sector (+ TOTAL), CO2e grids (EDGAR 0.1°, AR6 GWP-100) are coarsened to 0.2°,
log-transformed and Gaussian-smoothed; the flow is the down-gradient of that surface (emissions spreading out of
dense source clusters) plus a rotational term (90° rotated gradient, weight 0.9) so streams curl around sources instead of
radiating straight out. Speed ∝ smoothed local intensity. This is a visual encoding of emission density — it is NOT
atmospheric transport or wind.
Output: results/flow_field.json {sector: {bbox, nx, ny, res, u, v, s, dom}} with u/v/s quantised to int8/uint8.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.ndimage import gaussian_filter

from src.data import edgar
from src.data.cache import ROOT
from src.data.sectors import BIO, GWP, MAP, SECTORS

RES_DEG = 0.2


def sector_grids(year: int) -> dict[str, np.ndarray]:
    grids: dict[str, np.ndarray] = {}
    lat = lon = None
    for sector, spec in MAP.items():
        acc = None
        for gas, subs in spec.items():
            for sub in subs:
                try:
                    arr, da = edgar._nc(sub, year, gas)
                except RuntimeError:
                    continue
                lat, lon = da.lat.values, da.lon.values
                f = 1.0 if gas == "CO2" else GWP["N2O"] if gas == "N2O" else GWP["CH4_bio"] if sector in BIO else GWP["CH4_fossil"]
                acc = arr * f if acc is None else acc + arr * f
        if acc is not None:
            grids[sector] = acc
    grids["TOTAL"] = sum(grids.values())  # CO2e of all mapped sources
    grids["_lat"], grids["_lon"] = lat, lon
    return grids


def coarsen(a: np.ndarray, k: int = 2) -> np.ndarray:
    ny, nx = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    return a[:ny, :nx].reshape(ny // k, k, nx // k, k).sum((1, 3))


def field(E: np.ndarray, sigma: float = 3.0, swirl: float = 0.9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    L = gaussian_filter(np.log1p(E / 1e3), sigma)          # kt per cell -> log surface
    gy, gx = np.gradient(L)
    u, v = -gx + swirl * gy, -gy - swirl * gx               # downhill + 90° rotation (lat axis increases northwards)
    mag = np.hypot(u, v) + 1e-9
    s = gaussian_filter(np.log1p(E / 1e3), 1.0)
    s = s / max(np.quantile(s, 0.995), 1e-9)
    return u / mag, v / mag, np.clip(s, 0, 1)


def build(year: int | None = None) -> dict:
    year = year or 2024
    g = sector_grids(year)
    lat, lon = g.pop("_lat"), g.pop("_lon")
    k = int(round(RES_DEG / 0.1))
    lat_c = lat[: len(lat) // k * k].reshape(-1, k).mean(1)
    lon_c = lon[: len(lon) // k * k].reshape(-1, k).mean(1)
    stack = np.stack([coarsen(g[s], k) for s in SECTORS])
    dom = stack.argmax(0).astype(np.uint8)
    out = {"year": year, "method": __doc__.split("\n\n")[1].strip(), "sectors": SECTORS}
    for name in ("TOTAL", *SECTORS):
        E = coarsen(g[name], k)
        u, v, s = field(E)
        out[name] = {"bbox": [float(lon_c[0]), float(lat_c[0]), float(lon_c[-1]), float(lat_c[-1])],
                     "nx": int(len(lon_c)), "ny": int(len(lat_c)), "res": RES_DEG,
                     "u": np.round(u * 127).astype(np.int8).ravel().tolist(), "v": np.round(v * 127).astype(np.int8).ravel().tolist(),
                     "s": np.round(s * 255).astype(np.uint8).ravel().tolist(), "dom": dom.ravel().tolist()}
    return out


if __name__ == "__main__":
    ff = build()
    p = ROOT / "results" / "flow_field.json"
    p.write_text(json.dumps(ff, separators=(",", ":")))
    print("flow field", ff["TOTAL"]["nx"], "x", ff["TOTAL"]["ny"], f"{p.stat().st_size / 1e6:.1f} MB")
