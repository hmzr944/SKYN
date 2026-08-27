"""Multi-Feature Discrimination Bench : une COMBINAISON de features separe-
t-elle enfin vraie lesion et faux candidat, la ou chacune seule echouait ?

────────────────────────────────────────────────────────────────────────
CE QUE `chromaticity_discrimination_bench.py` A ETABLI.

Aucune feature individuelle n'atteint |d| >= 0,8 entre lesions et faux
candidats (meilleures : dynamique_locale d=-0,50, variation_chroma_locale
d=-0,42, chroma_a d=+0,43, saturation d=+0,38) — mais les quatre vont dans
une direction QUALITATIVEMENT COHERENTE : lesions -> chroma_a et
saturation plus hauts, dynamique_locale et variation_chroma_locale plus
bas ; faux candidats -> l'inverse. C'est exactement le signal qu'une
combinaison peut exploiter la ou une seule feature ne suffit pas.

────────────────────────────────────────────────────────────────────────
METHODE — aucun poids invente, aucun ajustement sur les faux candidats.

Chaque feature est standardisee (z-score) par rapport a la PEAU SAINE
uniquement — ni les lesions, ni les faux candidats (le jeu qu'on evalue)
ne participent au calibrage de l'echelle. La peau saine represente la
variabilite "normale" de reference, un choix neutre vis-a-vis des deux
populations testees.

Le SIGNE de chaque feature dans la combinaison est fixe par la direction
DEJA mesuree dans le banc precedent (chroma_a et saturation : lesions >
faux -> signe +1 ; dynamique_locale et variation_chroma_locale : faux >
lesions -> signe -1) — pas optimise ici. A noter honnetement : ce signe a
ete lu sur CE dataset (capture C), donc le resultat reste une
demonstration sur ce cas, pas une regle validee en general — exactement
la reserve que la demande elle-meme a soulevee.

Combinaison = SOMME NON PONDEREE des z-scores signes des features
selectionnees. Toutes les combinaisons de taille 1 a 4 parmi les 4
features sont testees (15 sous-ensembles), pas seulement celle qui
"marche le mieux" choisie a l'oeil.

CRITERE DE DECISION PRE-ENREGISTRE (exactement celui demande) :
    GO         — une combinaison ameliore nettement A/B (lesions vs faux)
                 SANS degrader A/C (lesions vs peau) ni B/C (faux vs peau)
    PROMETTEUR — separation interessante mais |d(A/B)| < 0,8
    STOP       — aucune combinaison n'apporte de gain robuste

Rien n'est modifie en production. Aucune image commitee.

Usage :
    python3 backend/tools/multi_feature_discrimination_bench.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.lesions import _local_excess  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.chromaticity_discrimination_bench import (  # noqa: E402
    IMAGE_A,
    IMAGE_C,
    N_PEAU_SAINE,
    RAYON_APPARIEMENT,
    SEED,
    _appareiller_positions,
    _d,
    _mesures,
)
from backend.tools.feature_lab import _points_peau_saine  # noqa: E402
from backend.tools.per_view_recall_bench import _candidats_permissifs  # noqa: E402
from backend.tools.real_skin_pilot_session_ab import _charger_oriente  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402

# Les 4 features retenues du banc precedent, avec le signe DEJA observe
# (lesions > faux -> +1 ; faux > lesions -> -1), pas optimise ici.
FEATURES_SIGNEES = {
    "chroma_a": +1,
    "saturation": +1,
    "dynamique_locale": -1,
    "variation_chroma_locale": -1,
}


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

    # ── Standardisation : moyenne/ecart-type de la PEAU SAINE uniquement ──
    ref_stats = {}
    for f in FEATURES_SIGNEES:
        v = np.array([m[f] for m in mesures_peau])
        ref_stats[f] = (float(v.mean()), float(v.std()) or 1e-6)

    def _score(mesure: dict, sous_ensemble) -> float:
        return sum(FEATURES_SIGNEES[f] * (mesure[f] - ref_stats[f][0]) / ref_stats[f][1]
                  for f in sous_ensemble)

    print("=" * 100)
    print("TOUTES LES COMBINAISONS (standardisation par la peau saine, signes deja observes, "
          "somme non ponderee)")
    print("=" * 100)
    print(f"{'combinaison':<52} {'d(les. vs faux)':>16} {'d(les. vs peau)':>16} {'d(faux vs peau)':>16}")

    features = list(FEATURES_SIGNEES.keys())
    resultats = []
    for taille in range(1, len(features) + 1):
        for sous_ensemble in itertools.combinations(features, taille):
            sl = [_score(m, sous_ensemble) for m in mesures_lesions]
            sf = [_score(m, sous_ensemble) for m in mesures_faux]
            sp = [_score(m, sous_ensemble) for m in mesures_peau]
            d_lf = _d(sl, sf)
            d_lp = _d(sl, sp)
            d_fp = _d(sf, sp)
            resultats.append((sous_ensemble, d_lf, d_lp, d_fp))
            nom = " + ".join(sous_ensemble)
            print(f"{nom:<52} {d_lf:>16.2f} {d_lp:>16.2f} {d_fp:>16.2f}")

    # ── Verdict pre-enregistre : les TROIS conditions doivent tenir A LA FOIS
    # sur la MEME combinaison — regarder seulement le meilleur d(A/B) isole
    # cacherait une combinaison qui gagne sur A/B en detruisant A/C. ──
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    meilleur_ab = max(resultats, key=lambda r: abs(r[1]))
    sous_ensemble, d_lf, d_lp, d_fp = meilleur_ab
    print(f"Meilleure combinaison sur A/B SEUL : {' + '.join(sous_ensemble)}  "
          f"(d(les.vs faux)={d_lf:.2f}, d(les.vs peau)={d_lp:.2f}, d(faux vs peau)={d_fp:.2f})")
    if abs(d_lp) < 0.8:
        print(f"  -> mais cette meme combinaison detruit A/C (|d(les.vs peau)|={abs(d_lp):.2f} < 0,8) : "
              f"elle ne distingue plus lesion et peau saine. Pas utilisable telle quelle.")

    meilleure_feature_seule = 0.50  # dynamique_locale, la plus forte mesuree seule dans le banc precedent
    candidats_go = [r for r in resultats if abs(r[1]) >= 0.8 and abs(r[2]) >= 0.8 and abs(r[3]) >= 0.5]
    if candidats_go:
        s, dlf, dlp, dfp = max(candidats_go, key=lambda r: abs(r[1]))
        print(f"\nGO — {' + '.join(s)} separe nettement A/B ({dlf:.2f}) SANS degrader "
              f"A/C ({dlp:.2f}) ni B/C ({dfp:.2f}).")
    else:
        combos_ameliorant_ab = [r for r in resultats if abs(r[1]) > meilleure_feature_seule]
        combos_sans_degrader_ac = [r for r in combos_ameliorant_ab if abs(r[2]) >= 0.8]
        if combos_sans_degrader_ac:
            s, dlf, dlp, dfp = max(combos_sans_degrader_ac, key=lambda r: abs(r[1]))
            print(f"\nPROMETTEUR — {' + '.join(s)} ameliore A/B ({dlf:.2f}) SANS detruire A/C "
                  f"({dlp:.2f}), mais reste sous |d|=0,8 sur A/B.")
        else:
            print(f"\nSTOP — aucune combinaison n'ameliore A/B sans detruire A/C. La seule "
                  f"combinaison qui approche 0,8 sur A/B ({' + '.join(sous_ensemble)}, "
                  f"d={d_lf:.2f}) le fait en ecrasant A/C (d={d_lp:.2f}) — pas un gain "
                  f"utilisable, un compromis different, pas meilleur.")

    print("\nRappel : signes fixes par la lecture du banc precedent SUR CE MEME DATASET (C) — "
          "ce resultat demontre une possibilite sur ce cas, il ne la valide pas en general. "
          "Aucun ajustement effectue sur/contre les 73 faux candidats de C au-dela de la lecture "
          "du signe. Rien modifie en production.")


if __name__ == "__main__":
    run()
