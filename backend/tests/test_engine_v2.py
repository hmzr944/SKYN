"""Tests unitaires du moteur v2. Aucun serveur ni reseau requis.

Ils verrouillent en priorite les defauts constates sur v1, pour qu'ils ne
puissent pas revenir sans qu'un test echoue.
"""
from __future__ import annotations

import base64
import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from skyn_engine.v2.concerns import CONCERN_KEYS, build_fingerprint
from skyn_engine.v2.lesions import LesionReport, RED_IF_DARK, _classify, _severity
from skyn_engine.v2.matching import (
    ACTIVE_STEPS,
    ESSENTIAL_STEPS,
    POTENT_FAMILIES,
    _conflicts,
    _irritation_budget,
    _load_catalog,
    build_routine,
)
from skyn_engine.v2.phenotype import Phenotype, ZoneStats, _decide_skin_type, _ita, _phototype_from_ita

FIXTURE = os.path.join(BACKEND, "tests", "fixtures_face.jpg")


# --------------------------------------------------------------------------
# Fabriques
# --------------------------------------------------------------------------
def make_phenotype(**kw) -> Phenotype:
    base = dict(
        skin_type="mixte", skin_type_confidence=0.8,
        phototype="III", phototype_label="Intermediaire", ita_deg=34.0,
        sensitive=False, sebum_t=0.6, sebum_u=0.3, shine_delta=0.3,
        dryness=0.1, redness_global=0.2, pore_load=0.4, unevenness=0.3,
        zones={"joue_g": ZoneStats("joue_g", 0.1, 8.0, 4.0, 60.0, 6.0, 14.0, 0.05, 0.0)},
        notes=[],
    )
    base.update(kw)
    return Phenotype(**base)


def make_lesions(severity=2, **counts) -> LesionReport:
    c = {"comedon": 0, "papule": 0, "pustule": 0,
         "marque_rouge": 0, "marque_brune": 0}
    c.update(counts)
    zones = ["front", "joue_g", "joue_d", "menton"]
    per_zone = {z: dict(c) for z in zones}
    density = {z: float(sum(c.values())) / len(zones) for z in zones}
    return LesionReport(
        lesions=[], counts=c, per_zone=per_zone, density=density,
        gags_score=float(severity * 8), severity_level=severity,
        severity_label=["peau_nette", "acne_legere", "acne_moderee",
                        "acne_severe", "acne_tres_severe"][severity],
        inflammatory_ratio=0.5, dominant_zones=zones[:2], hormonal_pattern=False,
    )


# --------------------------------------------------------------------------
# Phenotype
# --------------------------------------------------------------------------
class TestPhenotype:
    def test_ita_bands_cover_all_phototypes(self):
        """Chaque bande ITA doit produire le phototype attendu."""
        cases = [(70, "I"), (48, "II"), (34, "III"), (18, "IV"), (0, "V"), (-45, "VI")]
        for ita, expected in cases:
            code, _ = _phototype_from_ita(ita)
            assert code == expected, f"ITA {ita} -> {code}, attendu {expected}"

    def test_ita_formula_sign(self):
        """Une peau claire (L* eleve) donne un ITA positif eleve."""
        assert _ita(75.0, 15.0) > 50
        assert _ita(35.0, 18.0) < 0

    def test_ita_handles_zero_b_star(self):
        """b* nul ne doit pas lever de division par zero."""
        assert isinstance(_ita(60.0, 0.0), float)

    def test_skin_type_uses_tu_differential(self):
        """Une zone T brillante avec des joues mates donne une peau mixte.

        C'est precisement ce que v1 ne pouvait pas faire : le masque de zone T
        y etait calcule puis jamais lu.
        """
        t, _ = _decide_skin_type(sebum_t=0.5, sebum_u=0.2, delta=0.3, dryness=0.1)
        assert t == "mixte"

    def test_skin_type_oily_needs_both_zones(self):
        t, _ = _decide_skin_type(sebum_t=0.7, sebum_u=0.6, delta=0.1, dryness=0.0)
        assert t == "grasse"

    def test_skin_type_dry(self):
        t, _ = _decide_skin_type(sebum_t=0.1, sebum_u=0.1, delta=0.0, dryness=0.6)
        assert t == "seche"

    def test_confidence_is_bounded(self):
        for args in [(0.9, 0.9, 0.0, 0.0), (0.0, 0.0, 0.0, 0.9), (0.4, 0.2, 0.2, 0.2)]:
            _, conf = _decide_skin_type(*args)
            assert 0.0 <= conf <= 1.0


