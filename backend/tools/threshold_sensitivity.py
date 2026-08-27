"""Banc de sensibilite au seuil : quantifier la fragilite d'une decision,
candidat par candidat, sans toucher a l'image.

────────────────────────────────────────────────────────────────────────
CE QUE CE BANC REPOND.

L'audit rotation et l'audit contraste ont converge vers la MEME explication :
un candidat dont le signal franchit un seuil de justesse bascule sous
n'importe quelle petite perturbation, alors qu'un candidat au signal net y
resiste. Le moteur, lui, ne fait aucune difference entre les deux — la
decision est binaire (`_classify` renvoie un type ou `None`), sans notion de
marge.

Ce banc mesure cette marge directement, sans passer par l'image. Pour
chaque candidat REELEMENT mesure sur la photo de reference (candidats
retenus ET rejetes — le rejet aussi merite d'etre caracterise), le signal
d'entree (rouge, sombre, jaune) est mis a l'echelle par une serie de
facteurs -10 % a +10 %, et on regarde a quel moment, s'il y en a un, la
DECISION de `_classify` change. C'est une analyse de sensibilite de la
regle de decision elle-meme, pas une nouvelle simulation de capture — la
question posee est plus etroite et plus directe : "a quelle distance ce
candidat se trouve-t-il de sa frontiere de decision ?"

Trois issues possibles par candidat :
  STABLE  — la decision ne change sur AUCUNE des perturbations testees.
  BASCULE — la decision change quelque part dans l'intervalle ; on releve
            la plus petite perturbation qui suffit a la faire changer,
            c'est la mesure de fragilite elle-meme.
  BRUIT   — rejete a 0 %, et rejete sur toute la plage : jamais assez pres
            d'une frontiere pour meme etre une candidate fragile.

Aucun seuil "fort/probable/incertain/rejete" n'est fixe ici. Ce banc rend
la distribution des distances a la frontiere ; ou la couper est une decision
separee, a prendre UNE FOIS cette distribution vue — pas avant.

Usage :
    python3 backend/tools/threshold_sensitivity.py
"""
from __future__ import annotations

import base64
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    _blob_candidates,
    _classify,
    _local_excess,
)
from backend.skyn_engine.v2.zones import build_face_map, FaceMap  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")

# Exactement l'ensemble demande.
PERTURBATIONS_PCT = [-10, -5, -2, -1, 0, 1, 2, 5, 10]


@dataclass
class Candidat:
    zone: str
    x: int
    y: int
    red: float
    dark: float
    yellow: float
    core_l: float
    core_s: float
    skin_s: float
    r_px: float
    px_per_mm: float
    src: str
    decision_0: Optional[str]  # decision a 0 % — la classification actuelle


def _b64(img: np.ndarray, quality: int = 100) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode()


