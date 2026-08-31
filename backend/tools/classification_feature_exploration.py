"""P1 — Classification R&D : quelles caractéristiques séparent réellement une
vraie lésion d'un candidat parasite, indépendamment de red/dark absolus ?

REGLE STRICTE, comme tout ce fil : lesions.py et calibration.py restent
intacts. Ce script ne fait qu'OBSERVER — mesurer la séparabilité de
nouvelles features sur un jeu candidats-vrais / candidats-faux, jamais les
brancher sur une décision de production.

────────────────────────────────────────────────────────────────────────
POURQUOI CES FEATURES, PAS D'AUTRES.

`_blob_candidates()` filtre déjà forme/circularité/remplissage à la
génération (`_passes_shape`) — TOUS les candidats qui arrivent jusqu'ici,
vrais ou faux, ont déjà passé ce filtre. Refaire "forme/circularité" comme
feature de classification mesurerait donc surtout du bruit : la variable a
déjà été tronquée à sa plage "plausible" avant même d'atteindre ce banc.
Ecarté ici pour cette raison, pas par oubli.

Ce qui N'est PAS déjà gardé par un filtre en amont, et que ce banc mesure :

  contraste_centre_bord   — le coeur du candidat est-il net contre son
                             pourtour immédiat, ou le patch est-il
                             globalement egal (plus proche d'une variation
                             d'éclairage que d'un relief) ?
  force_bord              — magnitude du gradient (Sobel) sur le pourtour
                             du candidat — un vrai relief a un bord marqué,
                             une variation d'éclairage un bord flou.
  dispersion_signal       — coefficient de variation du rouge DANS le
                             patch — un vrai bouton est structuré
                             (coeur/halo), du bruit est plus homogène ou
                             erratique.
  asymetrie_lumiere_ombre — deja construite dans
                             cheek_candidate_diagnostic.py (moitié claire
                             moins moitié sombre du patch) — reprise ici
                             sans redéfinition.
  texture_environnante    — variance locale de luminance DANS le candidat
                             rapportée a celle de la peau autour — un vrai
                             bouton rompt la texture cutanée normale.
  taille_mm               — deja disponible (d_mm), rappelée pour
                             comparaison.

────────────────────────────────────────────────────────────────────────
POPULATIONS

  VRAI  = candidat apparié a une lésion synthétique plantée (position
          connue, backend/tools/synth_lesions.py, deja valide).
  FAUX  = tout autre candidat genere sur les memes photos marquees — du
          bruit de peau reel, dans les memes conditions de lumiere que les
          vrais, pas un jeu synthetique separe.

8 photos reelles (sujet 001, plusieurs eclairages/angles deja documentes
dans cette session) x 13 zones — le pool de candidats est donc deja
multi-condition par construction, pas perturbe synthetiquement comme
feature_lab.py le faisait sur une seule image.

LIMITE HONNETE : un seul sujet reel (+ le fixture du depot pour un second).
Ce banc mesure une separabilite, pas une preuve de generalisation a toute
une population.

Usage :
    python3 backend/tools/classification_feature_exploration.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from skyn_engine.v2.zones import ZONE_LANDMARKS  # noqa: E402
from skyn_engine.v2.lesions import RED_IF_DARK  # noqa: E402
from tools.synth_lesions import _landmarks, plant  # noqa: E402
from tools.cheek_candidate_diagnostic import (  # noqa: E402
    Champs, Candidat, _candidats, _charger_oriente_bgr, _b64_from_bgr,
    build_face_map,
)

SUBJECT = Path("/home/user/real_skin_pilot/subject_001")
PHOTOS = [SUBJECT / f"capture_{i}.jpg" for i in
          ("001", "002", "003", "004", "005", "006", "007", "008")]
FIXTURE = BACKEND / "tests" / "fixtures_face.jpg"  # deuxieme sujet, deja dans le depot
ZONES = list(ZONE_LANDMARKS.keys())
N_PAR_ZONE = 3
SEED = 29
RAYON_APPARIEMENT_MULT = 2.5  # meme logique que engine_loss_funnel_audit.py


def extra_features(c: Candidat, champs: Champs) -> Dict[str, float]:
    fm = champs.fm
    h, w = champs.core_mask.shape
    cx, cy, r = c.cx, c.cy, c.r_px
    rr = max(2, int(round(r)))
    y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
    x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
    patch_mask = fm.skin_mask[y0:y1, x0:x1] > 0

    cr = max(1, int(r * 0.5))
    coeur_sel = patch_mask & (dist2 <= cr ** 2)
    anneau_sel = patch_mask & (dist2 > cr ** 2) & (dist2 <= rr ** 2)
    coeur_a = float(champs.a_exc[y0:y1, x0:x1][coeur_sel].mean()) if coeur_sel.sum() else c.red
    anneau_a = float(champs.a_exc[y0:y1, x0:x1][anneau_sel].mean()) if anneau_sel.sum() else c.red
    contraste_centre_bord = coeur_a - anneau_a

    vals = champs.a_exc[y0:y1, x0:x1][patch_mask]
    dispersion_signal = float(vals.std() / (abs(vals.mean()) + 1e-3)) if vals.size >= 3 else 0.0

    gray = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    bord_sel = patch_mask & (dist2 > (rr * 0.6) ** 2)
    force_bord = float(grad[y0:y1, x0:x1][bord_sel].mean()) if bord_sel.sum() else 0.0

    # Texture environnante : variance locale de L DANS le candidat vs dans
    # un anneau plus large autour (2x le rayon), sur la peau uniquement.
    k = max(3, int(r))
    mean_l = cv2.blur(champs.L, (k, k))
    var_l = cv2.blur(champs.L * champs.L, (k, k)) - mean_l * mean_l
    var_l = np.maximum(var_l, 0.0)
    rr2 = int(rr * 2)
    y0b, y1b = max(0, cy - rr2), min(h, cy + rr2 + 1)
    x0b, x1b = max(0, cx - rr2), min(w, cx + rr2 + 1)
    yyb, xxb = np.mgrid[y0b:y1b, x0b:x1b]
    dist2b = (yyb - cy) ** 2 + (xxb - cx) ** 2
    mask_large = fm.skin_mask[y0b:y1b, x0b:x1b] > 0
    interieur = mask_large & (dist2b <= rr ** 2)
    exterieur = mask_large & (dist2b > rr ** 2) & (dist2b <= rr2 ** 2)
    tex_int = float(var_l[y0b:y1b, x0b:x1b][interieur].mean()) if interieur.sum() else 0.0
    tex_ext = float(var_l[y0b:y1b, x0b:x1b][exterieur].mean()) if exterieur.sum() else 1.0
    texture_ratio = tex_int / max(1e-3, tex_ext)

    return {
        "red": c.red,
        "dark": c.dark,
        "asymetrie_lumiere_ombre": (
            (c.red_moitie_claire - c.red_moitie_sombre)
            if c.red_moitie_claire is not None and c.red_moitie_sombre is not None
            else 0.0
        ),
        "contraste_centre_bord": contraste_centre_bord,
        "force_bord": force_bord,
        "dispersion_signal": dispersion_signal,
        "texture_ratio": texture_ratio,
        "taille_mm": c.d_mm,
    }


def _apparier(cands: List[Candidat], planted, rayon_mult: float):
    """Meme logique que engine_loss_funnel_audit.py : chaque lesion plantee
    cherche son plus proche candidat, sans reutiliser un candidat deja pris."""
    dispo = list(cands)
    vrais_idx = set()
    for p in planted:
        rayon = max(6.0, p.radius * rayon_mult)
        meilleur, meilleure_dist = None, rayon
        for c in dispo:
            d = ((c.cx - p.x) ** 2 + (c.cy - p.y) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = c, d
        if meilleur is not None:
            vrais_idx.add(id(meilleur))
            dispo.remove(meilleur)
    return vrais_idx


def collecter(photos: List[Path]) -> tuple:
    vrais: List[Dict[str, float]] = []
    faux: List[Dict[str, float]] = []
    n_photos_ok = 0

    for photo in photos:
        bgr = _charger_oriente_bgr(photo)
        pts = _landmarks(bgr)
        if pts is None:
            continue
        n_photos_ok += 1

        for zone in ZONES:
            try:
                marque, planted = plant(bgr, pts, zone, N_PAR_ZONE, seed=SEED)
            except SystemExit:
                continue
            fm = build_face_map(_b64_from_bgr(marque, quality=100))
            if not fm.detected:
                continue
            champs = Champs(fm)
            cands = _candidats(champs)
            if not cands:
                continue
            vrais_idx = _apparier(cands, planted, RAYON_APPARIEMENT_MULT)
            for c in cands:
                feats = extra_features(c, champs)
                feats["zone"] = zone
                feats["photo"] = photo.name
                (vrais if id(c) in vrais_idx else faux).append(feats)

    return vrais, faux, n_photos_ok


def _cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2) or 1e-6
    return float((a.mean() - b.mean()) / pooled)


FEATURES = ["red", "dark", "asymetrie_lumiere_ombre", "contraste_centre_bord",
            "force_bord", "dispersion_signal", "texture_ratio", "taille_mm"]


def rapporter(vrais: List[Dict], faux: List[Dict], titre: str) -> None:
    print(f"\n{titre} — n_vrais={len(vrais)}  n_faux={len(faux)}")
    if not vrais or not faux:
        print("  (population insuffisante, section ignorée)")
        return
    print(f"{'feature':<26}{'vrais (moy±ec)':<22}{'faux (moy±ec)':<22}{'d de Cohen':>12}")
    ds = {}
    for f in FEATURES:
        va = np.array([v[f] for v in vrais])
        fa = np.array([x[f] for x in faux])
        d = _cohen_d(va, fa)
        ds[f] = d
        print(f"{f:<26}{va.mean():>8.2f} ± {va.std():<9.2f}"
              f"{fa.mean():>8.2f} ± {fa.std():<9.2f}{d:>12.2f}")
    print("  (|d| > 0.8 : forte séparation — 0.5-0.8 : modérée — < 0.2 : négligeable)")
    ordre = sorted(ds.items(), key=lambda kv: -abs(kv[1]))
    print("  Classement par |d| décroissant : " + ", ".join(f"{k}({v:+.2f})" for k, v in ordre))


def main() -> None:
    photos = PHOTOS + ([FIXTURE] if FIXTURE.exists() else [])
    print(f"Collecte sur {len(photos)} photos × {len(ZONES)} zones "
          f"({N_PAR_ZONE} lésions/zone)...\n")
    vrais, faux, n_ok = collecter(photos)
    print(f"{n_ok}/{len(photos)} photos exploitables.")

    print("\n" + "=" * 100)
    print("SÉPARABILITÉ — population complète")
    print("=" * 100)
    rapporter(vrais, faux, "Toutes zones, toutes conditions")

    print("\n" + "=" * 100)
    print("SÉPARABILITÉ — zone grise uniquement (dark≤-1.2, 1.5≤red≤4.5)")
    print("Là où red/dark seuls ne peuvent déjà plus trancher (voir le benchmark RED/DARK)")
    print("=" * 100)
    zone_grise = lambda pop: [p for p in pop if p["dark"] <= -1.2 and 1.5 <= p["red"] <= RED_IF_DARK]
    rapporter(zone_grise(vrais), zone_grise(faux), "Zone grise")

    print("\n" + "=" * 100)
    print("SÉPARABILITÉ — bas/côtés du visage uniquement (joues, mâchoire, menton)")
    print("=" * 100)
    zones_bas = {"joue_g", "joue_d", "machoire_g", "machoire_d", "menton"}
    filtre_bas = lambda pop: [p for p in pop if p["zone"] in zones_bas]
    rapporter(filtre_bas(vrais), filtre_bas(faux), "Bas du visage")


if __name__ == "__main__":
    main()
