"""Diagnostic P0 : pourquoi chaque lesion manquee disparait, et a quelle etape.

Ce script ne modifie AUCUN seuil ni AUCUNE regle du moteur. Il reutilise les
memes fonctions internes que `lesions.detect_lesions()` — `_local_excess`,
`_blob_candidates`, `_robust_thr`, `_classify` — pour rejouer exactement le
meme calcul, mais en gardant la trace de ce qui se passe A CHAQUE LESION
POSEE individuellement, ce que le rapport final (qui ne renvoie que des
comptes agreges par zone) ne permet pas de voir.

Reproduit la configuration exacte du banc de reference : zones
joue_g,joue_d,front,menton,nez, 6 lesions par zone, seed 7 -> 30 lesions,
19 retrouvees, 63 %.

Usage :
    python3 backend/tools/diagnose_lesions.py
"""
from __future__ import annotations

import base64
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    RED_IF_DARK,
    _blob_candidates,
    _classify,
    _local_excess,
    _robust_thr,
    _zone_of,
)
from backend.skyn_engine.v2.pipeline import analyze_face  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.synth_lesions import plant, _landmarks, _b64  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
ZONES = ["joue_g", "joue_d", "front", "menton", "nez"]
N_PAR_ZONE = 6
SEED = 7
# Un candidat rapporte est apparie a une lesion posee s'il tombe a moins de
# cette distance (en rayons de la lesion posee) de son centre.
APPARIEMENT_RAYONS = 2.2


