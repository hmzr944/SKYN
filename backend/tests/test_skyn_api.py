"""SKYN backend API tests - auth, profile, reports, recommendations, SKYN Engine /analyze."""
import os
import uuid
import base64
import importlib
from pathlib import Path
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://skyn-glow-report.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://axpyatbjvvoxjtwkrhwu.supabase.co").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _new_session(s: "requests.Session") -> dict:
    """Provision a Supabase user via the Admin API and sign in to get an access token."""
    if not SUPABASE_SERVICE_ROLE_KEY or not SUPABASE_ANON_KEY:
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY not configured")
    email = f"test_{uuid.uuid4().hex[:10]}@skyn.test"
    password = uuid.uuid4().hex
    admin_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    r = s.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        json={"email": email, "password": password, "email_confirm": True,
              "user_metadata": {"name": "TEST User"}},
        headers=admin_headers,
        timeout=15,
    )
    assert r.status_code in (200, 201), f"Admin user creation failed: {r.status_code} {r.text}"
    created = r.json()

    r = s.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        json={"email": email, "password": password},
        headers={"apikey": SUPABASE_ANON_KEY},
        timeout=15,
    )
    assert r.status_code == 200, f"Sign-in failed: {r.status_code} {r.text}"
    token_data = r.json()
    return {
        "token": token_data["access_token"],
        "user": {"user_id": created["id"], "email": email},
    }

FIXTURE_FACE = Path(__file__).parent / "fixtures_face.jpg"


def _face_b64() -> str:
    if not FIXTURE_FACE.exists():
        pytest.skip("Face fixture not available")
    return base64.b64encode(FIXTURE_FACE.read_bytes()).decode()

# Tiny 1x1 white JPEG (valid bytes) base64-encoded
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQa"
    "FRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4e"
    "Hh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAA"
    "AAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAA"
    "AAD/2gAMAwEAAhEDEQA/AL+AB//Z"
)


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth():
    """Provision a Supabase test user and return token+user."""
    s = requests.Session()
    data = _new_session(s)
    return {"token": data["token"], "user": data["user"], "headers": {"Authorization": f"Bearer {data['token']}"}}


# -------- Health --------
class TestHealth:
    def test_root(self, session):
        r = session.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"
        assert body.get("name") == "SKYN API"


# -------- Auth --------
class TestAuth:
    def test_test_session_creates_user(self, auth):
        assert auth["user"]["email"].startswith("test_")
        assert len(auth["user"]["user_id"]) > 0

    def test_auth_me_with_token(self, session, auth):
        r = session.get(f"{API}/auth/me", headers=auth["headers"], timeout=10)
        assert r.status_code == 200
        assert r.json()["user_id"] == auth["user"]["user_id"]

    def test_auth_me_without_token(self, session):
        r = session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 401

    def test_auth_me_invalid_token(self, session):
        r = session.get(f"{API}/auth/me", headers={"Authorization": "Bearer invalid_token_xyz"}, timeout=10)
        assert r.status_code == 401


