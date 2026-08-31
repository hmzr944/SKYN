"""Audit complet du moteur — pas seulement les boutons de joue.

Chantier demandé après la conclusion du benchmark de calibration RED/DARK
(0/22 configurations retenues) : avant de rouvrir tout autre axe de
classification, savoir OÙ, dans tout le pipeline, un vrai bouton posé à un
endroit connu finit par disparaître.

REGLE STRICTE, inchangee depuis le debut de ce fil : ni lesions.py ni
calibration.py ne sont modifies. Ce script observe le pipeline reel
(build_face_map -> zones -> candidats -> classify -> analyze_face), rien
n'est reimplemente sauf ce qui doit rester observable a une etape que le
rapport final ne montre pas (candidats rejetes).

METHODE — le seul instrument qui donne une verite terrain fiable a chaque
etage est la lesion SYNTHETIQUE plantee a une position connue
(backend/tools/synth_lesions.py, deja valide). Pour chacune, on trace :

  1. Detection visage    — le visage est-il detecte du tout (global/photo) ?
  2. Zone disponible     — la zone visee existe-t-elle dans fm.zones ?
  3. Masque de peau      — le pixel plante est-il DANS skin_mask ?
  4. Attribution de zone — _zone_of() retrouve-t-il la BONNE zone ?
  5. Candidat genere     — _blob_candidates() propose-t-il quelque chose
                            pres de cette position ?
  6. Classification      — _classify() accepte-t-il ce candidat ?
  7. Rapporte au final   — analyze_face() le liste-t-il vraiment ?

Chaque lesion est imputee a la PREMIERE etape ou elle echoue — c'est la
"perte" de cette lesion. Le tableau final donne, par etape, combien de
lesions parmi celles qui ont survecu jusque-la sont perdues a CETTE etape
precisement (pas cumule).

HORS PERIMETRE, deliberement : tracking/fusion multi-vue (deja audites
separement cette session — lesion_tracking_audit.py, vote_gate_bench.py,
track_purity_gate_bench.py, track_clean_purity_bench.py — chacun avec sa
propre mesure BASELINE/NEW/DELTA deja validee, pas repris ici pour eviter
un doublon). Ce script couvre le pipeline MONO-VUE (analyze_face), qui
n'avait justement jamais eu cet audit de bout en bout sur de vraies photos.

Usage :
    python3 backend/tools/engine_loss_funnel_audit.py
"""
from __future__ import annotations

import base64
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from skyn_engine.v2.zones import build_face_map, ZONE_LANDMARKS  # noqa: E402
from skyn_engine.v2.pipeline import analyze_face  # noqa: E402
from tools.synth_lesions import _landmarks, plant  # noqa: E402
from tools.cheek_candidate_diagnostic import (  # noqa: E402
    Champs, _candidats, _charger_oriente_bgr, _b64_from_bgr,
)

SUBJECT = Path("/home/user/real_skin_pilot/subject_001")
PHOTOS = [SUBJECT / f"capture_{i}.jpg" for i in
          ("001", "002", "003", "004", "005", "006", "007", "008")]
ZONES = list(ZONE_LANDMARKS.keys())
N_PAR_ZONE = 2
SEED = 23

STAGES = ["detection_visage", "zone_disponible", "masque_peau",
          "attribution_zone", "candidat_genere", "classification", "confirme"]


def _premiere_etape_ratee(
    photo_detectee: bool,
    zone_dispo: bool,
    dans_peau: bool,
    zone_correcte: bool,
    candidat_proche,
    rapportee: bool,
) -> str:
    if not photo_detectee:
        return "detection_visage"
    if not zone_dispo:
        return "zone_disponible"
    if not dans_peau:
        return "masque_peau"
    if not zone_correcte:
        return "attribution_zone"
    if candidat_proche is None:
        return "candidat_genere"
    if candidat_proche.type is None:
        return "classification"
    if not rapportee:
        # Cas residuel : candidat classifie mais absent du rapport final
        # (dedup ou filtre en aval du classify) — compte a part, ca ne
        # devrait normalement jamais arriver si Candidat est fidele.
        return "classification"
    return "confirme"


def _cherche_candidat_proche(cands, cx: int, cy: int, rayon_px: float):
    meilleur, meilleure_dist = None, rayon_px
    for c in cands:
        d = ((c.cx - cx) ** 2 + (c.cy - cy) ** 2) ** 0.5
        if d < meilleure_dist:
            meilleur, meilleure_dist = c, d
    return meilleur


def _rapportee_pres_de(rapport_lesions: List[dict], cx: int, cy: int, bbox, rayon_norm: float) -> bool:
    bx, by, bw, bh = bbox
    for l in rapport_lesions:
        lx, ly = bx + l["x"] * bw, by + l["y"] * bh
        d = ((lx - cx) ** 2 + (ly - cy) ** 2) ** 0.5 / max(1, max(bw, bh))
        if d < rayon_norm:
            return True
    return False