def _tous_les_candidats(fm: FaceMap) -> List[Candidat]:
    """Rejoue `detect_lesions()` jusqu'au bout, mais garde TOUS les
    candidats — y compris ceux que `_classify` rejette — plutot que de ne
    renvoyer que le rapport final. Le rejet est une decision comme une
    autre ; il merite d'etre caracterise, pas simplement tu."""
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
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    cands = {}
    for cx, cy, area, _ in _blob_candidates(a_exc, core_mask, C.RED_BLOB_K, a_min, a_max):
        cands[(cx, cy)] = (area, "rouge")
    for cx, cy, area, _ in _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K, a_min, a_max):
        if (cx, cy) not in cands:
            cands[(cx, cy)] = (area, "sombre")

    pts = sorted(cands.items(), key=lambda kv: -kv[1][0])
    min_sep = max(3.0, 1.2 * px_per_mm)
    kept = []
    for (cx, cy), (area, src) in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < min_sep ** 2 for kx, ky, _, _ in kept):
            continue
        kept.append((cx, cy, area, src))

    h, w = mask.shape
    skin_s = float(S[mask > 0].mean())
    out: List[Candidat] = []
    for cx, cy, area, src in kept:
        r_px = float(np.sqrt(area / np.pi))
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
        zone = next((n for n, z in fm.zones.items() if z.available and z.mask[cy, cx] > 0), "autre")
        d0 = _classify(red, dark, yellow, core_l, core_s, skin_s, r_px, px_per_mm, src)
        out.append(Candidat(zone, cx, cy, red, dark, yellow, core_l, core_s,
                            skin_s, r_px, px_per_mm, src, d0))
    return out


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    fm = build_face_map(_b64(img))
    if not fm.detected:
        raise SystemExit("visage non detecte")

    candidats = _tous_les_candidats(fm)
    print(f"{len(candidats)} candidats releves (retenus ET rejetes)\n")

    resultats = []
    for c in candidats:
        decisions = {}
        for pct in PERTURBATIONS_PCT:
            f = 1.0 + pct / 100.0
            d = _classify(c.red * f, c.dark * f, c.yellow * f, c.core_l * f,
                         c.core_s, c.skin_s, c.r_px, c.px_per_mm, c.src)
            decisions[pct] = d

        # La plus petite perturbation qui fait changer la decision, en
        # s'eloignant de 0 dans CHAQUE sens separement — pas un simple
        # parcours de la liste, qui donnerait la bascule la plus NEGATIVE
        # trouvee en premier plutot que la plus proche de 0.
        cote_neg = [p for p in PERTURBATIONS_PCT if p < 0]
        cote_pos = [p for p in PERTURBATIONS_PCT if p > 0]
        premiere_bascule = None
        for p in sorted(cote_neg, key=abs) :
            if decisions[p] != c.decision_0:
                premiere_bascule = abs(p)
                break
        for p in sorted(cote_pos):
            if decisions[p] != c.decision_0:
                premiere_bascule = min(premiere_bascule, p) if premiere_bascule else p
                break

        if c.decision_0 is None and premiere_bascule is None:
            categorie = "BRUIT"
        elif premiere_bascule is None:
            categorie = "STABLE"
        else:
            categorie = "BASCULE"

        resultats.append((c, categorie, premiere_bascule))

    stables = [r for r in resultats if r[1] == "STABLE"]
    bascule = [r for r in resultats if r[1] == "BASCULE"]
    bruit = [r for r in resultats if r[1] == "BRUIT"]

    print(f"STABLE  : {len(stables):>3}  (decision inchangee sur ±10 %)")
    print(f"BASCULE : {len(bascule):>3}  (change de decision dans l'intervalle)")
    print(f"BRUIT   : {len(bruit):>3}  (rejete a 0 %, rejete sur toute la plage)\n")

    if bascule:
        print(f"{'zone':<10} {'decision (0%)':<14} {'red':>6} {'dark':>7} "
              f"{'plus petite bascule':>20}")
        for c, _, pct in sorted(bascule, key=lambda r: r[2]):
            print(f"{c.zone:<10} {str(c.decision_0):<14} {c.red:>6.2f} {c.dark:>7.2f} "
                  f"{pct:>18}%")

    if stables:
        print(f"\n{'zone':<10} {'decision (0%)':<14} {'red':>6} {'dark':>7}")
        for c, _, _ in sorted(stables, key=lambda r: (r[0].decision_0 is None, r[0].red)):
            print(f"{c.zone:<10} {str(c.decision_0):<14} {c.red:>6.2f} {c.dark:>7.2f}")

    detectes = [r for r in resultats if r[0].decision_0 is not None]
    if detectes:
        fragiles = [r[2] for r in detectes if r[2] is not None]
        solides = len(detectes) - len(fragiles)
        print(f"\nParmi les {len(detectes)} candidats ACTUELLEMENT DETECTES : "
              f"{solides} ne basculent a aucune perturbation testee (marge > 10 %), "
              f"{len(fragiles)} basculent des ±{min(fragiles) if fragiles else '-'} %")


if __name__ == "__main__":
    run()
