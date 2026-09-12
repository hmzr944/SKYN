"""Tests de la memoire persistante (chantier 4) : skin_memory.py en direct
(logique pure, base mongomock jetable par test) + un passage HTTP pour
verifier le branchement des endpoints. Aucun reseau.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("SKYN_ALLOW_GUEST", "1")
os.environ.setdefault("MONGO_URL", "demo")

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import skin_memory as sm  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _fresh_db():
    return AsyncMongoMockClient()["skyn_test"]


V2_HIGH_QUALITY = {
    "global_score": 70,
    "concerns": {"texture": 0.40, "redness": 0.20},
    "zone_scores": {"nez": 80, "joue_g": 70},
    "quality": {"usable": True, "issues": []},
}


def _v2(concerns=None, usable=True, issues=None):
    payload = {
        "global_score": 70,
        "concerns": concerns or {"texture": 0.40},
        "zone_scores": {"nez": 80},
        "quality": {"usable": usable, "issues": issues or []},
    }
    return payload


class TestIngestAndPeriodLifecycle:
    def test_first_scan_creates_baseline_period(self):
        db = _fresh_db()
        scan = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert scan.is_baseline is True
        assert scan.capture_quality == "high"

        period = _run(db.periods.find_one({"user_id": "u1"}, {"_id": 0}))
        assert period["baseline_scan_id"] == scan.id
        assert period["latest_scan_id"] == scan.id
        assert period["opened_by"] == "baseline"
        assert period["ends_at"] is None

    def test_second_scan_attaches_to_same_period(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        s2 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert s2.is_baseline is False
        assert s2.period_id == s1.period_id

        period = _run(db.periods.find_one({"user_id": "u1"}, {"_id": 0}))
        assert period["baseline_scan_id"] == s1.id
        assert period["latest_scan_id"] == s2.id

    def test_rejects_unsupported_source(self):
        db = _fresh_db()
        with pytest.raises(ValueError):
            _run(sm.ingest_scan(db, "u1", "v1", {}))

    def test_display_fields_are_persisted_from_the_source_analysis(self):
        """Dashboard/Suivi (chantier de reunification) affichent diagnostic,
        type de peau, severite et priorites depuis skin_memory — jusqu'ici
        ScanRecord ne les conservait pas du tout, alors que /analyze/v2 et
        /analyze/guided les calculent deja."""
        db = _fresh_db()
        analysis = {
            **V2_HIGH_QUALITY,
            "diagnosis": "Peau grasse — acné modérée",
            "skin_type": "grasse",
            "severity_level": 2,
            "top_concerns": ["acne_active", "sebum"],
        }
        scan = _run(sm.ingest_scan(db, "u1", "v2", analysis))
        assert scan.diagnosis == "Peau grasse — acné modérée"
        assert scan.skin_type == "grasse"
        assert scan.severity_level == 2
        assert scan.top_concerns == ["acne_active", "sebum"]

    def test_display_fields_default_gracefully_when_absent(self):
        """Le second calcul de /analyze/guided peut echouer sans faire
        echouer le scan (voir server.py) — ScanRecord ne doit pas planter,
        et ne doit surtout rien deviner a la place."""
        db = _fresh_db()
        scan = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert scan.diagnosis is None
        assert scan.skin_type is None
        assert scan.severity_level is None
        assert scan.top_concerns == []


class TestCaptureQuality:
    def test_v2_unusable_is_low(self):
        assert sm.compute_capture_quality("v2", _v2(usable=False)) == "low"

    def test_v2_usable_with_issues_is_medium(self):
        assert sm.compute_capture_quality("v2", _v2(issues=["low_light"])) == "medium"

    def test_v2_usable_clean_is_high(self):
        assert sm.compute_capture_quality("v2", _v2()) == "high"

    def test_guided_below_minimum_is_low(self):
        analysis = {"status": "NEED_MORE_VIEWS", "usable_views": 2}
        assert sm.compute_capture_quality("guided", analysis) == "low"

    def test_guided_target_reached_is_high(self):
        analysis = {"status": "TARGET_REACHED", "usable_views": 7}
        assert sm.compute_capture_quality("guided", analysis) == "high"

    def test_guided_max_reached_with_enough_views_is_medium(self):
        analysis = {"status": "MAX_REACHED", "usable_views": 9}
        assert sm.compute_capture_quality("guided", analysis) == "medium"


class TestPhaseState:
    def _seed(self, db, user_id, n, *, quality="high", span_days=0):
        """Ingest n scans then, if requested, spread their created_at over
        span_days so understanding's minimum-span rule can be exercised."""
        scans = []
        for i in range(n):
            payload = _v2(usable=(quality != "low"), issues=(["x"] if quality == "medium" else []))
            scans.append(_run(sm.ingest_scan(db, user_id, "v2", payload)))
        if span_days and n >= 2:
            base = datetime.now(timezone.utc) - timedelta(days=span_days)
            step = timedelta(days=span_days / (n - 1))
            for i, s in enumerate(scans):
                _run(db.scans.update_one({"id": s.id}, {"$set": {"created_at": base + step * i}}))
        return scans

    def test_one_scan_is_baseline(self):
        db = _fresh_db()
        self._seed(db, "u1", 1)
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["state"] == "baseline"
        assert view["changes"] == []

    def test_two_scans_is_tracking(self):
        db = _fresh_db()
        self._seed(db, "u1", 2)
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["state"] == "tracking"

    def test_three_scans_short_span_stays_tracking(self):
        db = _fresh_db()
        self._seed(db, "u1", 3, span_days=1)  # trop rapproches
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["state"] == "tracking"

    def test_three_scans_good_span_and_quality_is_understanding(self):
        db = _fresh_db()
        self._seed(db, "u1", 3, quality="high", span_days=21)
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["state"] == "understanding"

    def test_three_scans_good_span_but_low_quality_stays_tracking(self):
        db = _fresh_db()
        self._seed(db, "u1", 3, quality="low", span_days=21)
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["state"] == "tracking"

    def test_no_scans_returns_none(self):
        db = _fresh_db()
        assert _run(sm.get_active_period_view(db, "u1")) is None