def auditer_photo(chemin: Path, pertes: Dict[str, Counter], par_zone: Dict[str, Counter]) -> Optional[dict]:
    bgr = _charger_oriente_bgr(chemin)
    fm_ref = build_face_map(_b64_from_bgr(bgr))
    if not fm_ref.detected:
        return {"photo": chemin.name, "detectee": False}

    pts = _landmarks(bgr)
    if pts is None:
        return {"photo": chemin.name, "detectee": True, "landmarks": False}

    n_par_etape = Counter()
    n_total = 0

    for zone in ZONES:
        try:
            marque, planted = plant(bgr, pts, zone, N_PAR_ZONE, seed=SEED)
        except SystemExit:
            continue

        fm = build_face_map(_b64_from_bgr(marque, quality=100))
        photo_detectee = fm.detected
        rapport = analyze_face(_b64_from_bgr(marque, quality=100))
        rapport_lesions = rapport.lesions if rapport.ok else []

        if photo_detectee:
            champs = Champs(fm)
            cands = _candidats(champs)
            z = fm.zones.get(zone)
            zone_dispo = z is not None and z.available
        else:
            cands = []
            zone_dispo = False

        for p in planted:
            n_total += 1
            dans_peau = photo_detectee and zone_dispo and fm.skin_mask[p.y, p.x] > 0
            zone_correcte = dans_peau and z is not None and z.mask[p.y, p.x] > 0
            proche = None
            rapportee = False
            if zone_correcte:
                rayon_recherche = max(6.0, p.radius * 2.5)
                proche = _cherche_candidat_proche(cands, p.x, p.y, rayon_recherche)
                if proche is not None and proche.type is not None:
                    rapportee = _rapportee_pres_de(
                        rapport_lesions, p.x, p.y, fm.bbox, rayon_norm=0.04
                    )
            etape = _premiere_etape_ratee(
                photo_detectee, zone_dispo, dans_peau, zone_correcte, proche, rapportee
            )

            n_par_etape[etape] += 1
            pertes[zone][etape] += 1
            par_zone[etape][zone] += 1

    return {"photo": chemin.name, "detectee": True, "landmarks": True,
            "n_total": n_total, "par_etape": n_par_etape}


def audit_landmarks_instabilite() -> None:
    """Reprend le fait deja documente dans synth_lesions.py (re-encodage
    seul deplace les reperes) et le mesure sur les 8 vraies photos, pas
    seulement le fixture — pour savoir si c'est un phenomene marginal ou
    significatif dans l'absolu."""
    print("\n" + "=" * 100)
    print("LANDMARKS — dérive des centres de zone sous simple recompression JPEG (95→85)")
    print("=" * 100)
    derives = []
    for photo in PHOTOS:
        bgr = _charger_oriente_bgr(photo)
        fm_a = build_face_map(_b64_from_bgr(bgr, quality=95))
        fm_b = build_face_map(_b64_from_bgr(bgr, quality=85))
        if not (fm_a.detected and fm_b.detected):
            continue
        face_w = max(1.0, float(fm_a.bbox[2]))
        px_per_mm = face_w / 140.0
        for zname, za in fm_a.zones.items():
            zb = fm_b.zones.get(zname)
            if not (za.available and zb and zb.available):
                continue
            ys_a, xs_a = np.nonzero(za.mask)
            ys_b, xs_b = np.nonzero(zb.mask)
            if len(xs_a) == 0 or len(xs_b) == 0:
                continue
            ca = (float(xs_a.mean()), float(ys_a.mean()))
            cb = (float(xs_b.mean()), float(ys_b.mean()))
            d_px = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
            derives.append(d_px / px_per_mm)
    if derives:
        arr = np.array(derives)
        print(f"Dérive du centroïde de zone, en mm, sur {len(arr)} mesures "
              f"({len(PHOTOS)} photos × 13 zones) :")
        print(f"  moyenne={arr.mean():.2f}mm  p95={np.percentile(arr, 95):.2f}mm  max={arr.max():.2f}mm")
    else:
        print("(aucune mesure exploitable)")


def main() -> None:
    pertes: Dict[str, Counter] = defaultdict(Counter)
    par_zone: Dict[str, Counter] = defaultdict(Counter)
    resultats = []

    print("Plantation + traçage de la perte, 13 zones × 2 lésions × 8 photos "
          f"= jusqu'à {13 * N_PAR_ZONE * len(PHOTOS)} lésions synthétiques tracées.\n")

    for photo in PHOTOS:
        r = auditer_photo(photo, pertes, par_zone)
        resultats.append(r)
        if r.get("detectee") and r.get("landmarks"):
            print(f"{r['photo']:<18} {r['n_total']} lésions plantées — "
                  + ", ".join(f"{k}={v}" for k, v in r["par_etape"].items()))
        else:
            print(f"{r['photo']:<18} ignorée ({r})")

    total_par_etape: Counter = Counter()
    for c in pertes.values():
        total_par_etape.update(c)
    n_total = sum(total_par_etape.values())

    print("\n" + "=" * 100)
    print("ENTONNOIR GLOBAL — perte à CHAQUE étape (pas cumulé), sur toutes zones/photos")
    print("=" * 100)
    print(f"{'Étape':<20}{'Perdues ici':>14}{'% du total':>13}{'Gravité':>10}")
    survivantes = n_total
    for etape in STAGES[:-1]:
        n = total_par_etape.get(etape, 0)
        pct = 100 * n / n_total if n_total else 0.0
        gravite = "🔴" if pct >= 20 else ("🟡" if pct >= 5 else "🟢")
        print(f"{etape:<20}{n:>14}{pct:>12.1f}%{gravite:>10}")
    confirmees = total_par_etape.get("confirme", 0)
    print(f"{'confirmé (survit)':<20}{confirmees:>14}{100*confirmees/n_total if n_total else 0:>12.1f}%")
    print(f"\nTotal lésions plantées : {n_total}  —  confirmées au final : {confirmees} "
          f"({100*confirmees/n_total:.1f}% de rappel global, toutes zones confondues)")

    print("\n" + "=" * 100)
    print("PAR ZONE — où la perte se concentre-t-elle ?")
    print("=" * 100)
    print(f"{'zone':<14}" + "".join(f"{s:>16}" for s in STAGES))
    for zone in ZONES:
        c = pertes[zone]
        print(f"{zone:<14}" + "".join(f"{c.get(s,0):>16}" for s in STAGES))

    audit_landmarks_instabilite()


if __name__ == "__main__":
    main()
