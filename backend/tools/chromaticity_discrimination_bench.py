"""Chromaticity Discrimination Bench : la chromaticite locale separe-t-elle
reellement les faux candidats du reste — dans la MEME image, sans jamais
comparer a A ?

────────────────────────────────────────────────────────────────────────
CE QUE `c_light_failure_analysis.py` A TROUVE, ET LE PIEGE A EVITER.

Chromaticite locale (a*/b*) = le plus gros contributeur (39/73) parmi les
causes des nouveaux candidats de C, une fois le biais "C entier differe de
A" corrige. Mais 39/73 candidats "domines par la chromaticite" NE PROUVE
PAS que la chromaticite les distingue des vrais signaux — ca dit
seulement que c'est, pour CES candidats, l'indicateur le plus deviant
PARMI CEUX MESURES. Le piège explicite a eviter : "la chromaticite est
presente -> corrigeons la chromaticite" sans avoir prouve qu'elle separe.

Ce banc construit donc trois populations, TOUTES mesurees DANS C, jamais
comparees a A :
    lesions   — candidats de C apparies a une position de A (le proxy le
                plus proche d'un "vrai" signal disponible sans verite
                terrain annotee sur une vraie photo)
    faux      — candidats de C SANS correspondance en A (les suspects)
    peau_saine— patchs de peau de C n'ayant produit AUCUN candidat

Et compare, par un d de Cohen (meme construction que `feature_lab.py`,
deja validee dans ce projet) :
    lesions vs faux       — la chromaticite separe-t-elle le vrai du faux ?
    faux vs peau_saine    — les faux candidats ressemblent-ils a du bruit
                            de peau normale, ou sont-ils un troisieme groupe
                            distinct ?
    lesions vs peau_saine — verification de coherence (doit deja separer,
                            sinon la mesure elle-meme est suspecte)

CHROMATICITE ABSOLUE vs DIFFERENTIELLE, comme demande : chroma_a/chroma_b
sont les moyennes LAB brutes (absolu) ; chroma_a_exces/chroma_b_exces
utilisent `_local_excess()` — EXACTEMENT la fonction de production deja
utilisee pour le canal rouge/sombre, appliquee ici aux canaux a*/b*
(differentiel : ecart au fond LOCAL, pas une valeur brute).

Rien n'est modifie en production. Aucune image commitee.

Usage :
    python3 backend/tools/chromaticity_discrimination_bench.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.lesions import _local_excess  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.feature_lab import _points_peau_saine  # noqa: E402
from backend.tools.per_view_recall_bench import _candidats_permissifs  # noqa: E402
from backend.tools.real_skin_pilot_session_ab import _charger_oriente  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402

DOSSIER = Path("/home/user/real_skin_pilot/subject_001")
IMAGE_A = DOSSIER / "capture_001.jpg"
IMAGE_C = DOSSIER / "capture_003.jpg"
RAYON_APPARIEMENT = 0.08
N_PEAU_SAINE = 150
SEED = 7


def _mesures(fm, cx: int, cy: int, r_px: float, a_exc, b_exc) -> dict:
    h, w = fm.skin_mask.shape
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]
    L = fm.l_flat
    A_ = fm.lab[:, :, 1] - 128.0
    B_ = fm.lab[:, :, 2] - 128.0

    rr = max(2, int(round(r_px)))
    y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
    x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
    m = fm.skin_mask[y0:y1, x0:x1] > 0
    if m.sum() < 2:
        m = np.ones((y1 - y0, x1 - x0), dtype=bool)

    l_local = float(L[y0:y1, x0:x1][m].mean())
    s_local = float(S[y0:y1, x0:x1][m].mean())
    s_visage = float(S[fm.skin_mask > 0].mean())
    l_norm = min(1.0, max(0.0, l_local / 220.0))
    s_norm = min(1.0, max(0.0, s_local / max(1.0, s_visage * 2)))

    rr2 = rr * 3
    yy0, yy1 = max(0, cy - rr2), min(h, cy + rr2 + 1)
    xx0, xx1 = max(0, cx - rr2), min(w, cx + rr2 + 1)
    m2 = fm.skin_mask[yy0:yy1, xx0:xx1] > 0
    dynamique_locale = float(L[yy0:yy1, xx0:xx1][m2].std()) if m2.sum() > 2 else 0.0
    a_win = A_[yy0:yy1, xx0:xx1][m2] if m2.sum() > 2 else A_[y0:y1, x0:x1][m]
    b_win = B_[yy0:yy1, xx0:xx1][m2] if m2.sum() > 2 else B_[y0:y1, x0:x1][m]
    variation_chroma_locale = float(np.sqrt(a_win.std() ** 2 + b_win.std() ** 2))

    a_exc_local = float(a_exc[y0:y1, x0:x1][m].mean())
    b_exc_local = float(b_exc[y0:y1, x0:x1][m].mean())

    return {
        "luminance": l_local,
        "saturation": s_local,
        "dynamique_locale": dynamique_locale,
        "chroma_a": float(A_[y0:y1, x0:x1][m].mean()),
        "chroma_b": float(B_[y0:y1, x0:x1][m].mean()),
        "chroma_a_exces": a_exc_local,
        "chroma_b_exces": b_exc_local,
        "distance_chroma_exces": float(np.sqrt(a_exc_local ** 2 + b_exc_local ** 2)),
        "variation_chroma_locale": variation_chroma_locale,
        "reflet_speculaire": l_norm * (1.0 - s_norm),
    }


def _appareiller_positions(a: List[tuple], b: List[tuple], rayon: float):
    dispo = list(range(len(b)))
    out = []
    for r in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            n = b[i]
            d = ((r[0] - n[0]) ** 2 + (r[1] - n[1]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            out.append((r, meilleur))
            dispo.remove(meilleur)
        else:
            out.append((r, None))
    return out


def _d(a: List[float], b: List[float]) -> float:
    va, vb = np.array(a), np.array(b)
    pooled = np.sqrt((va.var(ddof=1) + vb.var(ddof=1)) / 2) or 1e-6
    return float((va.mean() - vb.mean()) / pooled)


def run() -> None:
    img_a = _charger_oriente(IMAGE_A)
    img_c = _charger_oriente(IMAGE_C)
    fm_a = build_face_map(_b64(img_a, quality=100))
    fm_c = build_face_map(_b64(img_c, quality=100))
    if not fm_a.detected or not fm_c.detected:
        raise SystemExit("visage non detecte sur A ou C")

    face_w = max(1.0, float(fm_c.bbox[2]))
    px_per_mm = face_w / 140.0
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    A_c = fm_c.lab[:, :, 1] - 128.0
    B_c = fm_c.lab[:, :, 2] - 128.0
    a_exc = _local_excess(A_c, fm_c.skin_mask, sigma_bg)
    b_exc = _local_excess(B_c, fm_c.skin_mask, sigma_bg)

    cands_a = _candidats_permissifs(fm_a, 1.00)
    cands_c = _candidats_permissifs(fm_c, 1.00)
    pts_a = [(c["x"], c["y"]) for c in cands_a]
    appariement = _appareiller_positions(pts_a, [(c["x"], c["y"]) for c in cands_c], RAYON_APPARIEMENT)
    idx_c_apparies = {j for _, j in appariement if j is not None}
    c_apparies = [cands_c[j] for j in idx_c_apparies]
    c_nouveaux = [c for i, c in enumerate(cands_c) if i not in idx_c_apparies]

    x0, y0, bw, bh = fm_c.bbox
    tous_pts_px = [(int(round(c["x"] * bw + x0)), int(round(c["y"] * bh + y0))) for c in cands_c]
    r_moyen = int(round(np.mean([c["r_px"] for c in cands_c]))) if cands_c else 6
    pts_peau = _points_peau_saine(fm_c.skin_mask, tous_pts_px, N_PEAU_SAINE, r_moyen, SEED)

    def _population(cands, en_pixels=False):
        out = []
        for c in cands:
            if en_pixels:
                cx, cy = c
                r_px = r_moyen
            else:
                cx = int(round(c["x"] * bw + x0))
                cy = int(round(c["y"] * bh + y0))
                r_px = c["r_px"]
            out.append(_mesures(fm_c, cx, cy, r_px, a_exc, b_exc))
        return out

    mesures_lesions = _population(c_apparies)
    mesures_faux = _population(c_nouveaux)
    mesures_peau = _population(pts_peau, en_pixels=True)

    print(f"populations : lesions(proxy)={len(mesures_lesions)}  "
          f"faux_candidats={len(mesures_faux)}  peau_saine={len(mesures_peau)}\n")

    cles = ["luminance", "saturation", "dynamique_locale", "chroma_a", "chroma_b",
            "chroma_a_exces", "chroma_b_exces", "distance_chroma_exces",
            "variation_chroma_locale", "reflet_speculaire"]

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
    ecart_type = lambda xs: (sum((x - moy(xs)) ** 2 for x in xs) / len(xs)) ** 0.5 if xs else 0.0

    print("=" * 110)
    print(f"{'feature':<24} {'lesions(proxy)':>16} {'faux candidats':>16} {'peau saine':>16} "
          f"{'d(les.vs faux)':>15} {'d(faux vs peau)':>16} {'d(les.vs peau)':>15}")
    print("=" * 110)
    for cle in cles:
        vl = [m[cle] for m in mesures_lesions]
        vf = [m[cle] for m in mesures_faux]
        vp = [m[cle] for m in mesures_peau]
        print(f"{cle:<24} {moy(vl):>9.2f}+-{ecart_type(vl):<5.1f} "
              f"{moy(vf):>9.2f}+-{ecart_type(vf):<5.1f} "
              f"{moy(vp):>9.2f}+-{ecart_type(vp):<5.1f} "
              f"{_d(vl, vf):>15.2f} {_d(vf, vp):>16.2f} {_d(vl, vp):>15.2f}")

    print("\nLecture : |d| >= 0,8 = grand ecart (feature discriminante) ; ~0,5 = modere ; "
          "<0,2 = negligeable (populations quasi confondues). "
          "'lesions vs peau' doit deja separer nettement, sinon la mesure elle-meme est douteuse.")
    print("Rien modifie en production.")


if __name__ == "__main__":
    run()
