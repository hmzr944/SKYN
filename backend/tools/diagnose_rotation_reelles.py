"""Meme diagnostic que `diagnose_rotation.py`, mais sur les VRAIES lesions de
`stability_bench.py`, pas des plants synthetiques.

────────────────────────────────────────────────────────────────────────
POURQUOI CE SECOND SCRIPT ETAIT NECESSAIRE.

Le premier essai, sur des lesions synthetiques plantees, a montre que les 8
survivent presque toutes a une rotation de 2° — un resultat qui CONTREDIT
`stability_bench.py` (6 lesions -> 3 sur l'image reelle). La raison de la
contradiction, verifiee : les lesions synthetiques de `plant()` portent un
signal FORT (exces mesure 9 a 14, contre un seuil ~3,1 — trois a quatre fois
au-dessus). Les lesions REELLES de la photo de reference sont plus proches du
seuil par nature (c'est pour ca qu'elles n'etaient detectees qu'avec une
confiance moderee des le depart). Un signal fort resiste trivialement a un
petit bruit de rotation ; un signal proche du seuil, non — et c'est
precisement la ou l'instabilite se joue. Tester la rotation sur des lesions
synthetiques fortes revient a tester la resistance d'un cable en tirant sur
sa partie la plus epaisse.

Ce script trace donc les vraies lesions rapportees par `analyze_face` sur
l'image de reference, aux memes coordonnees, a travers le meme pipeline.

Usage :
    python3 backend/tools/diagnose_rotation_reelles.py
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
    _classify,
    _local_excess,
    _robust_thr,
    _shape_stats,
    _zone_of,
)
from backend.skyn_engine.v2.pipeline import analyze_face  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
ANGLE = 2.0


def _b64(img: np.ndarray, quality: int = 100) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode()


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")

    ref = analyze_face(_b64(img))
    if not ref.ok:
        raise SystemExit("visage non detecte sur l'image de reference")

    bx, by, bw, bh = ref.face_box["x"], ref.face_box["y"], ref.face_box["w"], ref.face_box["h"]
    lesions_px = [
        (l["type"], l["confidence"], l["redness"], int(bx + l["x"] * bw), int(by + l["y"] * bh))
        for l in ref.lesions
    ]
    print(f"REFERENCE : {len(lesions_px)} vraies lesions\n")
    for t, conf, red, cx, cy in lesions_px:
        print(f"  {t:<12} conf={conf:.2f} red={red:>5.2f} pos=({cx},{cy})")

    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ANGLE, 1.0)
    tournee = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

    fm1 = build_face_map(_b64(tournee))
    if not fm1.detected:
        print("\nVisage non detecte sur l'image tournee — echec des l'etape reperes.")
        return

    face_w = max(1.0, float(fm1.bbox[2]))
    px_per_mm = face_w / 140.0
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    A1 = fm1.lab[:, :, 1] - 128.0
    L1 = fm1.l_flat
    B1 = fm1.lab[:, :, 2] - 128.0
    a_exc = _local_excess(A1, fm1.skin_mask, sigma_bg)
    l_exc = _local_excess(L1, fm1.skin_mask, sigma_bg)
    b_exc = _local_excess(B1, fm1.skin_mask, sigma_bg)
    hsv = cv2.cvtColor(fm1.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]

    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((fm1.skin_mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    thr_red = _robust_thr(a_exc[core_mask > 0], C.RED_BLOB_K)
    thr_dark = _robust_thr(-l_exc[core_mask > 0], C.DARK_BLOB_K)

    red_cands = _blob_candidates(a_exc, core_mask, C.RED_BLOB_K, a_min, a_max)
    dark_cands = _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K, a_min, a_max)
    red_pts = [(cx, cy, a) for cx, cy, a, _ in red_cands]
    dark_pts = [(cx, cy, a) for cx, cy, a, _ in dark_cands]

    print(f"\nseuils apres rotation : rouge={thr_red:.2f}  sombre={thr_dark:.2f}\n")
    seuil_app = 2.5 * r_min_px
    skin_s = float(S[fm1.skin_mask > 0].mean())

    print(f"{'type':<12} {'attendue':<14} {'peau':<7} {'zone_ok':<8} {'candidat':<9} "
          f"{'nouv.classe':<12} etape")
    for t, conf, red_orig, cx0, cy0 in lesions_px:
        p = M @ np.array([cx0, cy0, 1.0])
        cx, cy = int(round(p[0])), int(round(p[1]))
        h1, w1 = fm1.skin_mask.shape
        cx = max(0, min(w1 - 1, cx))
        cy = max(0, min(h1 - 1, cy))

        dans_skin = bool(fm1.skin_mask[cy, cx] > 0)
        zone_ok = dans_skin  # pas de "zone attendue" a comparer ici, juste presence
        red_ici = float(a_exc[cy, cx])
        dark_ici = float(-l_exc[cy, cx])

        proches = [(cx2, cy2, a) for cx2, cy2, a in red_pts if (cx2-cx)**2+(cy2-cy)**2 < seuil_app**2] + \
                  [(cx2, cy2, a) for cx2, cy2, a in dark_pts if (cx2-cx)**2+(cy2-cy)**2 < seuil_app**2]

        classe = "-"
        if not dans_skin:
            etape = "masque_peau"
        elif not proches:
            sous_seuil = red_ici < thr_red and dark_ici < thr_dark
            etape = (f"candidat (signal {red_ici:.2f}/{thr_red:.2f} rouge, "
                     f"{dark_ici:.2f}/{thr_dark:.2f} sombre — "
                     f"{'sous le seuil' if sous_seuil else 'forme rejetee'})")
        else:
            cx2, cy2, aire = proches[0]
            r_px = float(np.sqrt(max(aire, 1.0) / np.pi))
            rr = max(1, int(round(r_px)))
            y0, y1 = max(0, cy2-rr), min(h1, cy2+rr+1)
            x0, x1 = max(0, cx2-rr), min(w1, cx2+rr+1)
            patch_m = fm1.skin_mask[y0:y1, x0:x1] > 0
            if patch_m.sum() < 3:
                etape = "candidat (fenetre trop petite)"
            else:
                red = float(a_exc[y0:y1, x0:x1][patch_m].mean())
                dark = float(l_exc[y0:y1, x0:x1][patch_m].mean())
                yellow = float(b_exc[y0:y1, x0:x1][patch_m].mean())
                cr = max(1, int(r_px * 0.5))
                cy_0, cy_1 = max(0, cy2-cr), min(h1, cy2+cr+1)
                cx_0, cx_1 = max(0, cx2-cr), min(w1, cx2+cr+1)
                core_l = float(l_exc[cy_0:cy_1, cx_0:cx_1].mean())
                core_s = float(S[cy_0:cy_1, cx_0:cx_1].mean())
                src = "rouge" if any(p[0] == cx2 and p[1] == cy2 for p in red_pts) else "sombre"
                classe = _classify(red, dark, yellow, core_l, core_s, skin_s,
                                   r_px, px_per_mm, src) or "rejetee"
                etape = "detecte" if classe != "rejetee" else f"classification (red={red:.2f} dark={dark:.2f})"

        print(f"{t:<12} ({cx0},{cy0}){'':<3} {str(dans_skin):<7} {str(zone_ok):<8} "
              f"{str(bool(proches)):<9} {classe:<12} {etape}")


if __name__ == "__main__":
    run()
