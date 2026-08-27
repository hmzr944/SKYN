"""Matrice d'invariance : plusieurs familles de normalisation, plusieurs
perturbations, une seule question — laquelle stabilise reellement la mesure,
et laquelle deplace juste le probleme ailleurs ?

────────────────────────────────────────────────────────────────────────
CE QUE CE BANC FAIT, ET CE QU'IL NE FAIT PAS.

`stability_bench.py` a mesure l'instabilite et l'a expliquee pour le cas le
plus severe (le contraste). Ce script teste des CORRECTIONS CANDIDATES avant
d'en retenir une — aucune n'est adoptee en production ici.

Trois familles, choisies pour representer des strategies vraiment
differentes plutot que des variantes du meme geste :

  aucune              — le moteur tel qu'il est aujourd'hui (reference).
  photometrique_clahe — Option 1 : normaliser l'IMAGE avant toute mesure
                        (egalisation adaptative du canal L, avant meme la
                        detection des reperes).
  excess_zscore_local — Option 2/3 : normaliser la FEATURE, pas l'image.
                        Le seuil actuel compare un exces de couleur LOCAL
                        (deja relatif au fond local — c'est ce que fait
                        `_local_excess`) a un seuil robuste GLOBAL, calcule
                        une fois sur toute la peau. Un etirement de contraste
                        gonfle l'exces a peu pres partout a la fois, et ce
                        seuil global ne suit pas la meme cadence. Cette
                        variante remplace le seuil global par un ECART-TYPE
                        LOCAL (meme construction que le fond local, mais sur
                        le carre des ecarts) : le candidat est compare a la
                        dispersion de SON voisinage, pas a celle du visage
                        entier. Sous un etirement de contraste globalement
                        affine (`chan' = a*chan + b`), le fond local et
                        l'ecart-type local sont mis a l'echelle par le meme
                        facteur `a` que le signal — le rapport des deux,
                        c'est-a-dire le z-score, doit rester approximativement
                        constant. C'est l'hypothese testee ici, pas un
                        resultat suppose.
  clahe_et_zscore     — les deux combinees.

Ce que ce banc NE mesure PAS : le score global (`global_score`). Il depend
de l'assemblage complet — phenotype, empreinte, routine — que reproduire
fidelement hors production duppliquerait une bonne partie du moteur pour un
gain d'information marginal ici. La question posee est plus etroite et plus
utile a ce stade : la DETECTION DE CANDIDATS elle-meme devient-elle plus
stable ? C'est elle qui, en amont, determine tout le reste.

Usage :
    python3 backend/tools/invariance_matrix.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    _classify,
    _passes_shape,
    _shape_stats,
    _split_touching,
)
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.stability_bench import (  # noqa: E402
    _contraste,
    _identite,
    _luminosite,
    _rotation,
)

IMAGE = Path("backend/tests/fixtures_face.jpg")
APPARIEMENT = 0.05  # meme rayon que stability_bench.py, meme raison


def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


# --------------------------------------------------------------------------
# Perturbations — exactement l'ensemble demande.
# --------------------------------------------------------------------------
PERTURBATIONS: List[Tuple[str, Callable[[np.ndarray], np.ndarray], int]] = [
    ("original", _identite, 100),
    ("jpeg_95", _identite, 95),
    ("jpeg_85", _identite, 85),
    ("contraste_+5%", _contraste(1.05), 95),
    ("contraste_+10%", _contraste(1.10), 95),
    ("contraste_+15%", _contraste(1.15), 95),
    ("luminosite_+10%", _luminosite(int(255 * 0.10)), 95),
    ("rotation_1deg", _rotation(1.0), 95),
    ("rotation_2deg", _rotation(2.0), 95),
]


# --------------------------------------------------------------------------
# Familles de normalisation.
# --------------------------------------------------------------------------
def _clahe_L(img: np.ndarray) -> np.ndarray:
    """Egalisation adaptative locale du canal L — normalisation PHOTOMETRIQUE,
    appliquee a l'image avant tout le reste du pipeline (reperes compris)."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l2, a, b]), cv2.COLOR_LAB2BGR)


def _local_stats(chan: np.ndarray, mask: np.ndarray, sigma: float):
    """Fond local ET dispersion locale — meme construction que
    `lesions._local_excess`, etendue au second moment."""
    m = (mask > 0).astype(np.float32)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    num = cv2.GaussianBlur(chan * m, (0, 0), sigma)
    bg = num / np.maximum(den, 1e-3)
    sq = cv2.GaussianBlur(((chan - bg) ** 2) * m, (0, 0), sigma)
    var = sq / np.maximum(den, 1e-3)
    std = np.sqrt(np.maximum(var, 1e-6))
    return (chan - bg) * m, std


