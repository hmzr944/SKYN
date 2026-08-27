"""Diagnostic dedie : d'ou viennent les candidats qui naissent sous +15 % de
contraste, et qu'est-ce qui bouge reellement — le signal, ou le seuil ?

────────────────────────────────────────────────────────────────────────
LA QUESTION EXACTE POSEE.

`feature_lab.py` a montre que l'exces absolu (A) EST separable (d=3,90) et
QUE SA DERIVE MOYENNE reste petite (3,3 % de l'ecart lesion/peau). Mais
l'experience de contraste, elle, a mesure une explosion du COMPTE de
candidats (6 -> 14). Ces deux mesures ne se contredisent pas : une derive
moyenne faible sur l'ensemble de la peau peut coexister avec un basculement
franc pour la poignee de points qui se trouvaient deja pres du seuil — et le
seuil lui-meme (`_robust_thr`, une mediane + un multiple de MAD, calcule sur
TOUTE la peau) peut aussi avoir bouge, puisqu'il depend de la meme
distribution que le contraste vient d'etirer.

Ce script isole precisement la cause, candidat NOUVEAU par candidat NOUVEAU :
    - la peau saine a cet endroit avait-elle deja un signal notable a la
      reference, juste sous le seuil (le signal a grandi) ?
    - ou le seuil lui-meme est-il descendu, capturant un signal qui n'a
      quasiment pas bouge (le seuil a bouge) ?

Rien n'est modifie en production. C'est un diagnostic, pas un correctif.

Usage :
    python3 backend/tools/diagnose_naissance_candidats.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    _blob_candidates,
    _local_excess,
    _robust_thr,
)
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
FACTEUR_CONTRASTE = 1.15
APPARIEMENT = 10  # px : un candidat "existait deja" s'il y en a un a cette distance


def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode()


def _contraste(img: np.ndarray, facteur: float) -> np.ndarray:
    moy = img.astype(np.float32).mean()
    return np.clip((img.astype(np.float32) - moy) * facteur + moy, 0, 255).astype(np.uint8)


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")

    fm0 = build_face_map(_b64(img, quality=100))
    etire = _contraste(img, FACTEUR_CONTRASTE)
    fm1 = build_face_map(_b64(etire, quality=95))
    if not fm0.detected or not fm1.detected:
        raise SystemExit("visage non detecte")

    face_w = max(1.0, float(fm0.bbox[2]))
    px_per_mm = face_w / 140.0
    sigma_bg = max(4.0, 5.0 * px_per_mm)

    def _prepare(fm):
        A = fm.lab[:, :, 1] - 128.0
        a_exc = _local_excess(A, fm.skin_mask, sigma_bg)
        margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
        dist = cv2.distanceTransform((fm.skin_mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
        core_mask = ((dist > margin_px) * 255).astype(np.uint8)
        return a_exc, core_mask

    a_exc0, core0 = _prepare(fm0)
    a_exc1, core1 = _prepare(fm1)

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    thr0 = _robust_thr(a_exc0[core0 > 0], C.RED_BLOB_K)
    thr1 = _robust_thr(a_exc1[core1 > 0], C.RED_BLOB_K)
    print(f"seuil rouge  avant={thr0:.3f}   apres_contraste={thr1:.3f}   "
          f"variation du seuil = {100*(thr1-thr0)/thr0:+.1f} %\n")

    cands0 = _blob_candidates(a_exc0, core0, C.RED_BLOB_K, a_min, a_max)
    cands1 = _blob_candidates(a_exc1, core1, C.RED_BLOB_K, a_min, a_max)
    pts0 = [(cx, cy) for cx, cy, _, _ in cands0]

    nouveaux = [(cx, cy, a) for cx, cy, a, _ in cands1
                if not any((cx-x0)**2+(cy-y0)**2 < APPARIEMENT**2 for x0, y0 in pts0)]

    print(f"candidats avant : {len(cands0)}   apres : {len(cands1)}   "
          f"NOUVEAUX (sans correspondance avant) : {len(nouveaux)}\n")

    print(f"{'position':<14} {'signal avant':>13} {'signal apres':>13} "
          f"{'vs seuil avant':>15} {'vs seuil apres':>15}  origine")
    for cx, cy, aire in nouveaux:
        val0 = float(a_exc0[cy, cx])  # meme pixel, sur l'image NON etiree
        val1 = float(a_exc1[cy, cx])

        # Part attribuable a la seule croissance du signal vs part
        # attribuable a la seule baisse du seuil, en tenant tout le reste
        # fixe : deux scenarios contrefactuels, pas une mesure directe.
        franchirait_avec_seuil_dorigine = val1 > thr0
        franchirait_avec_signal_dorigine = val0 > thr1

        if franchirait_avec_seuil_dorigine and not franchirait_avec_signal_dorigine:
            origine = "signal a grandi (aurait franchi meme le seuil d'origine)"
        elif franchirait_avec_signal_dorigine and not franchirait_avec_seuil_dorigine:
            origine = "seuil a baisse (le signal d'origine suffisait deja face au nouveau seuil)"
        elif franchirait_avec_seuil_dorigine and franchirait_avec_signal_dorigine:
            origine = "les deux contribuent"
        else:
            origine = "ni l'un ni l'autre seul (effet combine requis)"

        print(f"({cx},{cy}){'':<6} {val0:>13.2f} {val1:>13.2f} "
              f"{'PASSE' if val0>thr0 else 'rate' :>15} "
              f"{'PASSE' if val1>thr1 else 'rate':>15}  {origine}")


if __name__ == "__main__":
    run()