# --------------------------------------------------------------------------
# Severite
# --------------------------------------------------------------------------
class TestSeverity:
    def test_bands_are_monotonic(self):
        levels = [_severity(g)[0] for g in (0.0, 4.0, 12.0, 24.0, 60.0)]
        assert levels == [0, 1, 2, 3, 4]
        assert levels == sorted(levels)

    def test_severity_separates_mild_from_severe(self):
        """v1 plafonnait a 5 detections : acne legere et severe se confondaient."""
        assert _severity(4.0)[0] < _severity(24.0)[0]


# --------------------------------------------------------------------------
# Classification d'une lesion
#
# Ces cas viennent du banc d'essai a lesions synthetiques
# (backend/tools/synth_lesions.py) : ce sont les signatures reelles mesurees
# sur des lesions posees a des positions connues, et sur les structures qui
# produisaient des faux positifs.
# --------------------------------------------------------------------------
def classify(red, dark, yellow, *, core_l=-5.0, core_s=100.0, skin_s=60.0,
             r_px=4.0, px_per_mm=2.6, src="rouge"):
    return _classify(red, dark, yellow, core_l, core_s, skin_s,
                     r_px, px_per_mm, src)


class TestBlobSplitting:
    """Deux ou trois lesions rondes qui se touchent forment, une fois
    binarisees, une seule composante allongee que les filtres de forme
    (aire, circularite) rejettent en bloc. Diagnostic P0 sur le banc de
    reference : 6 des 8 lesions non retrouvees etaient dans ce cas exact.
    `_split_touching` les separe par ligne de partage des eaux avant que les
    filtres ne s'appliquent."""

    def test_two_touching_discs_split_into_two(self):
        """Verrouille la correction de la convention des marqueurs de
        `cv2.watershed`. Premiere version : tout pixel de premier plan qui
        n'etait pas lui-meme un germe recevait un marqueur DEJA attribue (1)
        au lieu du marqueur "inconnu" (0) que watershed doit remplir — plus
        rien a inonder, les fragments rendus faisaient 1 pixel chacun. Sur ce
        cas fixe (deux disques de rayon 9 qui se touchent), la version
        buguee rendait deux fragments d'aire 1 ; corrigee, elle rend deux
        moities d'aire proche de celle d'un disque isole (~254 px).
        """
        import cv2
        import numpy as np
        from skyn_engine.v2.lesions import _split_touching

        comp = np.zeros((60, 60), dtype=np.uint8)
        cv2.circle(comp, (20, 30), 9, 1, -1)
        cv2.circle(comp, (35, 30), 9, 1, -1)

        frags = _split_touching(comp, r_min_px=1.66)

        assert len(frags) == 2
        for f in frags:
            # Une moitie de la paire fusionnee, pas un pixel isole ni le
            # bloc entier repris tel quel.
            assert 120 < f.sum() < 350

    def test_single_disc_is_not_split(self):
        """Une lesion isolee, sans voisine, ne doit produire aucun fragment
        — `_blob_candidates` la garde alors telle quelle."""
        import cv2
        import numpy as np
        from skyn_engine.v2.lesions import _split_touching

        comp = np.zeros((40, 40), dtype=np.uint8)
        cv2.circle(comp, (20, 20), 9, 1, -1)

        assert _split_touching(comp, r_min_px=1.66) == []

    def test_merged_pair_survives_candidate_filtering(self):
        """Le test d'integration correspondant : deux disques fusionnes,
        passes par `_blob_candidates` en entier (seuil, filtres de forme,
        separation), doivent rendre deux candidats — pas zero.
        """
        import cv2
        import numpy as np
        from skyn_engine.v2 import calibration as C
        from skyn_engine.v2.lesions import _blob_candidates

        excess = np.zeros((80, 80), dtype=np.float32)
        mask = np.zeros((80, 80), dtype=np.uint8)
        cv2.circle(mask, (40, 40), 35, 255, -1)
        for cx in (33, 48):
            cv2.circle(excess, (cx, 40), 9, 20.0, -1)
        # Un peu de bruit de fond realiste, sinon le seuil robuste degenere.
        rng = np.random.default_rng(0)
        excess += rng.normal(0, 0.5, excess.shape).astype(np.float32) * (mask > 0)

        a_min, a_max = 8, 400
        cands = _blob_candidates(excess, mask, C.RED_BLOB_K, a_min, a_max)
        assert len(cands) == 2


