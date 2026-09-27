"""`python -m src.insights` — v1 analytics (insights.json) + ATAR insight feed (atar_insights.json)."""
import json

from src.insights import RES, compute

out = compute()
(RES / "insights.json").write_text(json.dumps(out, indent=1, default=float))
print("decoupling top 5:", [(d["state_code"], d["status"]) for d in out["decoupling"][:5]])
print("watchlist:", [w["state_code"] for w in out["watchlist"] if w["on_watchlist"]][:10])
try:
    from src.insights.atar import generate, save

    items = generate()
    save(items)
    print(f"ATAR: {len(items)} insights", {s: sum(i['severity'] == s for i in items) for s in ('alert', 'warning', 'notice', 'info')})
except (FileNotFoundError, ImportError) as e:
    print("ATAR skipped (run sector ingestion + sector_run first):", e)
