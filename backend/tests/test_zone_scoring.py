"""Banc de validation de skyn_engine.v2.zone_scoring — le module qui derive
`zone_scores` des lesions DEJA confirmees par un scan multi-vue guide.

Cinq garanties pre-enregistrees avant integration produit (voir la decision
utilisateur qui a ouvert ce chantier) :
1. coherence anatomique — une lesion d'une zone n'alimente jamais une autre ;
2. stabilite — memes lesions confirmees en entree, meme zone_scores en sortie ;
3. monotonie — ajouter une lesion confirmee dans une zone ne peut jamais
   ameliorer son score ;
4. coherence visuelle — une zone chargee ressort nettement, les autres
   restent lisibles (verifie plus haut, cote produit, sur de vraies donnees ;
   ici on verifie la meme chose au niveau du calcul : burden croissant ->
   score decroissant, sur toute la plage) ;
5. absence de regression — verifiee separement en faisant tourner toute la
   suite existante (97 tests) apres ce chantier, pas ici.

Aucune image reelle necessaire : ce module ne fait plus de detection, donc
ses tests construisent des `ScanResult` a la main — memes conventions que
`test_skin_memory.py::TestGuidedScanChanges._guided`.
"""
from __future__ import annotations

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from skyn_engine.v2.multiview import ScanResult  # noqa: E402
from skyn_engine.v2.zone_scoring import zone_scores_from_confirmed  # noqa: E402


def _lesion(zone: str, ltype: str = "papule", x: float = 0.5, y: float = 0.5) -> dict:
    return {"x": x, "y": y, "type": ltype, "zone": zone, "n_observations": 3,
            "coherence_photo": 0.9, "evidence": 0.9}


def _result(lesions, zones_couvertes, zone_area_cm2) -> ScanResult:
    return ScanResult(
        lesions_confirmees=lesions,
        n_vues_recues=7, n_vues_utilisables=7, raison_arret="cible_atteinte_stable",
        vues_diagnostics=[],
        zones_couvertes=zones_couvertes,
        zone_area_cm2=zone_area_cm2,
    )


class TestCoherenceAnatomique:
    def test_lesion_n_alimente_que_sa_propre_zone(self):
        result = _result(
            lesions=[_lesion("nez"), _lesion("nez"), _lesion("joue_g")],
            zones_couvertes=["nez", "joue_g", "front"],
            zone_area_cm2={"nez": 4.0, "joue_g": 4.0, "front": 4.0},
        )
        scores = zone_scores_from_confirmed(result)
        # nez porte 2 lesions, joue_g 1, front 0 : nez doit etre strictement
        # la zone la plus chargee, front la plus propre. Une fuite entre
        # zones romprait cet ordre.
        assert scores["nez"] < scores["joue_g"] < scores["front"]

    def test_lesion_zone_inconnue_ignoree_sans_crash(self):
        result = _result(
            lesions=[_lesion("autre"), _lesion("nez")],
            zones_couvertes=["nez"],
            zone_area_cm2={"nez": 4.0},
        )
        scores = zone_scores_from_confirmed(result)
        assert set(scores.keys()) == {"nez"}


class TestZoneNonMesuree:
    def test_zone_non_couverte_absente_du_resultat(self):
        """Une zone hors de zones_couvertes n'apparait JAMAIS, meme si une
        lesion (donnee incoherente, ne devrait pas arriver) la reference :
        la couverture reelle du scan prime toujours sur les lesions."""
        result = _result(
            lesions=[_lesion("machoire_g")],
            zones_couvertes=["nez"],  # machoire_g volontairement absente
            zone_area_cm2={"nez": 4.0, "machoire_g": 4.0},
        )
        scores = zone_scores_from_confirmed(result)
        assert "machoire_g" not in scores
        assert scores == {"nez": 100}  # nez couverte, zero lesion -> nette

    def test_zone_sans_aire_exploitable_absente(self):
        result = _result(
            lesions=[], zones_couvertes=["nez"], zone_area_cm2={"nez": 0.0},
        )
        assert zone_scores_from_confirmed(result) == {}

    def test_zone_couverte_zero_lesion_score_maximal(self):
        result = _result(lesions=[], zones_couvertes=["front"], zone_area_cm2={"front": 6.0})
        assert zone_scores_from_confirmed(result) == {"front": 100}