def _candidats_zscore(chan_excess: np.ndarray, local_std: np.ndarray, mask: np.ndarray,
                      z_seuil: float, a_min: int, a_max: int, r_min_px: float):
    """Meme geometrie de detection que `_blob_candidates` (ouverture,
    composantes connexes, filtres de forme, separation des amas), mais le
    seuil de binarisation est un Z-SCORE LOCAL plutot qu'un seuil robuste
    GLOBAL — c'est la seule difference testee ici."""
    z = chan_excess / np.maximum(local_std, 1e-3)
    binary = ((z > z_seuil) & (mask > 0)).astype(np.uint8) * 255
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, cent = cv2.connectedComponentsWithStats(binary, connectivity=8)

    # (cx, cy, aire) — l'aire est necessaire en aval pour estimer un rayon
    # fidele : sans elle, `_classify` recevait un rayon constant arbitraire,
    # faussant ses conditions de taille (`d_mm`) pour chaque candidat.
    out = []
    for i in range(1, n):
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        comp = (labels[
            stats[i, cv2.CC_STAT_TOP]:stats[i, cv2.CC_STAT_TOP] + bh,
            stats[i, cv2.CC_STAT_LEFT]:stats[i, cv2.CC_STAT_LEFT] + bw
        ] == i).astype(np.uint8)
        shape = _shape_stats(comp)
        if shape is None:
            continue
        s_area, s_bw, s_bh, fill, circ = shape
        if _passes_shape(s_area, s_bw, s_bh, fill, circ, a_min, a_max):
            out.append((int(cent[i][0]), int(cent[i][1]), float(s_area)))
            continue
        if s_area < a_min * 1.6:
            continue
        for frag in _split_touching(comp, r_min_px):
            fshape = _shape_stats(frag)
            if fshape is None:
                continue
            f_area, f_bw, f_bh, f_fill, f_circ = fshape
            if not _passes_shape(f_area, f_bw, f_bh, f_fill, f_circ, a_min, a_max):
                continue
            ys, xs = np.nonzero(frag)
            top, left = int(stats[i, cv2.CC_STAT_TOP]), int(stats[i, cv2.CC_STAT_LEFT])
            out.append((int(round(float(xs.mean()))) + left, int(round(float(ys.mean()))) + top, float(f_area)))
    return out


def detecte_avec_zscore(fm, z_rouge: float = 2.2, z_sombre: float = 2.6) -> List[dict]:
    """Reimplementation experimentale de `detect_lesions`, seuil local au lieu
    de seuil global. Reutilise `_classify` telle quelle : seule l'ETAPE DE
    SELECTION DES CANDIDATS change, pas la regle qui decide leur type."""
    if not fm.detected or fm.skin_mask.sum() == 0:
        return []

    face_w = max(1.0, float(fm.bbox[2]))
    px_per_mm = face_w / 140.0
    lab = fm.lab
    A = lab[:, :, 1] - 128.0
    B = lab[:, :, 2] - 128.0
    L = fm.l_flat
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]

    mask = fm.skin_mask
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    a_exc, a_std = _local_stats(A, mask, sigma_bg)
    l_exc, l_std = _local_stats(L, mask, sigma_bg)
    b_exc, _ = _local_stats(B, mask, sigma_bg)

    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)
    for zn in ("sous_yeux_g", "sous_yeux_d"):
        z = fm.zones.get(zn)
        if z is not None and z.available:
            core_mask = cv2.bitwise_and(core_mask, cv2.bitwise_not(z.mask))

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    cands: Dict[Tuple[int, int], Tuple[float, str]] = {}
    for cx, cy, area in _candidats_zscore(a_exc, a_std, core_mask, z_rouge, a_min, a_max, r_min_px):
        cands[(cx, cy)] = (area, "rouge")
    for cx, cy, area in _candidats_zscore(-l_exc, l_std, core_mask, z_sombre, a_min, a_max, r_min_px):
        if (cx, cy) not in cands:
            cands[(cx, cy)] = (area, "sombre")

    if not cands:
        return []

    # Dedup en gardant la plus grande aire d'abord — meme regle que
    # `detect_lesions()` en production.
    min_sep = max(3.0, 1.2 * px_per_mm)
    pts = sorted(cands.items(), key=lambda kv: -kv[1][0])
    kept: List[Tuple[int, int, float, str]] = []
    for (cx, cy), (area, src) in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < min_sep ** 2 for kx, ky, _, _ in kept):
            continue
        kept.append((cx, cy, area, src))

    h, w = mask.shape
    bx, by, bw, bh = fm.bbox
    norm_dim = float(max(bw, bh)) or 1.0
    skin_s = float(S[mask > 0].mean())

    out = []
    for cx, cy, area, src in kept:
        # Rayon estime a partir de l'aire REELLE du candidat, comme en
        # production (`r_px = sqrt(aire/pi)`) — pas une constante arbitraire,
        # qui aurait fausse les conditions de taille de `_classify`.
        r_px = float(np.sqrt(max(area, 1.0) / np.pi))
        rr = max(1, int(round(r_px)))
        y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
        x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
        patch_m = mask[y0:y1, x0:x1] > 0
        if patch_m.sum() < 3:
            continue
        red = float(a_exc[y0:y1, x0:x1][patch_m].mean())
        dark = float(l_exc[y0:y1, x0:x1][patch_m].mean())
        yellow = float(b_exc[y0:y1, x0:x1][patch_m].mean())
        cr = max(1, int(r_px * 0.5))
        cy0, cy1 = max(0, cy - cr), min(h, cy + cr + 1)
        cx0, cx1 = max(0, cx - cr), min(w, cx + cr + 1)
        core_l = float(l_exc[cy0:cy1, cx0:cx1].mean())
        core_s = float(S[cy0:cy1, cx0:cx1].mean())
        ltype = _classify(red, dark, yellow, core_l, core_s, skin_s, r_px, px_per_mm, src)
        if ltype is None:
            continue
        out.append({
            "type": ltype,
            "x": float((cx - bx) / max(1, bw)),
            "y": float((cy - by) / max(1, bh)),
        })
    return out


