"""P1 — Test de validation d'une garde de récupération, EXPÉRIMENTALE, en
PLUS de RED_IF_DARK — jamais à sa place. Suite directe de
classification_feature_exploration.py, qui a trouvé deux features hors
couleur fortement séparatrices dans la zone grise (dark≤-1.2, red≤4.5) :
contraste_centre_bord (d=3.07) et dispersion_signal (d=2.12).

REGLE STRICTE, inchangee : lesions.py et calibration.py ne sont pas
modifies. C'est un test de validation, pas une autorisation d'integration.

────────────────────────────────────────────────────────────────────────
POURQUOI PAS UN MONKEYPATCH DE _classify() CETTE FOIS.

Le benchmark RED/DARK precedent pouvait monkeypatcher _classify() parce
que sa nouvelle regle ne dependait que des arguments deja passes par
detect_lesions() (red, dark, d_mm). contraste_centre_bord et
dispersion_signal ont besoin des CARTES DE PIXELS autour du candidat
(a_exc, l_exc), que _classify() ne reçoit jamais — signature figee a 9
scalaires. Impossible de les lui glisser sans modifier lesions.py, ce
qu'on s'interdit.

A la place : le VRAI _classify() est appele normalement (via
_candidats(), deja verifie fidele dans les deux bancs precedents) pour
obtenir le verdict de production. La garde experimentale ne fait que
RECUPERER un sous-ensemble de candidats deja rejetes — jamais elle ne
change un verdict deja positif, jamais elle n'agit hors de la zone que
RED_IF_DARK gouverne. C'est une garantie STRUCTURELLE (voir `evaluer()`),
pas une promesse : verifiee explicitement (voir `verifier_perimetre()`).

────────────────────────────────────────────────────────────────────────
LES 4 VARIANTES DEMANDEES

  V1 = RED_IF_DARK + contraste_centre_bord seul
  V2 = RED_IF_DARK + dispersion_signal seul
  V3 = RED_IF_DARK + contraste_centre_bord ET dispersion_signal
  V4 = V3 + un plancher de rouge balaye (au lieu du plancher fixe 1.8)

Seuils balayes, ISSUS des moyennes/ecarts-types deja mesures dans
classification_feature_exploration.py (zone grise), jamais inventes :
  contraste_centre_bord : faux=0.62±0.65, vrais=3.53±1.16
    -> grille {1.3, 1.9, 2.5} (faux+1σ, milieu vrais/faux, faux+3σ environ)
  dispersion_signal      : faux=0.39±0.18, vrais=0.73±0.15
    -> grille {0.5, 0.6, 0.7} (memes principes)
  plancher rouge (V4)    : {1.8 (deja la valeur "peu sombre" en
    production), 2.2, 2.6}

PROTOCOLE — TRAIN/CALIBRATION/VALIDATION repris identique au benchmark
RED/DARK (memes fichiers, memes roles). Limite honnete supplementaire :
capture_001-004 ont deja servi de matiere DESCRIPTIVE (funnel audit,
exploration de features) mais jamais a choisir un seuil — elles restent
valables comme validation pour CETTE decision-ci, sans etre une coupure
parfaitement vierge au sens absolu.

CRITERE DE SELECTION — inchange : tolerance zero sur faux positifs et
stabilite (mesures contre F0 lui-meme), parmi les points valides on garde
celui qui maximise le rappel.

Usage :
    python3 backend/tools/classification_guard_bench.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools.synth_lesions import _landmarks, plant  # noqa: E402
from tools.stability_bench import PERTURBATIONS, _appareiller  # noqa: E402
from tools.red_dark_calibration_bench import PERTURBATIONS_BALAYAGE  # noqa: E402
from tools.cheek_candidate_diagnostic import (  # noqa: E402
    Champs, _candidats, _charger_oriente_bgr, _b64_from_bgr, build_face_map,
)
from tools.classification_feature_exploration import extra_features  # noqa: E402

SUBJECT = Path("/home/user/real_skin_pilot/subject_001")
TRAIN = [SUBJECT / "capture_006.jpg", SUBJECT / "capture_007.jpg"]
CALIBRATION = [SUBJECT / "capture_005.jpg", SUBJECT / "capture_008.jpg"]
VALIDATION = [SUBJECT / f"capture_{i}.jpg" for i in ("001", "002", "003", "004")]

ZONES_RECALL = ("joue_g", "joue_d", "machoire_g", "machoire_d", "menton", "front", "nez")
N_PAR_ZONE = 3
SEED = 17

GardeFn = Callable[[Dict[str, float]], bool]


def garde_toujours_fausse(feats: Dict[str, float]) -> bool:
    """F0 — aucune récupération, comportement de production inchangé."""
    return False


def _evaluer(bgr, garde_fn: GardeFn) -> List[dict]:
    """Rejoue le VRAI _classify() (via _candidats(), déjà vérifié fidèle),
    puis n'ajoute une lésion QUE pour un candidat que _classify() a rejeté
    ET qui se trouvait dans la zone gouvernée par RED_IF_DARK (dark≤-1.2,
    d_mm≥1.2 — les deux conditions déjà exigées par la branche papule
    "sombre"). Un candidat déjà accepté, ou rejeté hors de cette zone,
    n'est JAMAIS modifié — voir verifier_perimetre()."""
    fm = build_face_map(_b64_from_bgr(bgr, quality=100))
    if not fm.detected:
        return []
    champs = Champs(fm)
    cands = _candidats(champs)
    bx, by, bw, bh = fm.bbox
    out = []
    for c in cands:
        type_final = c.type
        if type_final is None and c.dark <= -1.2 and c.d_mm >= 1.2:
            feats = extra_features(c, champs)
            if garde_fn(feats):
                type_final = "papule"
        if type_final is not None:
            out.append({
                "x": (c.cx - bx) / max(1, bw),
                "y": (c.cy - by) / max(1, bh),
                "type": type_final,
                "zone": c.zone,
            })
    return out