class TestStabilite:
    def test_meme_scan_meme_score(self):
        lesions = [_lesion("nez"), _lesion("nez", "comedon"), _lesion("joue_d", "pustule")]
        result = _result(lesions, ["nez", "joue_d", "front"],
                          {"nez": 3.0, "joue_d": 5.0, "front": 6.0})
        a = zone_scores_from_confirmed(result)
        b = zone_scores_from_confirmed(result)
        assert a == b

    def test_ordre_des_lesions_n_affecte_pas_le_score(self):
        lesions = [_lesion("nez"), _lesion("nez", "comedon"), _lesion("joue_d", "pustule")]
        r1 = _result(lesions, ["nez", "joue_d"], {"nez": 3.0, "joue_d": 5.0})
        r2 = _result(list(reversed(lesions)), ["nez", "joue_d"], {"nez": 3.0, "joue_d": 5.0})
        assert zone_scores_from_confirmed(r1) == zone_scores_from_confirmed(r2)


class TestMonotonie:
    def test_ajouter_une_lesion_ne_peut_pas_ameliorer_le_score(self):
        base = _result([_lesion("nez")], ["nez"], {"nez": 4.0})
        plus_charge = _result([_lesion("nez"), _lesion("nez")], ["nez"], {"nez": 4.0})
        assert zone_scores_from_confirmed(plus_charge)["nez"] <= zone_scores_from_confirmed(base)["nez"]

    def test_ajouter_une_lesion_inflammatoire_ne_peut_pas_ameliorer_le_score(self):
        avant = _result([_lesion("joue_g", "comedon")], ["joue_g"], {"joue_g": 4.0})
        apres = _result(
            [_lesion("joue_g", "comedon"), _lesion("joue_g", "papule")],
            ["joue_g"], {"joue_g": 4.0},
        )
        assert zone_scores_from_confirmed(apres)["joue_g"] <= zone_scores_from_confirmed(avant)["joue_g"]

    def test_monotonie_sur_une_plage_croissante_de_charge(self):
        """Charge une zone lesion par lesion : le score ne doit jamais
        remonter d'un palier au suivant."""
        precedent = None
        for n in range(0, 8):
            lesions = [_lesion("nez") for _ in range(n)]
            result = _result(lesions, ["nez"], {"nez": 4.0})
            score = zone_scores_from_confirmed(result)["nez"]
            if precedent is not None:
                assert score <= precedent
            precedent = score


class TestCoherenceVisuelle:
    def test_zone_chargee_ressort_des_zones_propres(self):
        """Une seule zone nettement chargee doit rester nettement la plus
        basse — pas noyee par un effet d'echelle qui aplatirait toutes les
        zones vers le meme score."""
        result = _result(
            lesions=[_lesion("nez") for _ in range(6)],
            zones_couvertes=["nez", "front", "joue_g", "joue_d", "menton"],
            zone_area_cm2={"nez": 3.0, "front": 6.0, "joue_g": 5.0, "joue_d": 5.0, "menton": 4.0},
        )
        scores = zone_scores_from_confirmed(result)
        propres = [v for k, v in scores.items() if k != "nez"]
        assert all(v == 100 for v in propres)
        assert scores["nez"] < 60  # forte densite (2/cm2) : doit se voir

    def test_scores_toujours_dans_0_100(self):
        result = _result(
            lesions=[_lesion("nez") for _ in range(50)],
            zones_couvertes=["nez"], zone_area_cm2={"nez": 1.0},
        )
        scores = zone_scores_from_confirmed(result)
        assert 0 <= scores["nez"] <= 100