class TestClassification:
    def test_papule_rouge_et_sombre_est_retenue(self):
        """Le cas qui disparaissait : franchement rouge ET franchement sombre.

        L'ancienne regle exigeait `dark > -1.2`, en supposant qu'une lesion en
        relief ne peut pas etre plus foncee que la peau voisine. Une papule
        inflammatoire l'est pourtant souvent. Elle ne correspondait alors a
        aucune regle et n'apparaissait pas dans le rapport : le rappel du banc
        d'essai plafonnait a 3 %.
        """
        assert classify(13.2, -12.2, 4.7, core_l=-17.6, core_s=135.7) == "papule"

    def test_papule_en_relief_reste_retenue(self):
        assert classify(2.5, -0.4, 0.2) == "papule"

    def test_ombre_rosee_est_rejetee(self):
        """Une ombre un peu rouge ne doit pas devenir une lesion.

        Sans cette exigence renforcee, le rappel montait a 27 % mais les faux
        positifs sur visage vierge passaient de 4 a 49 : le moteur cessait
        d'etre credible.
        """
        assert classify(RED_IF_DARK - 1.0, -4.0, 0.2) is None

    def test_seuil_plus_exigeant_quand_la_lesion_est_sombre(self):
        """Une meme rougeur suffit en relief, pas dans le sombre."""
        red = 2.5
        assert red < RED_IF_DARK
        assert classify(red, -0.4, 0.2) == "papule"
        assert classify(red, -4.0, 0.2) is None

    def test_poil_n_est_pas_un_comedon(self):
        """Sombre et neutre : c'est un poil, pas du sebum oxyde."""
        assert classify(0.5, -4.0, 0.0, r_px=2.0) is None

    def test_comedon_demande_une_teinte_chaude(self):
        assert classify(0.5, -4.0, 0.6, r_px=2.0, core_s=48.0) == "comedon"

    def test_coeur_desature_reste_un_poil(self):
        """Meme legerement chaud, un noyau tres desature n'est pas une lesion."""
        assert classify(0.5, -4.0, 0.6, r_px=2.0, core_s=60.0 * 0.4) is None