def diagnostiquer_zone(img: np.ndarray, pts: np.ndarray, zone: str) -> list[dict]:
    marked, planted = plant(img, pts, zone, N_PAR_ZONE, seed=SEED)
    fm = build_face_map(_b64(marked))

    # --- Rejoue exactement ce que detect_lesions() calcule -----------------
    lab = fm.lab
    A = lab[:, :, 1] - 128.0
    B = lab[:, :, 2] - 128.0
    L = fm.l_flat
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]

    face_w = max(1.0, float(fm.bbox[2]))
    px_per_mm = face_w / 140.0
    mask = fm.skin_mask
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    a_exc = _local_excess(A, mask, sigma_bg)
    l_exc = _local_excess(L, mask, sigma_bg)
    b_exc = _local_excess(B, mask, sigma_bg)

    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)
    for zn in ("sous_yeux_g", "sous_yeux_d"):
        z = fm.zones.get(zn)
        if z is not None and z.available:
            core_mask = cv2.bitwise_and(core_mask, cv2.bitwise_not(z.mask))

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px**2))
    a_max = max(a_min + 8, int(np.pi * r_max_px**2))

    red_cands = _blob_candidates(a_exc, core_mask, C.RED_BLOB_K, a_min, a_max)
    dark_cands = _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K, a_min, a_max)
    red_pts = {(cx, cy) for cx, cy, _, _ in red_cands}
    dark_pts = {(cx, cy) for cx, cy, _, _ in dark_cands}
    # Un candidat ne peut satisfaire qu'UNE lesion posee : sans ce retrait, un
    # seul candidat proche de deux points plantes rapprochees les "trouve" tous
    # les deux, et le compte global ne recolle plus a celui du banc officiel
    # (qui, lui, mesure une augmentation NETTE du compte par zone).
    red_libres, dark_libres = set(red_pts), set(dark_pts)

    skin_s = float(S[mask > 0].mean())
    thr_red = _robust_thr(a_exc[core_mask > 0], C.RED_BLOB_K)
    thr_dark = _robust_thr(-l_exc[core_mask > 0], C.DARK_BLOB_K)

    resultats = []
    for p in planted:
        cx, cy, r = p.x, p.y, p.radius
        seuil = APPARIEMENT_RAYONS * r

        # 1. Un candidat blob a-t-il ete PROPOSE pres de la lesion, ET encore
        #    libre (pas deja attribue a une autre lesion posee) ?
        proche_red = sorted(
            (pt for pt in red_libres if (pt[0]-cx)**2+(pt[1]-cy)**2 < seuil**2),
            key=lambda pt: (pt[0]-cx)**2+(pt[1]-cy)**2,
        )
        proche_dark = sorted(
            (pt for pt in dark_libres if (pt[0]-cx)**2+(pt[1]-cy)**2 < seuil**2),
            key=lambda pt: (pt[0]-cx)**2+(pt[1]-cy)**2,
        )
        candidat_trouve = bool(proche_red or proche_dark)
        if proche_red:
            red_libres.discard(proche_red[0])
        elif proche_dark:
            dark_libres.discard(proche_dark[0])

        # 2. Le point est-il DANS la zone de mesure (core_mask), et — question
        #    distincte — dans le masque peau lui-meme AVANT la marge de bord ?
        #    Un signal exactement nul (red=0/dark=0) trahit un point hors
        #    `skin_mask` : `_local_excess` multiplie par ce masque, un pixel
        #    hors peau y vaut donc zero par construction. Ce n'est alors pas
        #    la marge de bord qui a exclu la lesion, c'est le masque peau
        #    lui-meme (sourcil, narine, pilosite) — la lesion posee tombe sur
        #    une region que le moteur exclut delibrement de toute analyse.
        dans_core = bool(core_mask[cy, cx] > 0)
        dans_skin_mask = bool(mask[cy, cx] > 0)

        # 3. Signal mesure au point exact, meme si aucun candidat n'a ete retenu.
        red_ici = float(a_exc[cy, cx])
        dark_ici = float(-l_exc[cy, cx])
        yellow_ici = float(b_exc[cy, cx])

        diag = {
            "zone": zone, "x": cx, "y": cy, "rayon_px": r,
            "dans_core_mask": dans_core,
            "red_mesure": round(red_ici, 2), "seuil_rouge": round(thr_red, 2),
            "dark_mesure": round(dark_ici, 2), "seuil_sombre": round(thr_dark, 2),
            "candidat_propose": candidat_trouve,
        }

        # PRIORITE : si un candidat existe pres du point, c'est lui qui explique
        # ce qui se passe — meme si le pixel exact plante tombe hors core_mask
        # (le centroide d'une tache floutee derive souvent de quelques pixels
        # par rapport au centre demande, et peut retomber juste a l'interieur).
        # Verifier `dans_core` AVANT `candidat_trouve` classait a tort ces cas
        # comme "hors zone de mesure" alors qu'un candidat avait bel et bien
        # ete propose.
        if not candidat_trouve and not dans_core:
            if not dans_skin_mask:
                diag["cause"] = "hors_skin_mask (region exclue : sourcil/narine/levre/pilosite/hors ovale)"
            else:
                diag["cause"] = "hors_marge_de_bord (dans la peau, mais trop pres du contour du masque)"
        elif not candidat_trouve:
            if red_ici < thr_red and dark_ici < thr_dark:
                diag["cause"] = "signal_sous_le_seuil (ni rouge ni sombre assez au-dessus du fond local)"
            else:
                diag["cause"] = "signal_au-dessus_du_seuil_mais_geometrie_rejetee (forme/taille/circularite)"
        else:
            # Un candidat existe : on rejoue la classification EXACTEMENT
            # comme detect_lesions(), sur le patch autour du point trouve.
            cx2, cy2 = (proche_red or proche_dark)[0]
            rr = max(1, int(round(r)))
            h, w = mask.shape
            y0, y1 = max(0, cy2-rr), min(h, cy2+rr+1)
            x0, x1 = max(0, cx2-rr), min(w, cx2+rr+1)
            patch_m = mask[y0:y1, x0:x1] > 0
            red = float(a_exc[y0:y1, x0:x1][patch_m].mean())
            dark = float(l_exc[y0:y1, x0:x1][patch_m].mean())
            yellow = float(b_exc[y0:y1, x0:x1][patch_m].mean())
            cr = max(1, int(rr * 0.5))
            cy0, cy1 = max(0, cy2-cr), min(h, cy2+cr+1)
            cx0, cx1 = max(0, cx2-cr), min(w, cx2+cr+1)
            core_l = float(l_exc[cy0:cy1, cx0:cx1].mean())
            core_s = float(S[cy0:cy1, cx0:cx1].mean())
            src = "rouge" if (cx2, cy2) in red_pts else "sombre"
            ltype = _classify(red, dark, yellow, core_l, core_s, skin_s, r, px_per_mm, src)
            diag["patch_red"] = round(red, 2)
            diag["patch_dark"] = round(dark, 2)
            diag["patch_yellow"] = round(yellow, 2)
            diag["type_rendu"] = ltype
            if ltype is None:
                diag["cause"] = (
                    f"candidat_trouve_mais_classify_rejette "
                    f"(red={red:.2f} dark={dark:.2f} yellow={yellow:.2f} "
                    f"d_mm={2*r/px_per_mm:.2f} RED_IF_DARK={RED_IF_DARK})"
                )
            else:
                # Retrouve, classe — mais dans la BONNE zone ? Le banc officiel
                # compte separement les lesions qui atterrissent dans une zone
                # voisine : une detection reelle, mais une attribution fausse.
                zone_rendue = _zone_of(fm, cx2, cy2)
                if zone_rendue == zone:
                    diag["cause"] = "detecte_et_classe"
                else:
                    diag["cause"] = f"attribuee_a_une_autre_zone ({zone_rendue})"
        resultats.append(diag)
    return resultats


def main() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    pts = _landmarks(img)
    if pts is None:
        raise SystemExit("aucun visage detecte")

    tous = []
    for zone in ZONES:
        tous.extend(diagnostiquer_zone(img, pts, zone))

    manquees = [d for d in tous if d["cause"] != "detecte_et_classe"]
    trouvees = [d for d in tous if d["cause"] == "detecte_et_classe"]

    print(f"\n=== {len(trouvees)}/{len(tous)} retrouvees, {len(manquees)} manquees ===\n")

    causes = Counter(d["cause"].split(" (")[0] for d in manquees)
    print("Repartition des causes d'echec :")
    for c, n in causes.most_common():
        print(f"  {c:<55} {n}")

    print("\nDetail des lesions manquees :")
    for d in manquees:
        print(f"  [{d['zone']:<10}] ({d['x']},{d['y']}) r={d['rayon_px']}px  "
              f"core_mask={d['dans_core_mask']}  "
              f"red={d['red_mesure']}/{d['seuil_rouge']}  "
              f"dark={d['dark_mesure']}/{d['seuil_sombre']}  "
              f"candidat={d['candidat_propose']}")
        print(f"      -> {d['cause']}")


if __name__ == "__main__":
    main()