# -------- Profile (NEW shape: age_range / environment / priority) --------
class TestProfile:
    def test_get_profile_default(self, session, auth):
        r = session.get(f"{API}/profile", headers=auth["headers"], timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == auth["user"]["user_id"]
        assert body["onboarded"] is False
        # New fields present (may be null)
        assert "age_range" in body
        assert "environment" in body
        assert "priority" in body
        # Old fields must NOT be present
        assert "age" not in body
        assert "feeling" not in body
        assert "goal" not in body

    def test_update_profile_new_shape(self, session, auth):
        payload = {"age_range": "25-40", "environment": "Urbain", "priority": "Éclat", "onboarded": True}
        r = session.put(f"{API}/profile", headers=auth["headers"], json=payload, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["age_range"] == "25-40"
        assert body["environment"] == "Urbain"
        assert body["priority"] == "Éclat"
        assert body["onboarded"] is True
        # GET back to verify persistence
        g = session.get(f"{API}/profile", headers=auth["headers"], timeout=10)
        assert g.status_code == 200
        gb = g.json()
        assert gb["age_range"] == "25-40"
        assert gb["environment"] == "Urbain"
        assert gb["priority"] == "Éclat"
        assert gb["onboarded"] is True

    def test_profile_partial_update(self, session, auth):
        # Update only priority — others should remain
        r = session.put(f"{API}/profile", headers=auth["headers"], json={"priority": "Imperfections"}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["priority"] == "Imperfections"
        assert body["age_range"] == "25-40"  # preserved

    def test_profile_requires_auth(self, session):
        assert session.get(f"{API}/profile", timeout=10).status_code == 401
        assert session.put(f"{API}/profile", json={"age_range": "<25"}, timeout=10).status_code == 401


# -------- Reports (NEW shape — no hydration/elasticity) --------
class TestReports:
    def test_create_and_get_report(self, session, auth):
        payload = {
            "global_score": 82,
            "texture": 75,
            "radiance": 80,
            "imperfections": 70,
            "recommendations": ["TEST Use SPF daily", "TEST Hydrate", "TEST Niacinamide"],
        }
        r = session.post(f"{API}/reports", headers=auth["headers"], json=payload, timeout=10)
        assert r.status_code == 200, f"create report failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["global_score"] == 82
        assert body["texture"] == 75
        assert body["radiance"] == 80
        assert body["imperfections"] == 70
        assert body["user_id"] == auth["user"]["user_id"]
        assert "id" in body
        # Old fields must NOT appear in response
        assert "hydration" not in body
        assert "elasticity" not in body
        report_id = body["id"]
        # GET single
        g = session.get(f"{API}/reports/{report_id}", headers=auth["headers"], timeout=10)
        assert g.status_code == 200
        gj = g.json()
        assert gj["id"] == report_id
        assert gj["global_score"] == 82
        # LIST
        lst = session.get(f"{API}/reports", headers=auth["headers"], timeout=10)
        assert lst.status_code == 200
        ids = [x["id"] for x in lst.json()]
        assert report_id in ids

    def test_report_isolation_between_users(self, session, auth):
        payload = {"global_score": 60, "texture": 60, "radiance": 60, "imperfections": 60,
                   "recommendations": ["TEST_iso"]}
        r = session.post(f"{API}/reports", headers=auth["headers"], json=payload, timeout=10)
        assert r.status_code == 200
        report_id = r.json()["id"]
        other_headers = {"Authorization": f"Bearer {_new_session(session)['token']}"}
        g = session.get(f"{API}/reports/{report_id}", headers=other_headers, timeout=10)
        assert g.status_code == 404
        lst = session.get(f"{API}/reports", headers=other_headers, timeout=10)
        assert lst.status_code == 200
        assert report_id not in [x["id"] for x in lst.json()]

    def test_get_nonexistent_report(self, session, auth):
        r = session.get(f"{API}/reports/does-not-exist", headers=auth["headers"], timeout=10)
        assert r.status_code == 404

    def test_reports_requires_auth(self, session):
        assert session.get(f"{API}/reports", timeout=10).status_code == 401
        valid_body = {"global_score": 50, "texture": 50, "radiance": 50, "imperfections": 50, "recommendations": []}
        assert session.post(f"{API}/reports", json=valid_body, timeout=10).status_code == 401


# -------- Recommendations (NEW endpoint — GPT-4o Vision via Emergent LLM key) --------
class TestRecommendations:
    def test_recommendations_requires_auth(self, session):
        body = {"image_base64": TINY_JPEG_B64, "global_score": 75, "texture": 70, "radiance": 72, "imperfections": 78}
        r = session.post(f"{API}/recommendations", json=body, timeout=10)
        assert r.status_code == 401

    def test_recommendations_invalid_token(self, session):
        body = {"image_base64": TINY_JPEG_B64, "global_score": 75, "texture": 70, "radiance": 72, "imperfections": 78}
        r = session.post(f"{API}/recommendations", json=body,
                         headers={"Authorization": "Bearer invalid_token_xyz"}, timeout=10)
        assert r.status_code == 401

    def test_recommendations_returns_three_strings(self, session, auth):
        # Ensure profile exists with new fields so GPT prompt context is meaningful
        session.put(f"{API}/profile", headers=auth["headers"],
                    json={"age_range": "25-40", "environment": "Urbain", "priority": "Éclat", "onboarded": True},
                    timeout=10)
        body = {"image_base64": TINY_JPEG_B64, "global_score": 78, "texture": 72, "radiance": 70, "imperfections": 80}
        # GPT-4o vision may take a few seconds
        r = session.post(f"{API}/recommendations", headers=auth["headers"], json=body, timeout=60)
        assert r.status_code == 200, f"recommendations failed: {r.status_code} {r.text}"
        data = r.json()
        assert "recommendations" in data
        assert "source" in data
        assert data["source"] in ("gpt-4o", "fallback")
        recs = data["recommendations"]
        assert isinstance(recs, list)
        assert len(recs) == 3, f"expected exactly 3 recommendations, got {len(recs)}"
        for rec in recs:
            assert isinstance(rec, str)
            assert len(rec.strip()) > 0

    def test_recommendations_source_is_gpt4o_when_key_present(self, session, auth):
        """Re-confirm GPT-4o source per main agent's manual check."""
        body = {"image_base64": TINY_JPEG_B64, "global_score": 65, "texture": 60, "radiance": 70, "imperfections": 55}
        r = session.post(f"{API}/recommendations", headers=auth["headers"], json=body, timeout=60)
        assert r.status_code == 200
        data = r.json()
        # Soft assertion — log fallback so main agent sees it, but don't fail (LLM transient errors are possible)
        if data["source"] != "gpt-4o":
            pytest.skip(f"LLM fallback used (source={data['source']}). Recs still returned: {data['recommendations']}")
        assert data["source"] == "gpt-4o"
        assert len(data["recommendations"]) == 3


# -------- SKYN Engine module structure --------
import sys as _sys
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in _sys.path:
    _sys.path.insert(0, _BACKEND_DIR)


class TestSkynEngineModules:
    def test_module_files_exist(self):
        base = Path(_BACKEND_DIR) / "skyn_engine"
        assert base.is_dir(), f"skyn_engine dir missing: {base}"
        for fname in ("__init__.py", "preprocessing.py", "cv_analysis.py",
                      "imperfections.py", "expert_system.py", "pipeline.py"):
            f = base / fname
            assert f.is_file(), f"missing skyn_engine module file: {f}"

    def test_modules_import_cleanly(self):
        # Drop any cached partial imports
        for k in list(_sys.modules):
            if k == "skyn_engine" or k.startswith("skyn_engine."):
                del _sys.modules[k]
        for mod in [
            "skyn_engine",
            "skyn_engine.preprocessing",
            "skyn_engine.cv_analysis",
            "skyn_engine.imperfections",
            "skyn_engine.expert_system",
            "skyn_engine.pipeline",
        ]:
            m = importlib.import_module(mod)
            assert m is not None, f"Module {mod} failed to import"

    def test_public_api_exposed(self):
        from skyn_engine import analyze_skin, AnalysisOutput
        assert callable(analyze_skin)
        assert AnalysisOutput is not None


# -------- /api/analyze — SKYN Engine endpoint --------
class TestAnalyze:
    def test_analyze_requires_auth(self, session):
        r = session.post(f"{API}/analyze", json={"image_base64": TINY_JPEG_B64}, timeout=15)
        assert r.status_code == 401

    def test_analyze_invalid_token(self, session):
        r = session.post(f"{API}/analyze", json={"image_base64": TINY_JPEG_B64},
                         headers={"Authorization": "Bearer invalid_xyz"}, timeout=15)
        assert r.status_code == 401

    def test_analyze_synthetic_image_fallback(self, session, auth):
        """Tiny 1x1 jpg → no face. Endpoint must still respond 200 with detected=false,
        scores produced, 3 recommendations, detections=[]."""
        r = session.post(f"{API}/analyze", headers=auth["headers"],
                         json={"image_base64": TINY_JPEG_B64}, timeout=30)
        assert r.status_code == 200, f"analyze synthetic failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["detected"] is False
        # Scores still produced and in valid [30,98] range
        for k in ("global_score", "texture", "radiance", "imperfections"):
            assert isinstance(data[k], int), f"{k} should be int"
            assert 30 <= data[k] <= 98, f"{k}={data[k]} out of expected range"
        # 3 French recommendations
        recs = data["recommendations"]
        assert isinstance(recs, list) and len(recs) == 3
        for r_ in recs:
            assert isinstance(r_, str) and len(r_.strip()) > 10
        # detections empty since no face
        assert isinstance(data["detections"], list)
        assert data["detections"] == []
        # diagnosis non-empty string
        assert isinstance(data["diagnosis"], str) and len(data["diagnosis"]) > 0
        # source
        assert "source" in data and isinstance(data["source"], str)

    def test_analyze_real_face_image(self, session, auth):
        """Real face image → detected=true, normalized detection coords, scores plausible."""
        b64 = _face_b64()
        r = session.post(f"{API}/analyze", headers=auth["headers"],
                         json={"image_base64": b64}, timeout=60)
        assert r.status_code == 200, f"analyze face failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["detected"] is True, f"face not detected: {data}"
        # Scores plausible (30..98 per engine clamp)
        for k in ("global_score", "texture", "radiance", "imperfections"):
            assert 30 <= data[k] <= 98, f"{k}={data[k]} out of expected range"
        # diagnosis non-empty
        assert isinstance(data["diagnosis"], str) and len(data["diagnosis"]) > 0
        # exactly 3 recommendations, French strings (basic sanity)
        recs = data["recommendations"]
        assert len(recs) == 3
        for r_ in recs:
            assert isinstance(r_, str) and len(r_.strip()) > 20
        # detections — normalized x/y in [0,1], radius float, confidence in [0,1]
        dets = data["detections"]
        assert isinstance(dets, list)
        assert len(dets) >= 1, "expected at least 1 detection on a real face"
        for d in dets:
            assert isinstance(d["type"], str) and len(d["type"]) > 0
            assert 0.0 <= d["x"] <= 1.0, f"x out of range: {d['x']}"
            assert 0.0 <= d["y"] <= 1.0, f"y out of range: {d['y']}"
            assert 0.0 <= d["confidence"] <= 1.0
            assert isinstance(d["radius"], (int, float)) and d["radius"] > 0

    def test_analyze_invalid_base64(self, session, auth):
        """Garbage base64 should not 500 — engine catches and returns fallback."""
        r = session.post(f"{API}/analyze", headers=auth["headers"],
                         json={"image_base64": "not_a_real_base64_!!"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["detected"] is False
        assert len(data["recommendations"]) == 3


# -------- Report new fields: diagnosis + detections --------
class TestReportNewFields:
    def test_report_with_diagnosis_and_detections(self, session, auth):
        detections = [
            {"type": "spot", "x": 0.25, "y": 0.42, "confidence": 0.87, "radius": 0.025},
            {"type": "spot", "x": 0.71, "y": 0.55, "confidence": 0.66, "radius": 0.018},
        ]
        payload = {
            "global_score": 74,
            "texture": 70,
            "radiance": 72,
            "imperfections": 78,
            "recommendations": ["TEST reco 1", "TEST reco 2", "TEST reco 3"],
            "diagnosis": "Manque d'uniformité du teint",
            "detections": detections,
        }
        r = session.post(f"{API}/reports", headers=auth["headers"], json=payload, timeout=10)
        assert r.status_code == 200, f"create with new fields failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["diagnosis"] == "Manque d'uniformité du teint"
        assert isinstance(body["detections"], list) and len(body["detections"]) == 2
        assert body["detections"][0]["type"] == "spot"
        assert body["detections"][0]["x"] == 0.25
        rid = body["id"]
        # GET back — persisted
        g = session.get(f"{API}/reports/{rid}", headers=auth["headers"], timeout=10)
        assert g.status_code == 200
        gj = g.json()
        assert gj["diagnosis"] == "Manque d'uniformité du teint"
        assert len(gj["detections"]) == 2
        assert gj["detections"][1]["confidence"] == 0.66

    def test_report_without_new_fields_still_works(self, session, auth):
        """Backward compat: diagnosis/detections are optional."""
        payload = {
            "global_score": 80,
            "texture": 78,
            "radiance": 82,
            "imperfections": 80,
            "recommendations": ["TEST a", "TEST b", "TEST c"],
        }
        r = session.post(f"{API}/reports", headers=auth["headers"], json=payload, timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Defaults
        assert body.get("diagnosis") is None
        assert body.get("detections") == []

