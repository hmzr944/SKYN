"""Calibration RED/DARK — banc formel (chantier demandé après le diagnostic
multi-photo). Ne modifie NI lesions.py NI calibration.py : à aucun moment le
fichier sur disque n'est touché. La comparaison entre formulations se fait
en substituant `skyn_engine.v2.lesions._classify` par une variante, en
mémoire, pour la durée d'un appel — puis restaurée. Toute la mécanique
autour (candidats, dedup, zones, confiance, pipeline complet) reste le vrai
`detect_lesions`/`analyze_face`, jamais réimplémentée.

────────────────────────────────────────────────────────────────────────
PROTOCOLE (repris du prompt de cadrage)

  TRAIN        capture_006, capture_007       -> a servi a choisir la PLAGE
                                                  des grilles ci-dessous
                                                  (pas a choisir une valeur).
  CALIBRATION  capture_005, capture_008       -> selectionne le meilleur
                                                  point de grille par
                                                  formulation.
  VALIDATION   capture_001..004               -> jamais touchees avant ce
                                                  script, jamais utilisees
                                                  dans un diagnostic
                                                  precedent de cette session.
                                                  Evaluees UNE FOIS, a la fin.

REGLE DE SELECTION — aucun seuil de tolerance choisi a la main : un point de
grille n'est retenu QUE s'il ne cree AUCUN nouveau faux positif (sur les
zones saines de reference) et ne degrade PAS la stabilite same-skin par
rapport a F0 (la regle de production actuelle), mesuree sur les MEMES
captures. Parmi les points qui passent ce filtre, on garde celui qui
maximise le rappel. Un filtre a tolerance zero, empirique (mesure sur F0
lui-meme), pas invente.

LIMITE HONNETE, a lire avant les chiffres : 4 captures d'un seul sujet en
train+calibration, 4 en validation (dont 3 du meme sujet) — un echantillon
tres petit. Ce banc est directionnel, pas une preuve statistique. Il dit
"cette formulation ne regresse sur rien de mesure ici", pas "elle
generalise a toute la population".

Usage :
    python3 backend/tools/red_dark_calibration_bench.py
"""
from __future__ import annotations

import base64
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import skyn_engine.v2.lesions as lesions_mod  # noqa: E402
from skyn_engine.v2.lesions import RED_IF_DARK  # noqa: E402
from skyn_engine.v2.pipeline import analyze_face  # noqa: E402
from tools.synth_lesions import _landmarks, plant  # noqa: E402
from tools.stability_bench import PERTURBATIONS, _appareiller  # noqa: E402
from tools.cheek_candidate_diagnostic import (  # noqa: E402
    Champs, _b64_from_bgr, _candidats, _charger_oriente_bgr,
)

SUBJECT = Path("/home/user/real_skin_pilot/subject_001")
TRAIN = [SUBJECT / "capture_006.jpg", SUBJECT / "capture_007.jpg"]
CALIBRATION = [SUBJECT / "capture_005.jpg", SUBJECT / "capture_008.jpg"]
VALIDATION = [SUBJECT / f"capture_{i}.jpg" for i in ("001", "002", "003", "004")]

ZONES_RECALL = ("joue_g", "joue_d", "front", "menton")
N_PAR_ZONE = 3
SEED = 17

# Sous-echantillon de perturbations pour le BALAYAGE (cout), jeu complet de
# stability_bench.py pour la formulation retenue en validation finale.
PERTURBATIONS_BALAYAGE = [p for p in PERTURBATIONS if p.nom in (
    "jpeg_q85", "jpeg_q60", "luminosite_+15", "luminosite_-15",
    "contraste_+15%", "rotation_+2deg",
)]


# ─────────────────────────────────────────────────────────────────────────
# Le classify() reel, copie UNE SEULE FOIS (lesions.py:411-460), avec la
# relation red/dark de la branche papule rendue substituable. Tout le reste
# — pustule, comedon, marque_rouge, marque_brune — est un copier verbatim,
# jamais touche par les formulations testees ici.
# ─────────────────────────────────────────────────────────────────────────
PapuleTest = Callable[[float, float, float], bool]