def verifier_perimetre(garde_fn: GardeFn, photos: List[Path]) -> None:
    """Garantie structurelle : sur des photos DE RÉFÉRENCE (non marquées),
    toute lésion nouvelle sous la garde doit être un candidat qui était
    None sous F0 — jamais un TYPE CHANGÉ (ex. marque_rouge -> papule) ni
    une lésion apparue dans une zone où F0 n'avait déjà rien à dire."""
    for photo in photos:
        bgr = _charger_oriente_bgr(photo)
        fm = build_face_map(_b64_from_bgr(bgr, quality=100))
        if not fm.detected:
            continue
        champs = Champs(fm)
        cands = _candidats(champs)
        for c in cands:
            if c.type is not None:
                continue  # deja accepte par F0 : la garde ne doit meme pas etre evaluee ici
            feats = extra_features(c, champs)
            recuperee = garde_fn(feats)
            if recuperee and not (c.dark <= -1.2 and c.d_mm >= 1.2):
                raise AssertionError(
                    f"PÉRIMÈTRE VIOLÉ : candidat récupéré hors de la zone gouvernée "
                    f"par RED_IF_DARK (dark={c.dark:.2f}, d_mm={c.d_mm:.2f}) sur {photo.name}"
                )
    print("Périmètre vérifié : sur les photos de référence, aucune récupération "
          "n'a lieu hors de la zone RED_IF_DARK (dark≤-1.2, d_mm≥1.2).\n")


def rappel_et_fp(garde_fn: GardeFn, photos: List[Path]) -> Dict[str, float]:
    total_posees = total_gagnees = total_fp = 0
    for photo in photos:
        bgr = _charger_oriente_bgr(photo)
        ref = _evaluer(bgr, garde_fn)
        total_fp += len(ref)
        ref_zone = Counter(l["zone"] for l in ref)

        pts = _landmarks(bgr)
        if pts is None:
            continue
        for zone in ZONES_RECALL:
            try:
                marque, planted = plant(bgr, pts, zone, N_PAR_ZONE, seed=SEED)
            except SystemExit:
                continue
            rep = _evaluer(marque, garde_fn)
            by_zone = Counter(l["zone"] for l in rep)
            gagnees = max(0, by_zone[zone] - ref_zone[zone])
            total_posees += len(planted)
            total_gagnees += gagnees

    recall = total_gagnees / total_posees if total_posees else 0.0
    return {"recall": recall, "n_posees": total_posees, "n_gagnees": total_gagnees,
            "faux_positifs_reference": total_fp}