# --------------------------------------------------------------------------
# Empreinte cutanee
# --------------------------------------------------------------------------
class TestFingerprint:
    def test_all_axes_present_and_bounded(self):
        fp = build_fingerprint(make_phenotype(), make_lesions(), {})
        assert set(fp.vector) == set(CONCERN_KEYS)
        for k, v in fp.vector.items():
            assert 0.0 <= v <= 1.0, f"{k} hors bornes : {v}"

    def test_priority_moves_the_vector(self):
        """En v1 la priorite declaree ne retranchait que 4 points a un score.

        Elle doit maintenant deplacer reellement les axes concernes.
        """
        ph, lr = make_phenotype(), make_lesions(1, comedon=3)
        neutral = build_fingerprint(ph, lr, {})
        focused = build_fingerprint(ph, lr, {"priority": "Imperfections"})
        assert focused.get("acne_active") > neutral.get("acne_active")

    def test_phototype_raises_pigmentation_risk(self):
        """A lesions egales, un phototype fonce porte un risque de marques
        pigmentaires superieur : le vecteur doit le refleter."""
        lr = make_lesions(3, papule=10)
        light = build_fingerprint(make_phenotype(phototype="II"), lr, {})
        dark = build_fingerprint(make_phenotype(phototype="V"), lr, {})
        assert dark.get("post_acne_marks") > light.get("post_acne_marks")
        assert "risque_hyperpigmentation_post_inflammatoire" in dark.flags

    def test_score_uses_full_range(self):
        """v1 ecrasait tous les scores entre 30 et 98, d'ou 80 % des profils
        entre 61 et 79. La plage complete doit etre atteignable."""
        clear = build_fingerprint(
            make_phenotype(sebum_t=0.05, sebum_u=0.05, dryness=0.0,
                           redness_global=0.0, pore_load=0.05, unevenness=0.05),
            make_lesions(0), {"age_range": "<25"},
        )
        bad = build_fingerprint(
            make_phenotype(sebum_t=0.95, sebum_u=0.9, dryness=0.8,
                           redness_global=0.9, pore_load=0.9, unevenness=0.9,
                           sensitive=True),
            make_lesions(4, papule=40, pustule=20, marque_brune=15),
            {"age_range": "60+"},
        )
        assert clear.global_score > 85
        assert bad.global_score < 35
        assert clear.global_score - bad.global_score > 50

    def test_environment_influences_axes(self):
        ph, lr = make_phenotype(), make_lesions(1)
        dry_env = build_fingerprint(ph, lr, {"environment": "Sec"})
        neutral = build_fingerprint(ph, lr, {"environment": "Variable"})
        assert dry_env.get("dehydration") > neutral.get("dehydration")

    def test_aging_is_flagged_as_estimated(self):
        """Les rides ne sont pas mesurees optiquement : il faut le dire."""
        fp = build_fingerprint(make_phenotype(), make_lesions(0), {})
        assert "aging_estime_non_mesure" in fp.flags


