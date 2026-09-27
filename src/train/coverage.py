"""Fail a production build when any five-year forecast cell is absent."""
import pandas as pd

from src.data.sectors import SECTORS


def require_sector_coverage(frame: pd.DataFrame, codes: list[str], last_year: int) -> None:
    expected = pd.MultiIndex.from_product([codes, SECTORS, range(last_year + 1, last_year + 6)],
                                          names=["state_code", "sector", "year"])
    actual = pd.MultiIndex.from_frame(frame[["state_code", "sector", "year"]])
    if len(set(codes)) != 36 or not actual.is_unique or not actual.symmetric_difference(expected).empty or frame[["p10", "p50", "p90", "p50_reconciled"]].isna().any().any():
        raise ValueError("state-sector forecast coverage incomplete: expected one finite P10/P50/P90 and reconciled median for every state, sector and horizon 1–5")


def require_city_coverage(frame: pd.DataFrame, city_ids: list[int], last_year: int) -> None:
    expected = pd.MultiIndex.from_product([city_ids, range(last_year + 1, last_year + 6)], names=["city_id", "year"])
    actual = pd.MultiIndex.from_frame(frame[["city_id", "year"]])
    if not actual.is_unique or not actual.symmetric_difference(expected).empty or frame[["p10", "p50", "p90"]].isna().any().any():
        raise ValueError("city forecast coverage incomplete: expected one P10/P50/P90 for every city and horizon 1–5")