class TestRoutineAndProductEvents:
    def test_structural_event_rolls_period(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        old_period_id = s1.period_id

        event = _run(sm.log_routine_event(db, "u1", "step_added", {"added": ["retinol_pm"]}))
        assert event.type == "step_added"

        old_period = _run(db.periods.find_one({"id": old_period_id}, {"_id": 0}))
        assert old_period["ends_at"] is not None

        new_period = _run(sm._get_active_period(db, "u1"))
        assert new_period["id"] != old_period_id
        assert new_period["opened_by"] == event.id
        assert new_period["baseline_scan_id"] == s1.id
        assert new_period["latest_scan_id"] == s1.id

        # Le scan suivant se rattache a la nouvelle Phase, pas a l'ancienne.
        s2 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert s2.period_id == new_period["id"]

    def test_created_event_does_not_roll_period(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        _run(sm.log_routine_event(db, "u1", "created", {}))
        active = _run(sm._get_active_period(db, "u1"))
        assert active["id"] == s1.period_id
        assert active["ends_at"] is None

    def test_routine_event_without_scan_raises(self):
        db = _fresh_db()
        with pytest.raises(ValueError):
            _run(sm.log_routine_event(db, "u1", "created", {}))

    def test_product_event_attaches_to_active_period(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        event = _run(sm.log_product_event(db, "u1", "introduced", "niacinamide_serum", "am"))
        assert event.period_id == s1.period_id
        assert event.type == "introduced"

    def test_product_event_without_scan_raises(self):
        db = _fresh_db()
        with pytest.raises(ValueError):
            _run(sm.log_product_event(db, "u1", "introduced", "x", "am"))


class TestTreatmentPhase:
    """start_treatment_phase — la porte d'entree "je commence ce traitement
    precis", distincte d'un changement de routine anonyme (voir sa docstring
    dans skin_memory.py)."""

    def test_starting_a_treatment_rolls_period_like_a_structural_event(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        old_period_id = s1.period_id

        event = _run(sm.start_treatment_phase(db, "u1", "Traitement anti-imperfections", "reduire les boutons du menton"))
        assert event.type == "treatment_started"
        assert event.label == "Traitement anti-imperfections"
        assert event.goal == "reduire les boutons du menton"

        old_period = _run(db.periods.find_one({"id": old_period_id}, {"_id": 0}))
        assert old_period["ends_at"] is not None

        new_period = _run(sm._get_active_period(db, "u1"))
        assert new_period["id"] != old_period_id
        assert new_period["opened_by"] == event.id
        # Ancree sur le dernier scan connu, comme un changement structurel :
        # pas besoin de rescanner immediatement pour avoir un point de depart.
        assert new_period["baseline_scan_id"] == s1.id
        assert new_period["label"] == "Traitement anti-imperfections"
        assert new_period["goal"] == "reduire les boutons du menton"

    def test_goal_is_optional(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        event = _run(sm.start_treatment_phase(db, "u1", "Nouveau nettoyant"))
        assert event.goal is None
        new_period = _run(sm._get_active_period(db, "u1"))
        assert new_period["label"] == "Nouveau nettoyant"
        assert new_period["goal"] is None

    def test_blank_name_is_rejected(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        with pytest.raises(ValueError):
            _run(sm.start_treatment_phase(db, "u1", "   "))

    def test_treatment_without_scan_raises(self):
        db = _fresh_db()
        with pytest.raises(ValueError):
            _run(sm.start_treatment_phase(db, "u1", "Traitement X"))

    def test_a_routine_scale_period_carries_no_label(self):
        """Une Phase ouverte par un changement de routine ordinaire (pas un
        traitement nomme) ne doit pas se retrouver avec un `label` — sinon
        l'ecran Phases ne pourrait plus distinguer les deux origines."""
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        _run(sm.log_routine_event(db, "u1", "step_added", {"added": ["x"]}))
        active = _run(sm._get_active_period(db, "u1"))
        assert active["label"] is None
        assert active["goal"] is None


class TestSkinChanges:
    def test_stable_within_epsilon(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.40})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.41})))  # delta < epsilon
        view = _run(sm.get_active_period_view(db, "u1"))
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["direction"] == "stable"

    def test_moving_direction_detected(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.60})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.30})))
        view = _run(sm.get_active_period_view(db, "u1"))
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["direction"] == "down"

    def test_two_scans_confidence_is_at_most_medium(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.60})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.30})))
        view = _run(sm.get_active_period_view(db, "u1"))
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["confidence"] in ("low", "medium")

    def test_no_attribution_without_product_event(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.60})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.30})))
        view = _run(sm.get_active_period_view(db, "u1"))
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["attribution"] is None

    def test_attribution_appears_with_confirmed_trend_and_product_event(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.70})))
        _run(sm.log_product_event(db, "u1", "introduced", "niacinamide_serum", "am"))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.50})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.30})))
        base = datetime.now(timezone.utc) - timedelta(days=21)
        # etale les 3 scans sur 21 jours pour satisfaire la regle "high"
        scans = _run(db.scans.find({"user_id": "u1"}, {"_id": 0}).sort("created_at", 1).to_list(length=10))
        step = timedelta(days=21 / (len(scans) - 1))
        for i, s in enumerate(scans):
            _run(db.scans.update_one({"id": s["id"]}, {"$set": {"created_at": base + step * i}}))

        view = _run(sm.get_active_period_view(db, "u1"))
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["confidence"] == "high"
        assert texture["attribution"] == ["niacinamide_serum"]

    def test_no_common_metric_is_skipped_not_guessed(self):
        db = _fresh_db()
        no_zones = {"quality": {"usable": True, "issues": []}, "zone_scores": {}}
        _run(sm.ingest_scan(db, "u1", "v2", {**no_zones, "concerns": {"texture": 0.60}}))
        _run(sm.ingest_scan(db, "u1", "v2", {**no_zones, "concerns": {"redness": 0.30}}))
        view = _run(sm.get_active_period_view(db, "u1"))
        assert view["changes"] == []