def stabilite(garde_fn: GardeFn, photo: Path, perturbations) -> Dict[str, float]:
    bgr = _charger_oriente_bgr(photo)
    base = _evaluer(bgr, garde_fn)
    total_perdues = total_type = total_zone = 0
    for p in perturbations:
        modifiee = p.applique(bgr)
        out = _evaluer(modifiee, garde_fn)
        appariees = _appareiller(base, out)
        total_perdues += sum(1 for _, n in appariees if n is None)
        total_type += sum(1 for r, n in appariees if n is not None and n["type"] != r["type"])
        total_zone += sum(1 for r, n in appariees if n is not None and n["zone"] != r["zone"])
    instabilite = total_perdues + total_type + total_zone
    return {"instabilite": instabilite}


# ─────────────────────────────────────────────────────────────────────────
C_GRID = [1.3, 1.9, 2.5]
D_GRID = [0.5, 0.6, 0.7]
R_GRID = [1.8, 2.2, 2.6]


def v1(seuil_c: float) -> GardeFn:
    return lambda f: f["red"] > 1.8 and f["contraste_centre_bord"] > seuil_c


def v2(seuil_d: float) -> GardeFn:
    return lambda f: f["red"] > 1.8 and f["dispersion_signal"] > seuil_d


def v3(seuil_c: float, seuil_d: float) -> GardeFn:
    return lambda f: (f["red"] > 1.8 and f["contraste_centre_bord"] > seuil_c
                       and f["dispersion_signal"] > seuil_d)


def v4(seuil_r: float) -> GardeFn:
    # c, d fixes au point milieu des grilles V1/V2 : V4 teste spécifiquement
    # l'effet d'un plancher de rouge plus exigeant, pas une nouvelle grille c/d.
    return lambda f: (f["red"] > seuil_r and f["contraste_centre_bord"] > 1.9
                       and f["dispersion_signal"] > 0.6)


