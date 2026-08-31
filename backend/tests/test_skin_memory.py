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
    """Le scan multi-vue guide (source="guided") n'a ni concerns ni
    zone_scores (voir _extract_scan_fields) — sans comparer lesion_counts,
    une Phase construite uniquement a partir de scans guides n'aurait
    jamais rien a montrer sur What Changed?."""

    def _guided(self, lesion_types):
        return {
            "status": "TARGET_REACHED",
            "usable_views": 7,
            "lesions": [{"type": t} for t in lesion_types],
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


class TestListPeriods:
    def test_lists_active_and_closed_periods_most_recent_first(self):
        db = _fresh_db()
        _run(sm.ingest_scan(db, "u1", "v2", V2_HIGH_QUALITY))
        _run(sm.log_routine_event(db, "u1", "step_added", {"added": ["x"]}))
        periods = _run(sm.list_periods(db, "u1"))
        assert len(periods) == 2
        assert periods[0]["ends_at"] is None  # la Phase active en tete


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
