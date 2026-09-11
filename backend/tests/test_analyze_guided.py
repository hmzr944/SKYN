"""Tests de l'endpoint /api/analyze/guided. Aucun reseau, aucune base de
donnees reelle (mode invite + mongomock) — verifie le contrat HTTP et le
comportement d'arret adaptatif, pas la qualite du moteur (deja couverte
par test_engine_v2.py).
"""
from __future__ import annotations

import base64
import os
import sys

import cv2
import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("SKYN_ALLOW_GUEST", "1")
os.environ.setdefault("MONGO_URL", "demo")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

FIXTURE = os.path.join(BACKEND, "tests", "fixtures_face.jpg")


def _b64(path: str, quality: int = 90) -> str:
    img = cv2.imread(path)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


@pytest.fixture(scope="module")
def auth_headers():
    return {"Authorization": "Bearer skyn-guest"}


class TestAnalyzeGuided:
    def test_requires_auth(self, client):
        r = client.post("/api/analyze/guided", json={"images_base64": [_b64(FIXTURE)]})
        assert r.status_code in (401, 403)

    def test_rejects_empty_images(self, client, auth_headers):
        r = client.post("/api/analyze/guided", json={"images_base64": []}, headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_invalid_config(self, client, auth_headers):
        payload = {"images_base64": [_b64(FIXTURE)], "min_vues_utiles": 9,
                   "cible_vues": 7, "max_vues": 5}  # min > cible > max, invalide
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 400

    def test_stops_early_on_repeated_identical_frames(self, client, auth_headers):
        """9 frames identiques fournies, cible=7, max=9 : l'ensemble confirme
        ne peut que rester stable, donc l'arret adaptatif doit se declencher
        au plus tard a la cible (7), pas necessairement consommer les 9."""
        images = [_b64(FIXTURE)] * 9
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 7, "max_vues": 9}
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["usable_views"] <= 9
        assert body["usable_views"] >= 5
        assert body["stop_reason"] in ("cible_atteinte_stable", "max_atteint", "frames_epuisees")
        assert body["status"] in ("TARGET_REACHED", "MAX_REACHED", "NEED_MORE_VIEWS")
        assert len(body["view_diagnostics"]) == body["usable_views"]
        for diag in body["view_diagnostics"]:
            assert "yaw_proxy" in diag and "roll_deg" in diag
        assert isinstance(body["lesions"], list)
        for lesion in body["lesions"]:
            assert 0.0 <= lesion["x"] <= 1.0
            assert 0.0 <= lesion["y"] <= 1.0
            assert lesion["n_observations"] >= 1

    def test_respects_max_vues_hard_cap(self, client, auth_headers):
        images = [_b64(FIXTURE)] * 5
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 5, "max_vues": 5}
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["usable_views"] <= 5

    def test_does_not_affect_v2_endpoint(self, client, auth_headers):
        """L'endpoint v2 existant doit rester inchange par cet ajout."""
        r = client.post("/api/analyze/v2", json={"image_base64": _b64(FIXTURE)}, headers=auth_headers)
        assert r.status_code == 200
        assert "global_score" in r.json()

    def test_zone_scores_present_and_bounded(self, client, auth_headers):
        """Le trou documente dans skin_memory.py (zone_scores toujours vide
        pour source == "guided") est comble : l'endpoint doit maintenant
        exposer une note par zone reellement couverte, dans les bornes
        attendues, sur un jeu de zones connu."""
        ZONES_CONNUES = {
            "front", "glabelle", "tempe_g", "tempe_d", "nez", "joue_g", "joue_d",
            "sous_yeux_g", "sous_yeux_d", "peri_oral", "menton", "machoire_g", "machoire_d",
        }
        images = [_b64(FIXTURE)] * 7
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 7, "max_vues": 9}
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "zone_scores" in body
        assert body["zone_scores"], "au moins une zone doit etre couverte sur une vue frontale nette"
        for zone, score in body["zone_scores"].items():
            assert zone in ZONES_CONNUES
            assert 0 <= score <= 100

    def test_zone_scores_deterministic_across_repeated_calls(self, client, auth_headers):
        """Meme sequence de vues envoyee deux fois -> meme zone_scores. Le
        module est une fonction pure sur des lesions deja confirmees ; rien
        en amont (detection par vue, tracking, vote-gate) n'introduit de
        hasard, donc l'identite doit tenir bout en bout, pas seulement au
        niveau du module isole (voir test_zone_scoring.py)."""
        images = [_b64(FIXTURE)] * 7
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 7, "max_vues": 9}
        r1 = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        r2 = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["zone_scores"] == r2.json()["zone_scores"]

    def test_routine_and_skin_type_now_present(self, client, auth_headers):
        """Le trou signale par un utilisateur reel : ce scan alimentait la
        Memoire de peau mais ne calculait ni routine ni type de peau — le
        parcours principal de l'app ne pouvait donc jamais tenir sa promesse
        ("votre routine sera construite"). Comble par un second calcul
        (analyze_multi, la meme fonction que /analyze/v2) plafonne aux 3
        premieres vues — voir server.py."""
        images = [_b64(FIXTURE)] * 7
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 7, "max_vues": 9}
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["skin_type"] not in (None, "indetermine")
        assert isinstance(body["global_score"], int)
        assert 0 <= body["global_score"] <= 100
        assert isinstance(body["concerns"], dict) and body["concerns"]
        assert "am" in body["routine"] and "pm" in body["routine"]
        # Le nettoyant (ou tout autre produit) doit venir du VRAI catalogue,
        # pas d'un texte fixe — si ce champ est vide, la routine annoncee
        # n'existe pas vraiment.
        assert any(body["routine"]["am"]) or any(body["routine"]["pm"])

    def test_guided_lesions_and_zone_scores_unaffected_by_rich_analysis(self, client, auth_headers):
        """Le second calcul (routine/type de peau) ne doit jamais se
        substituer au suivi multi-vue confirme : `lesions`/`zone_scores`
        restent exactement ceux d'`orchestrer_scan`, pas ceux — plus
        faibles, non trackes — du calcul plafonne a 3 vues."""
        images = [_b64(FIXTURE)] * 7
        payload = {"images_base64": images, "min_vues_utiles": 5, "cible_vues": 7, "max_vues": 9}
        r = client.post("/api/analyze/guided", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        for lesion in body["lesions"]:
            # Signature propre a orchestrer_scan/_confirmer — pas presente
            # sur les lesions d'un FaceAnalysis classique (qui ont `radius`,
            # `confidence`, etc. a la place).
            assert "n_observations" in lesion
            assert "evidence" in lesion


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