def main() -> None:
    print("Vérification du périmètre (échantillon de seuils, sur CALIBRATION)")
    print("=" * 100)
    verifier_perimetre(v3(1.9, 0.6), CALIBRATION)

    print("=" * 100)
    print("RÉFÉRENCE F0 (aucune récupération) — mesurée sur CALIBRATION")
    print("=" * 100)
    ref_rp = rappel_et_fp(garde_toujours_fausse, CALIBRATION)
    ref_instab = sum(stabilite(garde_toujours_fausse, p, PERTURBATIONS_BALAYAGE)["instabilite"]
                      for p in CALIBRATION)
    print(f"Rappel F0        : {ref_rp['recall']:.1%}  ({ref_rp['n_gagnees']}/{ref_rp['n_posees']})")
    print(f"Faux positifs F0 : {ref_rp['faux_positifs_reference']}")
    print(f"Instabilité F0   : {ref_instab}\n")

    variantes = (
        [("V1_contraste", v1(c), (c,)) for c in C_GRID]
        + [("V2_dispersion", v2(d), (d,)) for d in D_GRID]
        + [("V3_les_deux", v3(c, d), (c, d)) for c in C_GRID for d in D_GRID]
        + [("V4_plancher_rouge", v4(r), (r,)) for r in R_GRID]
    )

    print("=" * 100)
    print(f"BALAYAGE — {len(variantes)} points, mesurés sur CALIBRATION")
    print("=" * 100)
    print(f"{'variante':<20}{'params':<16}{'rappel':>9}{'Δrappel':>10}{'FP':>5}"
          f"{'ΔFP':>6}{'instab.':>9}{'Δinstab.':>10}{'retenu':>9}")

    resultats = []
    for nom, fn, params in variantes:
        rp = rappel_et_fp(fn, CALIBRATION)
        instab = sum(stabilite(fn, p, PERTURBATIONS_BALAYAGE)["instabilite"] for p in CALIBRATION)
        d_recall = rp["recall"] - ref_rp["recall"]
        d_fp = rp["faux_positifs_reference"] - ref_rp["faux_positifs_reference"]
        d_instab = instab - ref_instab
        retenu = d_fp <= 0 and d_instab <= 0 and d_recall > 0
        resultats.append({"nom": nom, "params": params, "fn": fn, "recall": rp["recall"],
                          "d_recall": d_recall, "fp": rp["faux_positifs_reference"], "d_fp": d_fp,
                          "instab": instab, "d_instab": d_instab, "retenu": retenu})
        print(f"{nom:<20}{str(params):<16}{rp['recall']:>9.1%}{d_recall:>+10.1%}"
              f"{rp['faux_positifs_reference']:>5}{d_fp:>+6}{instab:>9}{d_instab:>+10}"
              f"{'OUI' if retenu else '-':>9}")

    valides = [r for r in resultats if r["retenu"]]
    print("\n" + "=" * 100)
    print("SÉLECTION")
    print("=" * 100)
    if not valides:
        print("AUCUNE variante ne passe le filtre (zéro nouveau FP, zéro dégradation de "
              "stabilité) en augmentant le rappel. Conclusion honnête : contraste_centre_bord "
              "et dispersion_signal séparent bien EN THÉORIE (voir le d de Cohen), mais "
              "utilisées comme garde de récupération sur ce jeu de photos, elles ne passent "
              "pas le même test que RED_IF_DARK n'avait pas passé non plus. La branche "
              "classification se referme sur cette base — pas d'intégration à proposer.")
        return

    meilleur = max(valides, key=lambda r: r["d_recall"])
    print(f"Retenu : {meilleur['nom']} {meilleur['params']} — "
          f"Δrappel={meilleur['d_recall']:+.1%}, ΔFP={meilleur['d_fp']}, "
          f"Δinstabilité={meilleur['d_instab']}\n")

    print("=" * 100)
    print("VALIDATION FINALE — captures 001-004, une seule mesure")
    print("=" * 100)
    val_f0_rp = rappel_et_fp(garde_toujours_fausse, VALIDATION)
    val_f0_instab = sum(stabilite(garde_toujours_fausse, p, PERTURBATIONS)["instabilite"]
                         for p in VALIDATION)
    val_fn_rp = rappel_et_fp(meilleur["fn"], VALIDATION)
    val_fn_instab = sum(stabilite(meilleur["fn"], p, PERTURBATIONS)["instabilite"] for p in VALIDATION)

    print(f"{'':<24}{'F0 (production)':>18}{meilleur['nom']:>18}{'Δ':>10}")
    print(f"{'Rappel':<24}{val_f0_rp['recall']:>17.1%} {val_fn_rp['recall']:>17.1%} "
          f"{val_fn_rp['recall'] - val_f0_rp['recall']:>+9.1%}")
    print(f"{'Faux positifs':<24}{val_f0_rp['faux_positifs_reference']:>18}"
          f"{val_fn_rp['faux_positifs_reference']:>18}"
          f"{val_fn_rp['faux_positifs_reference'] - val_f0_rp['faux_positifs_reference']:>+10}")
    print(f"{'Instabilité (15 pert.)':<24}{val_f0_instab:>18}{val_fn_instab:>18}"
          f"{val_fn_instab - val_f0_instab:>+10}")

    tient = (val_fn_rp["faux_positifs_reference"] <= val_f0_rp["faux_positifs_reference"]
             and val_fn_instab <= val_f0_instab
             and val_fn_rp["recall"] > val_f0_rp["recall"])
    print(f"\nLe candidat retenu tient-il sur la validation, au même critère strict ? "
          f"{'OUI' if tient else 'NON'}")

    print("\nVérification du périmètre sur la validation aussi :")
    verifier_perimetre(meilleur["fn"], VALIDATION)


if __name__ == "__main__":
    main()
