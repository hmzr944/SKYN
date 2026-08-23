"""Tests des règles d'incompatibilité d'actifs. Hors ligne, sans serveur.

Ils verrouillent le défaut mesuré avant correction : 22,3 % des routines
empilaient deux actifs forts de la même famille, et 17,6 % associaient deux
rétinoïdes — jusqu'à un sérum Rétinol 0,3 % et un traitement Rétinol 1 % dans
la même journée.
"""
from __future__ import annotations

import os
import random
import sys
from collections import Counter

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from skyn_engine import actives as A
from skyn_engine.products import CATALOG, recommend_products, _user_needs


def P(pid):
    p = next((x for x in CATALOG if x["id"] == pid), None)
    assert p is not None, f"produit absent du catalogue : {pid}"
    return p


# --------------------------------------------------------------------------
class TestFamilies:
    def test_retinoids_are_detected(self):
        for pid in ("pc-clinical-retinol", "lrp-retinol-b3", "differin-adapalene"):
            assert "retinoide" in A.families(P(pid)), pid

    def test_bha_detected(self):
        bha = [p["id"] for p in CATALOG if "bha" in A.families(p)]
        assert len(bha) >= 5, f"trop peu de BHA reperes : {bha}"

    def test_gentle_products_carry_no_potent_family(self):
        for pid in ("lrp-cicaplast-b5", "avene-tolerance-control"):
            assert not (A.families(P(pid)) & A.POTENT), pid

    def test_accents_do_not_matter(self):
        a = A.families({"id": "x", "key_ingredients": ["Acide azélaïque 10%"], "name": ""})
        b = A.families({"id": "y", "key_ingredients": ["Acide azelaique 10%"], "name": ""})
        assert a == b == {"azelaique"}

    def test_unclassified_products_are_gentle_ones(self):
        """Un produit non classé n'est jamais bloqué : il ne doit donc pas
        s'agir d'un actif fort passé au travers du filet."""
        audit = A.audit_catalog(CATALOG)
        flat = [pid for ids in audit.values() for pid in ids]
        for pid in flat:
            blob = " ".join(P(pid).get("key_ingredients") or []).lower()
            for danger in ("rétinol", "retinol", "adapal", "peroxyde", "glycolique",
                           "salicyl", "azélaïque"):
                assert danger not in blob, f"{pid} contient {danger} mais n'est pas classé"


class TestIrritation:
    def test_dose_raises_irritation(self):
        """Rétinol 1 % doit peser plus lourd que Rétinol 0,3 %."""
        assert A.irritation(P("pc-clinical-retinol")) > A.irritation(P("lrp-retinol-b3"))

    def test_cleanser_is_discounted(self):
        """Un actif rincé après quelques secondes ne pèse pas comme un soin
        laissé en place toute la nuit."""
        leave_on = {"id": "a", "step": "serum", "name": "", "key_ingredients": ["Acide salicylique 2%"]}
        rinse = {"id": "b", "step": "nettoyant", "name": "", "key_ingredients": ["Acide salicylique 2%"]}
        assert A.irritation(rinse) < A.irritation(leave_on)

    def test_bounded(self):
        for p in CATALOG:
            assert 0.0 <= A.irritation(p) <= 1.0, p["id"]

    def test_excipient_percentage_is_ignored(self):
        """« Eau volcanique 89 % » n'est pas une concentration d'actif."""
        p = {"id": "z", "step": "serum", "name": "", "key_ingredients": ["Eau volcanique 89%"]}
        assert A.irritation(p) < 0.2


class TestConflicts:
    def test_two_retinoids_are_refused(self):
        """Le défaut d'origine : 17,6 % des routines cumulaient deux rétinoïdes."""
        assert A.conflicts(P("pc-clinical-retinol"), [P("lrp-retinol-b3")])

    def test_same_family_refused_even_at_different_moments(self):
        """C'est la dose cumulée sur la journée qui compte."""
        a = {"id": "a", "step": "serum", "name": "", "moment": "matin",
             "key_ingredients": ["Rétinol 0,3%"]}
        b = {"id": "b", "step": "traitement", "name": "", "moment": "soir",
             "key_ingredients": ["Rétinol 1%"]}
        assert A.conflicts(a, [b])

    def test_antagonist_pair_allowed_at_different_moments(self):
        """BHA le matin et rétinoïde le soir : association courante et tolérée."""
        bha = {"id": "a", "step": "serum", "name": "", "moment": "matin",
               "key_ingredients": ["Acide salicylique 2%"]}
        ret = {"id": "b", "step": "traitement", "name": "", "moment": "soir",
               "key_ingredients": ["Rétinol 0,3%"]}
        assert A.conflicts(bha, [ret]) is None

    def test_antagonist_pair_refused_at_same_moment(self):
        bha = {"id": "a", "step": "serum", "name": "", "moment": "soir",
               "key_ingredients": ["Acide salicylique 2%"]}
        ret = {"id": "b", "step": "traitement", "name": "", "moment": "soir",
               "key_ingredients": ["Rétinol 0,3%"]}
        assert A.conflicts(bha, [ret])

    def test_cleanser_never_conflicts(self):
        """Quelques secondes de contact avant rinçage ne cumulent pas."""
        wash = {"id": "a", "step": "nettoyant", "name": "", "moment": "matin_soir",
                "key_ingredients": ["Acide salicylique 2%"]}
        ret = {"id": "b", "step": "traitement", "name": "", "moment": "soir",
               "key_ingredients": ["Rétinol 1%"]}
        assert A.conflicts(wash, [ret]) is None

    def test_gentle_families_may_coexist(self):
        a = {"id": "a", "step": "serum", "name": "", "key_ingredients": ["Niacinamide 10%"]}
        b = {"id": "b", "step": "hydratant", "name": "", "key_ingredients": ["Céramides"]}
        assert A.conflicts(a, [b]) is None