def make_classify(papule_test: PapuleTest):
    def classify(red, dark, yellow, core_l, core_s, skin_s, r_px, px_per_mm, src):
        d_mm = 2.0 * r_px / px_per_mm
        if red > 1.6 and core_l > 0.8 and core_s < skin_s * 0.82:
            return "pustule"
        if d_mm >= 1.2 and papule_test(red, dark, d_mm):
            return "papule"
        if dark < -1.5 and red < 1.6 and d_mm <= 2.2 and yellow > 0.35:
            if core_s < skin_s * 0.55:
                return None
            return "comedon"
        if red > 1.2 and abs(dark) < 1.0 and d_mm > 1.8:
            return "marque_rouge"
        if dark < -1.0 and yellow > 0.5 and red < 1.2:
            return "marque_brune"
        return None
    return classify


def _f0_papule(red: float, dark: float, d_mm: float) -> bool:
    return (dark > -1.2 and red > 1.8) or (dark <= -1.2 and red > RED_IF_DARK)


F0 = make_classify(_f0_papule)


@contextmanager
def classify_override(fn):
    original = lesions_mod._classify
    lesions_mod._classify = fn
    try:
        yield
    finally:
        lesions_mod._classify = original


def _verifier_harnais() -> None:
    """F0 (la copie) doit produire EXACTEMENT le meme verdict que le vrai
    _classify() sur un vrai lot de candidats — sinon tout le reste de ce
    banc mesure une fiction. Arret immediat en cas de divergence."""
    bgr = _charger_oriente_bgr(CALIBRATION[0])
    from tools.cheek_candidate_diagnostic import build_face_map
    fm = build_face_map(_b64_from_bgr(bgr))
    champs = Champs(fm)
    cands = _candidats(champs)  # utilise le VRAI _classify() en interne
    if not cands:
        raise SystemExit("harnais : aucun candidat pour verifier — jeu de test insuffisant")
    n_verifies = 0
    for c in cands:
        rejoue = F0(c.red, c.dark, c.yellow, c.core_l, c.core_s, c.skin_s, c.r_px,
                    champs.px_per_mm, c.src)
        attendu = c.type
        if rejoue != attendu:
            raise SystemExit(
                f"HARNAIS INVALIDE : F0 rejoue={rejoue!r} mais vrai _classify()={attendu!r} "
                f"sur candidat ({c.cx},{c.cy}) — arret, aucun chiffre de ce banc n'est fiable."
            )
        n_verifies += 1
    print(f"Harnais vérifié : F0 reproduit exactement le vrai _classify() sur "
          f"{n_verifies} candidats réels (0 divergence).\n")


# ─────────────────────────────────────────────────────────────────────────
# Rappel / faux positifs — meme methode que synth_lesions.py::evaluate(),
# adaptee pour tourner sous classify_override().
# ─────────────────────────────────────────────────────────────────────────
def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


def rappel_et_faux_positifs(classify_fn, photos: List[Path]) -> Dict[str, float]:
    from collections import Counter
    total_posees = total_gagnees = total_fp_reference = 0
    with classify_override(classify_fn):
        for photo in photos:
            bgr = _charger_oriente_bgr(photo)
            ref = analyze_face(_b64(bgr, quality=100))
            if not ref.ok:
                continue
            ref_zone = Counter(l["zone"] for l in ref.lesions)
            total_fp_reference += len(ref.lesions)

            pts = _landmarks(bgr)
            if pts is None:
                continue
            for zone in ZONES_RECALL:
                try:
                    marque, planted = plant(bgr, pts, zone, N_PAR_ZONE, seed=SEED)
                except SystemExit:
                    continue
                rep = analyze_face(_b64(marque, quality=100))
                if not rep.ok:
                    continue
                by_zone = Counter(l["zone"] for l in rep.lesions)
                gagnees = max(0, by_zone[zone] - ref_zone[zone])
                total_posees += len(planted)
                total_gagnees += gagnees

    recall = total_gagnees / total_posees if total_posees else 0.0
    return {"recall": recall, "n_posees": total_posees, "n_gagnees": total_gagnees,
            "faux_positifs_reference": total_fp_reference}