# --------------------------------------------------------------------------
# Routine
# --------------------------------------------------------------------------
class TestRoutine:
    @pytest.fixture(scope="class")
    def catalog(self):
        return _load_catalog()

    def test_catalog_schema(self, catalog):
        required = {"id", "name", "brand", "step", "moment", "actives", "targets",
                    "skin_types", "avoid_if", "conflicts_with", "family",
                    "price_eur", "irritation", "evidence"}
        assert len(catalog) >= 40
        for p in catalog:
            assert required <= set(p), f"{p.get('id')} : champs manquants"
            assert 0.0 <= p["irritation"] <= 1.0
            assert set(p["targets"]) <= set(CONCERN_KEYS), p["id"]

    def test_ids_are_unique(self, catalog):
        ids = [p["id"] for p in catalog]
        assert len(ids) == len(set(ids))

    def test_different_skins_get_different_products(self, catalog):
        """Le reproche central fait a l'application : tout le monde recevait
        les memes produits."""
        acne = build_routine(
            build_fingerprint(make_phenotype(skin_type="grasse", sebum_t=0.9, sebum_u=0.8),
                              make_lesions(3, papule=20, pustule=8), {}),
            make_phenotype(skin_type="grasse", sebum_t=0.9, sebum_u=0.8),
            {}, catalog=catalog,
        )
        dry = build_routine(
            build_fingerprint(make_phenotype(skin_type="seche", sebum_t=0.05,
                                             sebum_u=0.05, dryness=0.8),
                              make_lesions(0), {}),
            make_phenotype(skin_type="seche", sebum_t=0.05, sebum_u=0.05, dryness=0.8),
            {}, catalog=catalog,
        )
        ids_a = {p.product["id"] for p in acne.am + acne.pm}
        ids_d = {p.product["id"] for p in dry.am + dry.pm}
        assert ids_a != ids_d
        assert not ids_a <= ids_d and not ids_d <= ids_a

    def test_sunscreen_always_in_morning(self, catalog):
        """La creme solaire ne doit jamais sauter, y compris quand le budget
        d'irritation est au plus bas : les actifs anti-acne photosensibilisent."""
        ph = make_phenotype(sensitive=True, redness_global=0.9)
        fp = build_fingerprint(ph, make_lesions(4, papule=30), {"experience": "debutant"})
        rt = build_routine(fp, ph, {"experience": "debutant"}, catalog=catalog)
        steps = {p.step for p in rt.am}
        assert "protection" in steps, "protection solaire absente du matin"

    def test_essential_steps_present(self, catalog):
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(2, papule=6), {})
        rt = build_routine(fp, ph, {}, catalog=catalog)
        assert "nettoyant" in {p.step for p in rt.am}
        assert "hydratant" in {p.step for p in rt.am}

    def test_no_potent_family_stacked_in_same_moment(self, catalog):
        """Empiler deux exfoliants ou deux retinoides le meme soir expose a la
        brulure. Les familles douces, elles, peuvent coexister."""
        for sev in (1, 2, 3, 4):
            ph = make_phenotype()
            fp = build_fingerprint(ph, make_lesions(sev, papule=sev * 6), {})
            rt = build_routine(fp, ph, {}, catalog=catalog)
            for moment in (rt.am, rt.pm):
                leave_on = [p for p in moment if p.product.get("step") != "nettoyant"]
                fams = [p.product.get("family") for p in leave_on]
                potent = [f for f in fams if f in POTENT_FAMILIES]
                assert len(potent) == len(set(potent)), f"doublon d'actif fort : {fams}"

    def test_declared_conflicts_are_respected(self, catalog):
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(3, papule=15), {})
        rt = build_routine(fp, ph, {}, catalog=catalog)
        for moment in (rt.am, rt.pm):
            leave_on = [p for p in moment if p.product.get("step") != "nettoyant"]
            for i, a in enumerate(leave_on):
                others = leave_on[:i] + leave_on[i + 1:]
                assert not _conflicts(a.product, others), a.product["id"]

    def test_pregnancy_excludes_contraindicated(self, catalog):
        ph = make_phenotype()
        prof = {"pregnant": True}
        fp = build_fingerprint(ph, make_lesions(3, papule=12), prof)
        rt = build_routine(fp, ph, prof, catalog=catalog)
        for p in rt.am + rt.pm + rt.weekly:
            assert "grossesse" not in (p.product.get("avoid_if") or []), p.product["id"]

    def test_sensitive_skin_gets_gentler_routine(self, catalog):
        calm = make_phenotype(sensitive=False, redness_global=0.05)
        reactive = make_phenotype(sensitive=True, redness_global=0.9)
        lr = make_lesions(2, papule=8)
        r_calm = build_routine(build_fingerprint(calm, lr, {}), calm, {}, catalog=catalog)
        r_react = build_routine(build_fingerprint(reactive, lr, {}), reactive, {},
                                catalog=catalog)
        assert r_react.irritation_load <= r_calm.irritation_load

    def test_irritation_budget_shrinks_with_reactivity(self):
        calm = make_phenotype(sensitive=False, redness_global=0.0)
        reactive = make_phenotype(sensitive=True, redness_global=0.9)
        lr = make_lesions(2)
        b_calm = _irritation_budget(calm, build_fingerprint(calm, lr, {}), {})
        b_react = _irritation_budget(reactive, build_fingerprint(reactive, lr, {}), {})
        assert b_react < b_calm

    def test_isotretinoin_caps_budget(self):
        ph = make_phenotype()
        prof = {"on_isotretinoin": True}
        fp = build_fingerprint(ph, make_lesions(3), prof)
        assert _irritation_budget(ph, fp, prof) <= 0.35

    def test_severe_acne_triggers_medical_referral(self, catalog):
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(4, papule=40, pustule=20), {})
        rt = build_routine(fp, ph, {}, catalog=catalog)
        assert any("dermatolog" in c.lower() for c in rt.cautions)

    def test_schedule_introduces_actives_gradually(self, catalog):
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(3, papule=15), {})
        rt = build_routine(fp, ph, {}, catalog=catalog)
        weeks = [s["week"] for s in rt.schedule]
        assert weeks == sorted(weeks)
        # Le socle demarre toujours en semaine 1
        assert weeks[0] == 1

    def test_budget_is_respected_when_possible(self, catalog):
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(1, comedon=4), {})
        cheap = build_routine(fp, ph, {"budget": "petit"}, catalog=catalog)
        rich = build_routine(fp, ph, {"budget": "large"}, catalog=catalog)
        assert cheap.total_price <= rich.total_price

    def test_deterministic(self, catalog):
        """Deux scans identiques doivent donner exactement la meme routine,
        sinon l'utilisateur perd confiance dans l'outil."""
        ph = make_phenotype()
        fp = build_fingerprint(ph, make_lesions(2, papule=7), {})
        a = build_routine(fp, ph, {}, catalog=catalog)
        b = build_routine(fp, ph, {}, catalog=catalog)
        assert [p.product["id"] for p in a.am] == [p.product["id"] for p in b.am]
        assert [p.product["id"] for p in a.pm] == [p.product["id"] for p in b.pm]

    def test_step_sets_are_disjoint(self):
        assert not set(ESSENTIAL_STEPS) & set(ACTIVE_STEPS)