class TestGuidedScanChanges:
    """Le scan multi-vue guide (source="guided") n'a pas de concerns (voir
    _extract_scan_fields) — sans comparer lesion_counts, une Phase
    construite uniquement a partir de scans guides n'aurait jamais rien a
    montrer sur What Changed?. zone_scores, lui, arrive maintenant dans le
    payload d'analyse (calcule par skyn_engine.v2.zone_scoring cote
    /api/analyze/guided) — _extract_scan_fields doit juste le relayer."""

    def _guided(self, lesion_types, zone_scores=None):
        return {
            "status": "TARGET_REACHED",
            "usable_views": 7,
            "lesions": [{"type": t} for t in lesion_types],
            "zone_scores": zone_scores or {},
        }

    def test_lesion_count_drop_is_detected(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "guided", self._guided(["papule", "papule", "comedon"])))
        _run(sm.ingest_scan(db, "u1", "guided", self._guided(["comedon"])))
        view = _run(sm.get_active_period_view(db, "u1"))
        papule = next(c for c in view["changes"] if c["metric"] == "papule")
        assert papule["kind"] == "lesion_type"
        assert papule["direction"] == "down"

    def test_unchanged_count_is_stable(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "guided", self._guided(["comedon"])))
        _run(sm.ingest_scan(db, "u1", "guided", self._guided(["comedon"])))
        view = _run(sm.get_active_period_view(db, "u1"))
        comedon = next(c for c in view["changes"] if c["metric"] == "comedon")
        assert comedon["direction"] == "stable"

    def test_guided_scans_get_medium_or_high_capture_quality(self):
        db = _fresh_db()
        scan = _run(sm.ingest_scan(db, "u1", "guided", self._guided(["comedon"])))
        assert scan.capture_quality == "high"
        assert scan.source == "guided"
        assert scan.concerns == {}
        assert scan.zone_scores == {}
        assert scan.lesion_counts == {"comedon": 1}

    def test_guided_zone_scores_are_relayed_from_analysis(self):
        db = _fresh_db()
        scan = _run(sm.ingest_scan(
            db, "u1", "guided", self._guided(["comedon"], zone_scores={"nez": 62, "front": 100}),
        ))
        assert scan.zone_scores == {"nez": 62, "front": 100}

    def test_guided_zone_change_is_detected_on_the_skin_map(self):
        """Meme mecanique de comparaison que pour lesion_counts (intersection
        des zones mesurees aux deux scans, voir _METRIC_FIELDS) — verifie ici
        que zone_scores nourrit bien What Changed?, plus seulement stocke."""
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "guided", self._guided([], zone_scores={"nez": 90})))
        _run(sm.ingest_scan(db, "u1", "guided", self._guided([], zone_scores={"nez": 40})))
        view = _run(sm.get_active_period_view(db, "u1"))
        nez = next(c for c in view["changes"] if c["kind"] == "zone" and c["metric"] == "nez")
        assert nez["direction"] == "down"


