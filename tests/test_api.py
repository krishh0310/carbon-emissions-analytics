"""API auth/security tests against an isolated SQLite DB (no Postgres needed)."""
import os

os.environ.update(DATABASE_URL="sqlite:///./test_api.db", JWT_SECRET="test-secret-" + "x" * 40, RATE_LIMIT_AUTH="1000/minute")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import db as dbm  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.security import hash_password  # noqa: E402


@pytest.fixture(scope="module")
def client():
    if os.path.exists("test_api.db"):
        os.remove("test_api.db")
    dbm.Base.metadata.create_all(dbm.engine())
    with dbm.session() as s:
        s.add(dbm.User(email="admin@example.com", hash=hash_password("adminpassword1"), role="admin"))
        s.add(dbm.State(code="IN-MH", name="Maharashtra", region="West", is_ut=False, coastal=True,
                        geometry='{"type":"MultiPolygon","coordinates":[]}', boundary_source="test"))
        s.add(dbm.EmissionState(state_code="IN-MH", year=2024, co2_mt=300.0, source="EDGAR-downscaled"))
        s.commit()
    yield TestClient(app)
    dbm.Base.metadata.drop_all(dbm.engine())  # keep the file/pool valid for later test modules sharing the engine


def _login(c, email, pw):
    r = c.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def test_register_login_and_protected(client):
    assert client.post("/api/v1/auth/register", json={"email": "v@example.com", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "v@example.com", "password": "viewerpass1"}).status_code == 201
    assert client.post("/api/v1/auth/register", json={"email": "v@example.com", "password": "viewerpass1"}).status_code == 409
    assert client.get("/api/v1/states").status_code == 401
    t = _login(client, "v@example.com", "viewerpass1")
    r = client.get("/api/v1/states", headers={"Authorization": f"Bearer {t['access_token']}"})
    assert r.status_code == 200 and r.json()["items"][0]["code"] == "IN-MH"
    assert r.headers["x-frame-options"] == "DENY" and "content-security-policy" in r.headers


def test_wrong_password_and_token_type(client):
    assert client.post("/api/v1/auth/login", json={"email": "v@example.com", "password": "wrongpass12"}).status_code == 401
    t = _login(client, "v@example.com", "viewerpass1")
    # refresh token must not work as access token
    assert client.get("/api/v1/states", headers={"Authorization": f"Bearer {t['refresh_token']}"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    t = _login(client, "v@example.com", "viewerpass1")
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r1.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401  # reuse
    # reuse revoked the whole family, including the freshly issued token
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401


def test_role_guard_and_validation(client):
    v = _login(client, "v@example.com", "viewerpass1")["access_token"]
    a = _login(client, "admin@example.com", "adminpassword1")["access_token"]
    assert client.post("/api/v1/admin/retrain", json={}, headers={"Authorization": f"Bearer {v}"}).status_code == 403
    assert client.get("/api/v1/admin/jobs", headers={"Authorization": f"Bearer {a}"}).status_code == 200
    h = {"Authorization": f"Bearer {v}"}
    assert client.get("/api/v1/states/DROP TABLE/history", headers=h).status_code == 422
    assert client.get("/api/v1/states?limit=100000", headers=h).status_code == 422  # max page size
    assert client.post("/api/v1/admin/retrain", json={"models": ["rm -rf"]},
                       headers={"Authorization": f"Bearer {a}"}).status_code == 422


# ---- v2 -------------------------------------------------------------------------------------------------
def _seed_v2():
    with dbm.session() as s:
        if s.query(dbm.EmissionStateSector).count():
            return
        for sec, v in (("POWER", 200.0), ("TRANSPORT", 30.0), ("INDUSTRY", 60.0), ("BUILDINGS", 10.0),
                       ("AGRICULTURE", 20.0), ("WASTE", 5.0), ("OTHER", 3.0)):
            s.add(dbm.EmissionStateSector(state_code="IN-MH", sector=sec, year=2024, co2e_mt=v, co2_mt=v * 0.9,
                                          source="test", method="test", confidence="B"))
        s.add(dbm.Insight(state_code="IN-MH", sector="POWER", type="ANOMALY", severity="alert", title="t", body="b", evidence={"z": 3}))
        s.add(dbm.Insight(state_code=None, sector="POWER", type="TREND", severity="info", title="n", body="b", evidence={}))
        s.commit()


def test_v2_sectors_insights_and_validation(client):
    _seed_v2()
    h = {"Authorization": f"Bearer {_login(client, 'v@example.com', 'viewerpass1')['access_token']}"}
    r = client.get("/api/v2/states/IN-MH/sectors", headers=h)
    assert r.status_code == 200 and len(r.json()["breakdown"]) == 7
    assert abs(sum(b["share"] for b in r.json()["breakdown"]) - 1) < 1e-9
    assert client.get("/api/v2/states/IN-MH/sectors").status_code == 401
    assert client.get("/api/v2/states/IN-MH/sectors/NUCLEAR/forecast", headers=h).status_code == 422  # sector enum
    ins = client.get("/api/v2/insights?severity=alert", headers=h).json()
    assert ins["total"] == 1 and ins["items"][0]["severity"] == "alert"
    assert client.get("/api/v2/insights?state=NATIONAL", headers=h).json()["total"] == 1
    assert client.get("/api/v2/insights?severity=critical", headers=h).status_code == 422
    assert client.get("/api/v2/insights?limit=5000", headers=h).status_code == 422
    # scenario bounds are enforced server-side before any computation
    for bad in ({"renewable_pp": 80}, {"ev_share_pct": -1}, {"industrial_growth_pp": 9}, {"states": ["DROP TABLE"]}, {"name": "<script>"}):
        assert client.post("/api/v2/scenarios/run", json=bad, headers=h).status_code == 422, bad
    # insights are read-only for everyone (no write routes exist)
    assert client.post("/api/v2/insights", json={}, headers=h).status_code == 405


# ---- v3 RBAC: viewers never see model internals ----------------------------------------------------------
def test_rbac_viewer_cannot_reach_model_internals(client):
    v = {"Authorization": f"Bearer {_login(client, 'v@example.com', 'viewerpass1')['access_token']}"}
    a = {"Authorization": f"Bearer {_login(client, 'admin@example.com', 'adminpassword1')['access_token']}"}
    for path in ("/api/v1/models", "/api/v1/models/gru/importance", "/api/v1/models/gru/backtest", "/api/v1/data-quality",
                 "/api/v2/models", "/api/v2/models/mt_gru/importance", "/api/v1/admin/jobs", "/api/v1/admin/registry"):
        assert client.get(path, headers=v).status_code == 403, path
        assert client.get(path, headers=a).status_code in (200, 404), path  # admin allowed (404 = artifact not seeded)
    # choosing a model is admin-only; default forecasts never name the model for viewers
    assert client.get("/api/v1/states/IN-MH/forecast?model=gru", headers=v).status_code == 403
    assert client.get("/api/v2/states/IN-MH/sectors/POWER/forecast?model=gru", headers=v).status_code == 403
    with dbm.session() as s:
        s.add(dbm.Model(name="gru", version="t", target="co2_mt", horizon=5, metrics={}, level="state", status="champion", val_score=1.0))
        s.commit()
    r = client.get("/api/v1/states/IN-MH/forecast", headers=v).json()
    assert r["forecast"] == "CarbonScope Forecast" and "model" not in r and "version" not in r
    ra = client.get("/api/v1/states/IN-MH/forecast", headers=a).json()
    assert ra["model"] == "gru"