class TestBudget:
    def test_reactive_skin_gets_smaller_budget(self):
        calm = A.irritation_budget({"redness": 0.0}, {})
        reactive = A.irritation_budget({"redness": 0.9}, {})
        assert reactive < calm

    def test_beginner_gets_smaller_budget(self):
        assert (A.irritation_budget({"redness": 0.2}, {"experience": "debutant"})
                < A.irritation_budget({"redness": 0.2}, {"experience": "avance"}))

    def test_pregnancy_and_isotretinoin_cap(self):
        assert A.irritation_budget({"redness": 0.0}, {"pregnant": True}) <= 0.55
        assert A.irritation_budget({"redness": 0.0}, {"on_isotretinoin": True}) <= 0.30

    def test_always_positive(self):
        assert A.irritation_budget({"redness": 1.0},
                                   {"skin_type": "Sèche", "experience": "debutant"}) > 0


class TestRoutineIntegration:
    """Sur une population simulée, la routine ne doit plus jamais empiler
    deux actifs forts de la même famille."""

    AGES = ["<25", "25-40", "40-60", "60+"]
    ENVS = ["Urbain", "Sec", "Humide", "Variable"]
    PRIOS = ["Éclat", "Ridules", "Imperfections", "Sensibilité"]
    STYPES = ["Sèche", "Normale", "Grasse", "Mixte", None]

    @staticmethod
    def _clamp(v, lo=30, hi=98):
        return int(round(max(lo, min(hi, v))))

    def _population(self, n=400, seed=7):
        rng = random.Random(seed)
        for _ in range(n):
            tx = self._clamp(100 - ((rng.gauss(7.5, 2.2) - 3) / 13) * 58)
            rd = self._clamp(30 + ((rng.gauss(150, 18) - 90) / 90) * 60)
            im = self._clamp(95 - (abs(rng.gauss(.07, .03)) - .04) * 450)
            metrics = {
                "texture": tx, "radiance": rd, "imperfections": im,
                "redness": max(0.0, rng.gauss(3.0, 2.0)),
                "shine_t": abs(rng.gauss(.06, .04)),
                "pore_density": abs(rng.gauss(.04, .03)),
                "fine_lines": abs(rng.gauss(.12, .10)),
            }
            profile = {
                "age_range": rng.choice(self.AGES),
                "environment": rng.choice(self.ENVS),
                "priority": rng.choice(self.PRIOS),
                "skin_type": rng.choice(self.STYPES),
            }
            yield metrics, profile

    def test_no_duplicate_potent_family(self):
        for metrics, profile in self._population():
            routine = recommend_products(metrics, profile)
            leave_on = [p for p in routine if p["step"] != "nettoyant"]
            fams = Counter()
            for p in leave_on:
                for f in A.families(p) & A.POTENT:
                    fams[f] += 1
            dup = [f for f, c in fams.items() if c >= 2]
            assert not dup, f"{dup} en double : {[p['id'] for p in leave_on]}"

    def test_essential_steps_always_present(self):
        """Une routine trouée est pire qu'une routine imparfaite : la
        protection solaire, en particulier, ne doit jamais sauter."""
        for metrics, profile in self._population(200):
            steps = {p["step"] for p in recommend_products(metrics, profile)}
            for essential in ("nettoyant", "hydratant", "protection"):
                assert essential in steps, f"{essential} manquant pour {profile}"

    def test_routine_never_empty_of_actives(self):
        for metrics, profile in self._population(200):
            steps = {p["step"] for p in recommend_products(metrics, profile)}
            assert steps & {"serum", "traitement"}, profile

    def test_pregnancy_excludes_retinoids(self):
        for metrics, profile in self._population(150):
            profile = {**profile, "pregnant": True}
            for p in recommend_products(metrics, profile):
                assert "retinoide" not in A.families(p), p["id"]

    def test_minors_never_get_retinoids(self):
        """Garde-fou déjà présent via min_age : on le verrouille."""
        for metrics, profile in self._population(200):
            profile = {**profile, "age_range": "<25"}
            for p in recommend_products(metrics, profile):
                assert "retinoide" not in A.families(p), p["id"]

    def test_deterministic(self):
        metrics, profile = next(iter(self._population(1)))
        a = [p["id"] for p in recommend_products(metrics, profile)]
        b = [p["id"] for p in recommend_products(metrics, profile)]
        assert a == b


class TestSchedule:
    def test_base_first_then_actives(self):
        metrics, profile = ({"texture": 60, "radiance": 60, "imperfections": 45,
                             "redness": 2.0}, {"age_range": "25-40"})
        routine = recommend_products(metrics, profile)
        steps = A.introduction_schedule(routine, _user_needs(metrics, profile))
        weeks = [s["week"] for s in steps]
        assert weeks == sorted(weeks)
        if steps:
            assert weeks[0] == 1

    def test_reactive_skin_gets_wider_spacing(self):
        metrics = {"texture": 60, "radiance": 60, "imperfections": 45, "redness": 9.0}
        routine = recommend_products(metrics, {"age_range": "25-40"})
        calm = A.introduction_schedule(routine, {"redness": 0.0})
        react = A.introduction_schedule(routine, {"redness": 0.9})
        if len(calm) > 1 and len(react) > 1:
            assert react[1]["week"] >= calm[1]["week"]