# --------------------------------------------------------------------------
def _appareiller(ref: List[dict], nouveau: List[dict]):
    dispo = list(range(len(nouveau)))
    tp, lost = 0, 0
    for r in ref:
        meilleur, meilleure_dist = None, APPARIEMENT
        for i in dispo:
            n = nouveau[i]
            d = ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            tp += 1
            dispo.remove(meilleur)
        else:
            lost += 1
    fp = len(dispo)  # ce qui reste, apparie a rien dans la reference
    return tp, fp, lost


def _lesions_aucune(bgr: np.ndarray, quality: int) -> List[dict]:
    from backend.skyn_engine.v2.pipeline import analyze_face
    out = analyze_face(_b64(bgr, quality))
    return out.lesions if out.ok else []


def _lesions_zscore(bgr: np.ndarray, quality: int) -> List[dict]:
    fm = build_face_map(_b64(bgr, quality))
    return detecte_avec_zscore(fm)


STRATEGIES: List[Tuple[str, Callable[[np.ndarray], np.ndarray], Callable]] = [
    ("aucune", lambda im: im, _lesions_aucune),
    ("photometrique_clahe", _clahe_L, _lesions_aucune),
    ("excess_zscore_local", lambda im: im, _lesions_zscore),
    ("clahe_et_zscore", _clahe_L, _lesions_zscore),
]


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")

    # Reference absolue : image d'origine, sans normalisation.
    ref = _lesions_aucune(img, 100)
    print(f"REFERENCE (originale, sans normalisation) : {len(ref)} lesions\n")

    resultats = {}
    for strat_nom, pretraite, detecteur in STRATEGIES:
        for pert_nom, perturbe, quality in PERTURBATIONS:
            bgr = pretraite(perturbe(img))
            lesions = detecteur(bgr, quality)
            tp, fp, lost = _appareiller(ref, lesions)
            resultats[(strat_nom, pert_nom)] = (len(lesions), tp, fp, lost)

    for strat_nom, _, _ in STRATEGIES:
        print(f"=== {strat_nom} ===")
        print(f"{'perturbation':<18} {'n':>4} {'TP':>4} {'FP':>4} {'perdues':>8}")
        for pert_nom, _, _ in PERTURBATIONS:
            n, tp, fp, lost = resultats[(strat_nom, pert_nom)]
            print(f"{pert_nom:<18} {n:>4} {tp:>4} {fp:>4} {lost:>8}")
        # Stabilite resumee : moyenne du (FP+perdues) sur les perturbations
        # autres que "original" — c'est la partie qui doit etre minimisee.
        hors_ref = [resultats[(strat_nom, p)] for p, _, _ in PERTURBATIONS if p != "original"]
        moy_bruit = sum(fp + lost for _, _, fp, lost in hors_ref) / len(hors_ref)
        print(f"  -> bruit moyen (FP + perdues) hors reference : {moy_bruit:.2f}\n")


if __name__ == "__main__":
    run()