# ─────────────────────────────────────────────────────────────────────────
# Stabilite same-skin — reutilise stability_bench.py telle quelle.
# ─────────────────────────────────────────────────────────────────────────
def stabilite(classify_fn, photo: Path, perturbations) -> Dict[str, float]:
    bgr = _charger_oriente_bgr(photo)
    with classify_override(classify_fn):
        base = analyze_face(_b64(bgr, quality=100))
        if not base.ok:
            return {"instabilite": float("inf"), "echecs": len(perturbations)}
        total_perdues = total_type = total_zone = echecs = 0
        for p in perturbations:
            modifiee = p.applique(bgr)
            out = analyze_face(_b64(modifiee, quality=p.qualite_jpeg))
            if not out.ok:
                echecs += 1
                continue
            appariees = _appareiller(base.lesions, out.lesions)
            total_perdues += sum(1 for _, n in appariees if n is None)
            total_type += sum(1 for r, n in appariees if n is not None and n["type"] != r["type"])
            total_zone += sum(1 for r, n in appariees if n is not None and n["zone"] != r["zone"])
    # Un seul score agrege : plus bas = plus stable. Pas de ponderation
    # choisie a la main entre les trois composantes — simple somme, chacune
    # etant deja un compte d'evenements de meme nature (une lesion qui
    # bouge de categorie).
    instabilite = total_perdues + total_type + total_zone
    return {"instabilite": instabilite, "perdues": total_perdues,
            "type_change": total_type, "zone_change": total_zone, "echecs": echecs}


# ─────────────────────────────────────────────────────────────────────────
# Formulations candidates. UNIQUEMENT la relation red/dark de la branche
# papule change ; d_mm>=1.2 reste la garde de taille, inchangee partout.
# ─────────────────────────────────────────────────────────────────────────
def formulation_f1(c_fort: float, t_moyen: float, t_fort: float) -> PapuleTest:
    """3 paliers : dark faible (>-1.2, inchange), dark moyen (entre -1.2 et
    c_fort), dark fort (<=c_fort) — chacun son propre seuil de rouge."""
    def test(red: float, dark: float, d_mm: float) -> bool:
        if dark > -1.2:
            return red > 1.8
        if dark > c_fort:
            return red > t_moyen
        return red > t_fort
    return test


def formulation_f2(a: float, b: float) -> PapuleTest:
    """Croissance lineaire du rouge exige avec l'obscurite, au lieu d'un
    saut brutal a 4,5 des que dark<=-1.2. Plafonnee a 6.0 pour eviter une
    exigence absurde sur une obscurite extreme."""
    def test(red: float, dark: float, d_mm: float) -> bool:
        if dark > -1.2:
            return red > 1.8
        exige = min(6.0, a + b * (-dark - 1.2))
        return red > exige
    return test


def formulation_f3(k: float) -> PapuleTest:
    """Score combine normalise par l'obscurite plutot qu'un seuil de rouge
    absolu."""
    def test(red: float, dark: float, d_mm: float) -> bool:
        if dark > -1.2:
            return red > 1.8
        score = red / (1.0 + max(0.0, -dark - 1.2) / 10.0)
        return score > k
    return test


GRID_F1 = [
    (c_fort, t_moyen, t_fort)
    for c_fort in (-6.0, -10.0)
    for t_moyen in (2.2, 2.8, 3.4)
    for t_fort in (4.5, 6.0)
]
GRID_F2 = [(a, b) for a in (1.8, 2.2) for b in (0.05, 0.15, 0.3)]
GRID_F3 = [(k,) for k in (1.6, 1.8, 2.0, 2.2)]


