"""Verification statistique : FIXE-9 est-il vraiment le pire des quatre sur
synthetique, ou est-ce du bruit d'echantillonnage a R=6 ?

────────────────────────────────────────────────────────────────────────
AUCUN CHANGEMENT D'ALGORITHME. Reutilise EXACTEMENT les memes fonctions de
`capture_protocol_v0_bench.py` (`_sessions_pour`, `_reproductibilite`,
`VARIANTES`, le meme `PLAFOND_TENTATIVES`, les memes seuils de nettoyage/
purete/vote-gate deja valides) — seule R_SESSIONS augmente. Si le
comportement de FIXE-9 (pire des quatre sur recall/faux-evt/persistance/
%transitoire a R=6) est du bruit, il doit se rapprocher de FIXE-3/7 a plus
grand R. S'il reste systematiquement le pire, c'est un vrai signal sur ce
terrain synthetique specifiquement, pas un artefact d'echantillon.

Rien modifie en production.

Usage :
    python3 backend/tools/capture_protocol_v0_synth_verification.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.capture_protocol_v0_bench import (  # noqa: E402
    IMAGE_SYNTH,
    RAYON_REGROUPEMENT_INTER_SESSION,
    VARIANTES,
    _reproductibilite,
    _sessions_pour,
)
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN  # noqa: E402
from backend.tools.multiview_persistence_bench import (  # noqa: E402
    LESIONS_PAR_ZONE,
    SEED_PLANT,
    ZONES_PLANTEES,
)
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

R_SESSIONS_VERIFICATION = 16  # 6 -> 16, meme experience, plus de sessions


def run() -> None:
    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

    img = cv2.imread(str(IMAGE_SYNTH))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE_SYNTH}")
    pts0 = _landmarks(img)
    marque = img.copy()
    plantees = []
    for zone in ZONES_PLANTEES:
        marque, p = plant(marque, pts0, zone, LESIONS_PAR_ZONE, seed=SEED_PLANT)
        plantees.extend(p)
    base = build_face_map(_b64(marque, quality=100))
    x0, y0, bw, bh = base.bbox
    verite_xy = [((p.x - x0) / bw, (p.y - y0) / bh) for p in plantees]

    print(f"R_SESSIONS = {R_SESSIONS_VERIFICATION} (contre 6 dans le banc precedent), "
          f"meme algorithme, memes seuils.\n")
    print(f"{'variante':<30} {'recall':>7} {'precision':>10} {'doublons':>9} {'faux-evt':>9} "
          f"{'persist.':>9} {'%stable':>8} {'%transit':>9} {'vues util.moy':>14}")
    for i_variante, (nom, config) in enumerate(VARIANTES):
        resultats = _sessions_pour(marque, config, seed_base_par_n=9000 + 100 * i_variante,
                                   r_sessions=R_SESSIONS_VERIFICATION)
        sessions_confirmees = [r.lesions_confirmees for r in resultats]

        recalls, precisions, doublons_l = [], [], []
        for confirmees in sessions_confirmees:
            tp, fn, fp, r, prec, d = _evaluer(confirmees, verite_xy, RAYON_MATCH_ANCIEN)
            recalls.append(r); precisions.append(prec); doublons_l.append(d)
        faux_evt = [_fausse_evolution(sessions_confirmees[i], sessions_confirmees[i+1], RAYON_MATCH_ANCIEN)
                   for i in range(R_SESSIONS_VERIFICATION - 1)]
        repro = _reproductibilite(sessions_confirmees, RAYON_REGROUPEMENT_INTER_SESSION)
        vues_util = [r.n_vues_utilisables for r in resultats]
        print(f"{nom:<30} {moy(recalls):>7.2f} {moy(precisions):>10.2f} {moy(doublons_l):>9.2f} "
              f"{moy(faux_evt):>9.2f} {repro['persistance_moyenne']:>9.2f} "
              f"{repro['part_stable']:>8.1%} {repro['part_transitoire']:>9.1%} {moy(vues_util):>14.1f}")

    print("\nRien modifie en production.")


if __name__ == "__main__":
    run()