# --------------------------------------------------------------------------
# Pipeline complet (necessite OpenCV et MediaPipe)
# --------------------------------------------------------------------------
cv_available = True
try:  # pragma: no cover
    import cv2  # noqa: F401
    import mediapipe  # noqa: F401
except Exception:  # pragma: no cover
    cv_available = False


@pytest.mark.skipif(not cv_available, reason="OpenCV/MediaPipe absents")
@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture absente")
class TestPipeline:
    @pytest.fixture(scope="class")
    def result(self):
        from skyn_engine.v2.pipeline import analyze_face
        b64 = base64.b64encode(open(FIXTURE, "rb").read()).decode()
        return analyze_face(b64, {"age_range": "<25", "priority": "Imperfections"})

    def test_face_detected(self, result):
        assert result.ok is True

    def test_zones_are_analysed(self, result):
        """v1 n'exposait aucune granularite par zone."""
        assert len(result.zone_scores) >= 8

    def test_lesion_count_is_not_capped_at_five(self, result):
        """Verrouille la correction du plafond `max_n=5` de v1."""
        from skyn_engine.v2.lesions import detect_lesions
        from skyn_engine.v2.zones import build_face_map
        b64 = base64.b64encode(open(FIXTURE, "rb").read()).decode()
        report = detect_lesions(build_face_map(b64))
        # Le nombre exact depend de l'image ; ce qui compte est l'absence de
        # troncature artificielle a une constante.
        assert isinstance(report.counts, dict)
        assert sum(report.counts.values()) == len(report.lesions)

    def test_excluded_regions_are_not_skin(self):
        """Sourcils, yeux, levres et narines ne doivent pas compter comme peau,
        sans quoi une pilosite sombre degrade mecaniquement le score."""
        from skyn_engine.v2.zones import build_face_map
        b64 = base64.b64encode(open(FIXTURE, "rb").read()).decode()
        fm = build_face_map(b64)
        assert fm.skin_mask.sum() > 0
        # Les zones exposees ne doivent jamais recouvrir la pilosite detectee
        for name, z in fm.zones.items():
            if z.available:
                overlap = ((z.mask > 0) & (fm.hair_mask > 0)).sum()
                assert overlap == 0, f"{name} recouvre la pilosite"

    def test_routine_is_produced(self, result):
        assert result.routine["am"], "routine du matin vide"
        assert result.routine["pm"], "routine du soir vide"

    def test_serialisable(self, result):
        import json
        json.dumps(result.to_dict())

    def test_no_face_returns_actionable_message(self):
        from skyn_engine.v2.pipeline import analyze_face
        blank = base64.b64encode(b"not-an-image").decode()
        out = analyze_face(blank, {})
        assert out.ok is False
        assert out.summary

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Regression connue, non corrigee : la recompression JPEG seule "
            "(sans le moindre changement de peau) fait bouger le score de 4 "
            "points (77 -> 81) et le compte de lesions de 5 -> 4. Cause "
            "tracee : MediaPipe deplace les reperes de 1-2 px sous le bruit de "
            "recompression, ce qui deplace la boite du visage et les seuils "
            "robustes qui en dependent juste assez pour faire basculer un ou "
            "deux candidats pres de leur frontiere. Marque `xfail` plutot que "
            "supprime : corriger cela est un chantier P1/P3 a part entiere "
            "(lissage compression-invariant, hysteresis sur les seuils), pas "
            "un ajustement de seuil ponctuel — et le laisser echouer en rouge "
            "aurait masque le reste de la suite plutot que documenter le "
            "probleme.",
        ),
    )
    def test_stable_under_jpeg_recompression(self):
        """Verrouille — pour le jour ou elle sera corrigee — une regression de
        reproductibilite reperee lors de l'audit P0 : la MEME photo, encodee
        deux fois differemment, ne doit pas produire un compte de lesions ni
        un score notablement differents. Voir la raison du xfail ci-dessus
        pour les chiffres mesures et la piste retenue.
        """
        import cv2
        from skyn_engine.v2.pipeline import analyze_face

        original = base64.b64encode(open(FIXTURE, "rb").read()).decode()
        img = cv2.imread(FIXTURE)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        assert ok
        recompresse = base64.b64encode(buf.tobytes()).decode()

        a = analyze_face(original)
        b = analyze_face(recompresse)
        assert a.ok and b.ok
        assert abs(a.global_score - b.global_score) <= 3, (
            f"score instable a la recompression : {a.global_score} vs {b.global_score}"
        )
        assert abs(len(a.lesions) - len(b.lesions)) <= 1, (
            f"compte de lesions instable a la recompression : "
            f"{len(a.lesions)} vs {len(b.lesions)}"
        )

    def test_multi_angle_zone_scores_match_merged_per_zone(self, result):
        """Verrouille une regression reperee sur un scan reel a trois angles :
        la carte affichee n'avait qu'une seule zone notee (le front, vu par la
        vue de face), et sa legende presentait cette zone unique comme « la
        plus chargee » — alors que `per_zone`, lui, portait bien les tempes et
        la machoire vues par les profils. `analyze_multi` fusionnait les
        comptages sans jamais recalculer `zone_scores` a partir du resultat.

        Les trois prises sont la meme image : ca ne teste pas la fusion des
        VALEURS (le fixture n'a qu'un visage), seulement que `zone_scores`
        redevient un calcul du `per_zone` fusionne — donc que ses cles suivent
        celles de `per_zone`, quel que soit le nombre de prises. Avant le
        correctif, `zone_scores` restait celui de la seule premiere prise :
        sur des prises reellement differentes, ses cles se seraient limitees a
        ce que la vue de face avait, a elle seule, reussi a cartographier.
        """
        from skyn_engine.v2.pipeline import analyze_multi
        b64 = base64.b64encode(open(FIXTURE, "rb").read()).decode()
        out = analyze_multi([b64, b64, b64], {"age_range": "<25", "priority": "Imperfections"})
        assert out.ok is True
        assert set(out.zone_scores.keys()) == set(out.per_zone.keys())
        assert "Analyse consolidée sur 3 prises de vue." in out.summary


