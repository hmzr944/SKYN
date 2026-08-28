"""Tests HTTP des endpoints de memoire persistante (chantier 4) : verifie
uniquement le branchement (auth, routage, forme de reponse) — la logique
elle-meme est couverte par test_skin_memory.py. Utilisateur invite partage
entre tests : chaque test nettoie les collections concernees avant de
s'executer, pour rester independant de l'ordre d'execution.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("SKYN_ALLOW_GUEST", "1")
os.environ.setdefault("MONGO_URL", "demo")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

V2_ANALYSIS = {
    "global_score": 70,
    "concerns": {"texture": 0.40},
    "zone_scores": {"nez": 80},
    "quality": {"usable": True, "issues": []},
}


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


@pytest.fixture(scope="module")
def auth_headers():
    return {"Authorization": "Bearer skyn-guest"}


@pytest.fixture(autouse=True)
def _reset_memory_collections():
    async def _clear():
        for name in ("scans", "periods", "routine_events", "product_events"):
            await server.db[name].delete_many({})
    asyncio.run(_clear())
    yield


class TestSkinMemoryEndpoints:
    def test_scans_requires_auth(self, client):
        r = client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS})
        assert r.status_code in (401, 403)

    def test_rejects_unsupported_source(self, client, auth_headers):
        r = client.post("/api/scans", json={"source": "v1", "analysis": V2_ANALYSIS},
                         headers=auth_headers)
        assert r.status_code == 400

    def test_no_active_period_before_first_scan(self, client, auth_headers):
        r = client.get("/api/periods/active", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() is None

    def test_first_scan_becomes_baseline(self, client, auth_headers):
        r = client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS},
                         headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["is_baseline"] is True

        r = client.get("/api/periods/active", headers=auth_headers)
        body = r.json()
        assert body["state"] == "baseline"
        assert len(body["scans"]) == 1
        assert body["changes"] == []

    def test_second_scan_moves_to_tracking(self, client, auth_headers):
        client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS}, headers=auth_headers)
        client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS}, headers=auth_headers)
        r = client.get("/api/periods/active", headers=auth_headers)
        assert r.json()["state"] == "tracking"

    def test_structural_routine_event_opens_new_period(self, client, auth_headers):
        client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS}, headers=auth_headers)
        before = client.get("/api/periods/active", headers=auth_headers).json()

        r = client.post("/api/routine-events",
                         json={"type": "step_added", "diff": {"added": ["retinol_pm"]}},
                         headers=auth_headers)
        assert r.status_code == 200

        after = client.get("/api/periods/active", headers=auth_headers).json()
        assert after["period"]["id"] != before["period"]["id"]
        assert after["state"] == "baseline"  # nouvelle Phase, pas encore de nouveau scan

        periods = client.get("/api/periods", headers=auth_headers).json()
        assert len(periods) == 2

    def test_product_event_requires_active_period(self, client, auth_headers):
        r = client.post("/api/product-events",
                         json={"type": "introduced", "product_id": "x", "moment": "am"},
                         headers=auth_headers)
        assert r.status_code == 400

    def test_product_event_attaches_after_first_scan(self, client, auth_headers):
        client.post("/api/scans", json={"source": "v2", "analysis": V2_ANALYSIS}, headers=auth_headers)
        r = client.post("/api/product-events",
                         json={"type": "introduced", "product_id": "niacinamide_serum", "moment": "am"},
                         headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["product_id"] == "niacinamide_serum"

    def test_does_not_affect_v2_or_guided_endpoints(self, client, auth_headers):
        r = client.post("/api/analyze/v2", json={"image_base64": ""}, headers=auth_headers)
        # Image vide -> le moteur echoue proprement, mais la ROUTE existe et
        # repond toujours (500), elle n'a pas ete supprimee/deplacee.
        assert r.status_code in (200, 500)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