class TestListPeriods:
    def test_lists_active_and_closed_periods_most_recent_first(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        _run(sm.log_routine_event(db, "u1", "step_added", {"added": ["x"]}))
        periods = _run(sm.list_periods(db, "u1"))
        assert len(periods) == 2
        assert periods[0]["ends_at"] is None  # la Phase active en tete


class TestGetPeriodView:
    """get_period_view — le "Bilan" d'une Phase precise, la piece qui
    manquait pour consulter un traitement apres qu'il soit termine (voir
    _build_period_view, factorisee avec get_active_period_view)."""

    def test_returns_the_active_period_by_id(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        view = _run(sm.get_period_view(db, "u1", s1.period_id))
        assert view is not None
        assert view["period"]["id"] == s1.period_id
        assert view["state"] == "baseline"

    def test_returns_a_closed_treatment_period_with_its_own_changes(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.60})))
        _run(sm.start_treatment_phase(db, "u1", "Acide salicylique"))
        treatment_period_id = _run(sm._get_active_period(db, "u1"))["id"]
        # baseline_scan_id ne fait que pointer vers le dernier scan de la
        # Phase precedente (continuite visuelle) — les changements, eux, ne
        # se calculent que sur les scans propres a CETTE Phase : il en faut
        # deux ICI, pas un point de depart emprunte a la precedente.
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.45})))
        _run(sm.ingest_scan(db, "u1", "v2", _v2(concerns={"texture": 0.30})))
        # Un second traitement cloture le premier — le Bilan du premier doit
        # rester consultable, pas seulement celui de la Phase desormais active.
        _run(sm.start_treatment_phase(db, "u1", "Nouveau traitement"))

        view = _run(sm.get_period_view(db, "u1", treatment_period_id))
        assert view is not None
        assert view["period"]["label"] == "Acide salicylique"
        assert view["period"]["ends_at"] is not None
        texture = next(c for c in view["changes"] if c["metric"] == "texture")
        assert texture["direction"] == "down"

    def test_unknown_period_returns_none(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert _run(sm.get_period_view(db, "u1", "not-a-real-id")) is None

    def test_another_users_period_is_not_visible(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert _run(sm.get_period_view(db, "u2", s1.period_id)) is None


class TestListScans:
    """list_scans — la lecture qui manquait pour que Dashboard/Suivi
    affichent l'historique complet d'un utilisateur, toutes Phases
    confondues, plutot que seulement la Phase active."""

    def test_lists_scans_across_periods_most_recent_first(self):
        db = _fresh_db()
        s1 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        _run(sm.start_treatment_phase(db, "u1", "Traitement X"))
        s2 = _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))

        scans = _run(sm.list_scans(db, "u1"))
        assert [s["id"] for s in scans] == [s2.id, s1.id]

    def test_does_not_leak_another_users_scans(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        assert _run(sm.list_scans(db, "u2")) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