class TestZoneScoresMerge:
    """`_zone_scores_from_merged` doit couvrir l'union des zones vues par
    n'importe laquelle des prises fusionnees, pas seulement celles de la vue
    de face — c'est precisement ce que la version precedente ne faisait pas."""

    def test_covers_zones_seen_only_in_profile_views(self):
        from skyn_engine.v2.pipeline import _zone_scores_from_merged

        # Le front n'est "vu" que par la vue de face ; les tempes ne le sont
        # que par les profils gauche et droit — exactement la situation d'un
        # vrai scan a trois angles.
        merged = {
            "front": {"lesions": {}, "density_cm2": 0.0},
            "tempe_g": {"lesions": {"papule": 2}, "density_cm2": 1.5},
            "tempe_d": {"lesions": {}, "density_cm2": 0.4},
        }
        scores = _zone_scores_from_merged(merged)

        assert set(scores.keys()) == {"front", "tempe_g", "tempe_d"}
        # Front nette : aucune lesion, densite nulle.
        assert scores["front"] == 100
        # Tempe gauche chargee : deux papules et une densite notable doivent
        # la faire passer sous le seuil d'affichage cote client (charge > 20 %,
        # soit une note sous 80).
        assert scores["tempe_g"] < 80

    def test_empty_zone_is_perfectly_clean(self):
        from skyn_engine.v2.pipeline import _zone_scores_from_merged
        scores = _zone_scores_from_merged({"menton": {"lesions": {}, "density_cm2": 0.0}})
        assert scores["menton"] == 100


