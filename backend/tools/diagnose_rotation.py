"""Diagnostic dedie : a quelle etape une rotation de 2 degres fait-elle
disparaitre une lesion ?

────────────────────────────────────────────────────────────────────────
CE QUE CE SCRIPT FAIT, ET NE FAIT PAS.

`stability_bench.py` a mesure l'effet global (6 lesions -> 3 sous 2 degres)
sans dire OU, dans le pipeline, chacune se perd. Ce script trace des lesions
plantees a une position CONNUE a travers chaque etape :

    reperes -> masque peau -> zone -> candidat -> filtre de forme -> classification

et rapporte, pour chacune, la premiere etape ou elle disparait. Aucune
correction n'est tentee ici — c'est un diagnostic, pas un chantier de
correctif, exactement la demande.

Methode : une lesion plantee a une position (cx, cy) connue survit a une
rotation d'angle `a` a la position `M @ (cx, cy)`, ou `M` est la MEME
matrice de rotation que celle appliquee a l'image entiere. On suit cette
position attendue a travers le pipeline plutot que d'esperer apparier une
detection a une position a posteriori — la position est un fait geometrique,
pas une mesure.

Usage :
    python3 backend/tools/diagnose_rotation.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    _blob_candidates,
    _classify,
    _local_excess,
    _zone_of,
)
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
ANGLE = 2.0
SEED = 5


def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode()


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    pts0 = _landmarks(img)
    if pts0 is None:
        raise SystemExit("aucun visage detecte sur l'image de base")

    marque = img.copy()
    lesions: List[Tuple[str, int, int]] = []
    for zone in ("joue_g", "joue_d", "front", "menton"):
        marque, planted = plant(marque, pts0, zone, 2, seed=SEED)
        lesions.extend((zone, p.x, p.y) for p in planted)

    h, w = marque.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ANGLE, 1.0)
    tournee = cv2.warpAffine(marque, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

    # Position ATTENDUE de chaque lesion apres rotation — un fait geometrique,
    # calcule avec la MEME matrice que celle appliquee a l'image, pas mesure.
    attendues = []
    for zone, cx, cy in lesions:
        p = M @ np.array([cx, cy, 1.0])
        attendues.append((zone, int(round(p[0])), int(round(p[1]))))

    print(f"ANGLE = {ANGLE}°\n")

    # ── Etape 1 : les REPERES survivent-ils, et ou tombent-ils reellement ? ──
    pts1 = _landmarks(tournee)
    if pts1 is None:
        print("ETAPE 1 (reperes) : ECHEC TOTAL — MediaPipe ne detecte plus de "
              "visage sous 2° de rotation. Tout le reste est sans objet.")
        return

    # Reperes attendus (rotation geometrique pure des reperes d'origine) vs
    # reperes REELLEMENT rendus par MediaPipe sur l'image tournee : l'ecart
    # entre les deux est la part de derive qui n'est PAS de la rotation elle-
    # meme, mais une imprecision de re-detection.
    pts0_h = np.hstack([pts0, np.ones((len(pts0), 1))])
    pts0_tournes_geometriquement = (M @ pts0_h.T).T
    derive = np.linalg.norm(pts1 - pts0_tournes_geometriquement, axis=1)
    print(f"ETAPE 1 (reperes) : derive de re-detection (hors rotation pure) — "
          f"max={derive.max():.2f}px  p95={np.percentile(derive, 95):.2f}px  "
          f"moyenne={derive.mean():.2f}px\n")

    fm0 = build_face_map(_b64(marque, quality=100))
    fm1 = build_face_map(_b64(tournee, quality=100))
    if not fm1.detected:
        print("ETAPE 2 (masque peau) : ECHEC — build_face_map ne detecte plus "
              "de visage sur l'image tournee.")
        return

    face_w = max(1.0, float(fm1.bbox[2]))
    px_per_mm = face_w / 140.0
    sigma_bg = max(4.0, 5.0 * px_per_mm)

    A1 = fm1.lab[:, :, 1] - 128.0
    L1 = fm1.l_flat
    a_exc = _local_excess(A1, fm1.skin_mask, sigma_bg)
    l_exc = _local_excess(L1, fm1.skin_mask, sigma_bg)

    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((fm1.skin_mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    red_cands = _blob_candidates(a_exc, core_mask, C.RED_BLOB_K, a_min, a_max)
    dark_cands = _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K, a_min, a_max)
    # L'aire est conservee : `detect_lesions()` en tire le rayon REEL du
    # candidat (`r_px = sqrt(aire/pi)`) pour sa fenetre de mesure ET pour le
    # controle de taille de `_classify`. Un rayon fixe ici serait un ecart au
    # pipeline reel, pas une reproduction fidele de ce qu'il voit.
    red_pts = [(cx, cy, a) for cx, cy, a, _ in red_cands]
    dark_pts = [(cx, cy, a) for cx, cy, a, _ in dark_cands]

    seuil_app = 2.5 * r_min_px

    print(f"{'zone':<10} {'pos. attendue':<16} {'masque peau':<12} "
          f"{'meme zone':<10} {'candidat':<9} {'classe':<12} etape de disparition")
    for (zone, cx0, cy0), (_, cx, cy) in zip(lesions, attendues):
        h1, w1 = fm1.skin_mask.shape
        cx = max(0, min(w1 - 1, cx))
        cy = max(0, min(h1 - 1, cy))

        dans_skin = bool(fm1.skin_mask[cy, cx] > 0)
        zone_reelle = _zone_of(fm1, cx, cy) if dans_skin else "-"
        meme_zone = zone_reelle == zone

        proches_red = [pt for pt in red_pts if (pt[0]-cx)**2+(pt[1]-cy)**2 < seuil_app**2]
        proches_dark = [pt for pt in dark_pts if (pt[0]-cx)**2+(pt[1]-cy)**2 < seuil_app**2]
        a_candidat = bool(proches_red or proches_dark)

        classe = "-"
        etape = "?"
        if not dans_skin:
            etape = "masque_peau (hors skin_mask apres rotation)"
        elif not meme_zone:
            etape = f"zone (rendue en {zone_reelle}, pas {zone})"
        elif not a_candidat:
            etape = "candidat (aucun blob au-dessus du seuil pres du point)"
        else:
            cx2, cy2, aire = (proches_red or proches_dark)[0]
            # Rayon REEL du candidat, pas une constante — sinon `_classify`
            # recoit un `d_mm` artificiellement petit et rejette pour une
            # raison qui n'existe pas dans le vrai pipeline.
            r_px = float(np.sqrt(max(aire, 1.0) / np.pi))
            rr = max(1, int(round(r_px)))
            y0, y1 = max(0, cy2-rr), min(h1, cy2+rr+1)
            x0, x1 = max(0, cx2-rr), min(w1, cx2+rr+1)
            patch_m = fm1.skin_mask[y0:y1, x0:x1] > 0
            if patch_m.sum() < 3:
                etape = "candidat (fenetre de mesure trop petite)"
            else:
                red = float(a_exc[y0:y1, x0:x1][patch_m].mean())
                dark = float(l_exc[y0:y1, x0:x1][patch_m].mean())
                hsv = cv2.cvtColor(fm1.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
                S = hsv[:, :, 1]
                B1 = fm1.lab[:, :, 2] - 128.0
                b_exc_local = _local_excess(B1, fm1.skin_mask, sigma_bg)
                yellow = float(b_exc_local[y0:y1, x0:x1][patch_m].mean())
                skin_s = float(S[fm1.skin_mask > 0].mean())
                cr = max(1, int(r_px * 0.5))
                cy0, cy1 = max(0, cy2-cr), min(h1, cy2+cr+1)
                cx0, cx1 = max(0, cx2-cr), min(w1, cx2+cr+1)
                core_l = float(l_exc[cy0:cy1, cx0:cx1].mean())
                core_s = float(S[cy0:cy1, cx0:cx1].mean())
                src = "rouge" if any(p[0] == cx2 and p[1] == cy2 for p in red_pts) else "sombre"
                classe = _classify(red, dark, yellow, core_l, core_s, skin_s,
                                   r_px, px_per_mm, src) or "rejetee"
                etape = "detecte" if classe != "rejetee" else "classification (candidat rejete)"

        print(f"{zone:<10} ({cx},{cy}){'':<6} {str(dans_skin):<12} "
              f"{str(meme_zone):<10} {str(a_candidat):<9} {classe:<12} {etape}")


if __name__ == "__main__":
    run()