def main() -> None:
    print("Vérification du harnais (F0 doit être identique au vrai _classify)")
    print("=" * 100)
    _verifier_harnais()

    print("=" * 100)
    print("RÉFÉRENCE F0 (règle de production actuelle) — mesurée sur CALIBRATION")
    print("=" * 100)
    ref_rp = rappel_et_faux_positifs(F0, CALIBRATION)
    ref_stab = [stabilite(F0, p, PERTURBATIONS_BALAYAGE) for p in CALIBRATION]
    ref_instab = sum(s["instabilite"] for s in ref_stab)
    print(f"Rappel F0            : {ref_rp['recall']:.1%}  "
          f"({ref_rp['n_gagnees']}/{ref_rp['n_posees']})")
    print(f"Faux positifs F0     : {ref_rp['faux_positifs_reference']} "
          f"(sur photos de référence, non marquées)")
    print(f"Instabilité F0       : {ref_instab} "
          f"(somme lésions perdues + changements type/zone, "
          f"{len(PERTURBATIONS_BALAYAGE)} perturbations × {len(CALIBRATION)} photos)\n")

    formulations = (
        [("F1", make_classify(formulation_f1(*p)), p) for p in GRID_F1]
        + [("F2", make_classify(formulation_f2(*p)), p) for p in GRID_F2]
        + [("F3", make_classify(formulation_f3(*p)), p) for p in GRID_F3]
    )

    print("=" * 100)
    print(f"BALAYAGE — {len(formulations)} points de grille, mesurés sur CALIBRATION")
    print("=" * 100)
    print(f"{'formulation':<8}{'params':<26}{'rappel':>9}{'Δrappel':>10}{'FP':>5}"
          f"{'ΔFP':>6}{'instab.':>9}{'Δinstab.':>10}{'retenu':>9}")

    resultats = []
    for nom, fn, params in formulations:
        rp = rappel_et_faux_positifs(fn, CALIBRATION)
        stab = [stabilite(fn, p, PERTURBATIONS_BALAYAGE) for p in CALIBRATION]
        instab = sum(s["instabilite"] for s in stab)

        d_recall = rp["recall"] - ref_rp["recall"]
        d_fp = rp["faux_positifs_reference"] - ref_rp["faux_positifs_reference"]
        d_instab = instab - ref_instab

        # Filtre a tolerance ZERO, empirique (mesure sur F0 lui-meme) :
        # aucun nouveau faux positif, aucune degradation de stabilite.
        retenu = d_fp <= 0 and d_instab <= 0 and d_recall > 0

        resultats.append({
            "nom": nom, "params": params, "fn": fn, "recall": rp["recall"],
            "d_recall": d_recall, "fp": rp["faux_positifs_reference"], "d_fp": d_fp,
            "instab": instab, "d_instab": d_instab, "retenu": retenu,
        })
        print(f"{nom:<8}{str(params):<26}{rp['recall']:>9.1%}{d_recall:>+10.1%}"
              f"{rp['faux_positifs_reference']:>5}{d_fp:>+6}{instab:>9}{d_instab:>+10}"
              f"{'OUI' if retenu else '-':>9}")

    valides = [r for r in resultats if r["retenu"]]
    print("\n" + "=" * 100)
    print("SÉLECTION — parmi les points valides, celui qui maximise le rappel")
    print("=" * 100)
    if not valides:
        print("AUCUN point de grille ne passe le filtre (zéro nouveau FP, zéro dégradation "
              "de stabilité) tout en augmentant le rappel. Conclusion honnête : dans la plage "
              "balayée, aucune formulation testée ne bat F0 sans compromis. Pas de recalibrage "
              "à proposer sur cette base.")
        return

    meilleur = max(valides, key=lambda r: r["d_recall"])
    print(f"Retenu : {meilleur['nom']} {meilleur['params']} — "
          f"Δrappel={meilleur['d_recall']:+.1%}, ΔFP={meilleur['d_fp']}, "
          f"Δinstabilité={meilleur['d_instab']}\n")

    print("=" * 100)
    print("VALIDATION FINALE — captures 001-004, jamais vues avant ce script, une seule mesure")
    print("=" * 100)
    val_f0_rp = rappel_et_faux_positifs(F0, VALIDATION)
    val_f0_stab = [stabilite(F0, p, PERTURBATIONS) for p in VALIDATION]  # jeu COMPLET ici
    val_f0_instab = sum(s["instabilite"] for s in val_f0_stab)

    val_fn_rp = rappel_et_faux_positifs(meilleur["fn"], VALIDATION)
    val_fn_stab = [stabilite(meilleur["fn"], p, PERTURBATIONS) for p in VALIDATION]
    val_fn_instab = sum(s["instabilite"] for s in val_fn_stab)

    print(f"{'':<24}{'F0 (production)':>18}{meilleur['nom']:>18}{'Δ':>10}")
    print(f"{'Rappel':<24}{val_f0_rp['recall']:>17.1%} {val_fn_rp['recall']:>17.1%} "
          f"{val_fn_rp['recall'] - val_f0_rp['recall']:>+9.1%}")
    print(f"{'Faux positifs':<24}{val_f0_rp['faux_positifs_reference']:>18}"
          f"{val_fn_rp['faux_positifs_reference']:>18}"
          f"{val_fn_rp['faux_positifs_reference'] - val_f0_rp['faux_positifs_reference']:>+10}")
    print(f"{'Instabilité (15 pert.)':<24}{val_f0_instab:>18}{val_fn_instab:>18}"
          f"{val_fn_instab - val_f0_instab:>+10}")

    tient_en_validation = (
        val_fn_rp["faux_positifs_reference"] <= val_f0_rp["faux_positifs_reference"]
        and val_fn_instab <= val_f0_instab
        and val_fn_rp["recall"] > val_f0_rp["recall"]
    )
    print(f"\nLe candidat retenu en calibration tient-il sur la validation, "
          f"au MÊME critère strict ? {'OUI' if tient_en_validation else 'NON'}")


if __name__ == "__main__":
    main()