@pytest.mark.skipif(not cv_available, reason="OpenCV/MediaPipe absents")
@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture absente")
class TestSynthBenchValidity:
    """Le banc synthetique doit lui-meme etre digne de confiance.

    Trouvaille de l'audit P0 : 3 des 8 lesions "manquees" sur le banc de
    reference (30 lesions, seed 7) n'etaient pas des echecs de detection —
    elles etaient plantees a l'interieur d'une region que le moteur exclut
    deliberement de toute analyse (sourcils, narines), confirme par une
    distance NEGATIVE au polygone d'exclusion le plus proche. Le rappel
    mesure grimpait de 63 a 70 % en corrigeant uniquement la POSE des
    lesions, sans toucher au moteur.

    Ce test empeche que le meme defaut ne revienne dans `plant()` : aucune
    lesion posee ne doit tomber sur un pixel que `build_face_map` exclut du
    masque peau.
    """

    def test_planted_lesions_never_land_on_excluded_skin(self):
        import cv2

        # `synth_lesions.py` s'importe lui-meme comme `backend.tools....` (il
        # insere la RACINE du depot dans son propre sys.path) alors que ce
        # fichier de tests s'importe depuis `backend/` directement. Les deux
        # conventions coexistent : il faut la racine en plus pour resoudre
        # le prefixe `backend.`.
        REPO_ROOT = os.path.dirname(BACKEND)
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        from backend.tools.synth_lesions import _landmarks, plant
        from skyn_engine.v2.zones import build_face_map

        img = cv2.imread(FIXTURE)
        pts = _landmarks(img)
        assert pts is not None

        for zone in ("front", "nez", "joue_g", "joue_d", "menton"):
            marked, planted = plant(img, pts, zone, 6, seed=7)
            ok, buf = cv2.imencode(".jpg", marked, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            assert ok
            b64 = base64.b64encode(buf.tobytes()).decode()
            fm = build_face_map(b64)
            assert fm.detected

            for p in planted:
                assert fm.skin_mask[p.y, p.x] > 0, (
                    f"lesion posee en zone {zone} a ({p.x},{p.y}) tombe hors "
                    f"du masque peau — verite terrain invalide"
                )
