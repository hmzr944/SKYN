"""Fusion par evidence multi-dimensionnelle : remplace le seuil de
persistance binaire par un score continu, et cherche le meilleur point de
fonctionnement au lieu d'en supposer un.

────────────────────────────────────────────────────────────────────────
POURQUOI LA PERSISTANCE BINAIRE NE SUFFIT PAS.

`multiview_persistence_bench.py` a confirme que la fusion multi-vues aide
(doublons quasi nuls, faux-evenements en baisse a nombre de vues egal), mais
au prix d'un recall qui tombe de 84 % (production N=3) a ~73-75 %
(persistance, N=3/5/9). La cause : "vu dans au moins 40 % des vues" traite
un signal faible-mais-cohérent exactement comme un signal fort-mais-rare —
les deux perdent s'ils ne passent pas la barre de comptage brut, alors que
ce sont deux situations tres differentes.

Ce banc remplace donc la regle binaire par un SCORE D'EVIDENCE continu,
moyenne non ponderee (poids egaux, non calibres — voir plus bas) de cinq
dimensions :

    1. persistance          — fraction des vues qui ont vu le candidat
    2. coherence de position — les observations restent-elles proches entre
                               elles (std normalisee par le rayon
                               d'appariement), ou dérivent-elles ?
    3. coherence photometrique — le rougeur (`redness`) reste-t-il stable
                               d'une observation a l'autre (coefficient de
                               variation), ou saute-t-il ?
    4. coherence morphologique — les observations s'accordent-elles sur le
                               MEME type de lesion (proxy de forme : le
                               moteur ne renvoie pas la forme brute au-dela
                               de `_classify`, donc l'accord de type est
                               ce qui est mesurable a ce niveau) ?
    5. confiance moyenne     — la confiance heuristique native du moteur
                               (signal x plausibilite de taille), deja
                               calculee par `_confidence()`.

La "qualite des frames" demandee (5e dimension de la liste initiale) est
traitee comme une PORTE, pas un score : les vues que le controle qualite du
moteur (`Quality.usable`) juge inutilisables sont ecartees AVANT la fusion,
plutot que ponderees par un facteur invente sans etalonnage.

Cas degenere important, traite explicitement : un candidat vu une seule
fois a une coherence triviale (aucune variance calculable sur 1
observation). Lui donner 1.0 par defaut recompenserait injustement un
signal jamais confirme — ces trois dimensions de coherence valent donc 0,5
(neutre) quand moins de 2 observations existent, et c'est la persistance
elle-meme (1/N, petite pour N grand) qui porte alors la penalite.

Les poids sont EGAUX et NON CALIBRES — un choix de depart honnete, pas une
pretention d'optimalite. Plutot que de deviner un seuil d'evidence unique,
ce banc BALAIE une plage de seuils et rapporte la courbe complete —
exactement la discipline utilisee pour RED_IF_DARK : le seuil doit venir
de la mesure, pas l'inverse.

Reutilise `_verite_terrain`, `_vues_de_session`, `_evaluer`,
`_fausse_evolution` de `multiview_persistence_bench.py` a l'identique,
pour que la comparaison au producton N=3 deja mesure reste sur des bases
communes plutot que sur deux implementations paralleles.

Usage :
    python3 backend/tools/multiview_evidence_bench.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import FaceAnalysis, analyze_face, analyze_multi  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.multiview_persistence_bench import (  # noqa: E402
    LESIONS_PAR_ZONE,
    RAYON_APPARIEMENT,
    SEED_PLANT,
    ZONES_PLANTEES,
    _evaluer,
    _fausse_evolution,
    _verite_terrain,
    _vues_de_session,
)
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
SESSIONS = 8
VUES_TESTEES = [3, 5, 9]
SEUILS_EVIDENCE = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def _pistes_par_evidence(vues: List[FaceAnalysis], rayon: float) -> List[dict]:
    """Regroupe les lesions brutes de chaque vue par proximite, et calcule un
    score d'evidence continu par piste — SANS filtrer par un seuil : le
    filtrage se fait a part, pour pouvoir balayer plusieurs seuils sur les
    memes observations sans refaire tourner le moteur a chaque fois."""
    vues_ok = [v for v in vues if v.quality.get("usable", True)]
    n = len(vues_ok)
    if n == 0:
        return []

    pistes: List[dict] = []
    for v in vues_ok:
        for l in v.lesions:
            x, y = l["x"], l["y"]
            meilleur, meilleure_dist = None, rayon
            for i, p in enumerate(pistes):
                d = ((p["x"] - x) ** 2 + (p["y"] - y) ** 2) ** 0.5
                if d < meilleure_dist:
                    meilleur, meilleure_dist = i, d
            if meilleur is not None:
                p = pistes[meilleur]
                p["obs"].append(l)
                p["x"] = sum(o["x"] for o in p["obs"]) / len(p["obs"])
                p["y"] = sum(o["y"] for o in p["obs"]) / len(p["obs"])
            else:
                pistes.append({"x": x, "y": y, "obs": [l]})

    out = []
    for p in pistes:
        obs = p["obs"]
        k = len(obs)
        persistance = k / n

        if k >= 2:
            xs = [o["x"] for o in obs]
            ys = [o["y"] for o in obs]
            mx, my = sum(xs) / k, sum(ys) / k
            std_pos = (sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / k) ** 0.5
            coherence_position = max(0.0, 1.0 - std_pos / rayon)

            reds = [o["redness"] for o in obs]
            m_red = sum(reds) / k
            if m_red > 1e-6:
                ecart_type = (sum((r - m_red) ** 2 for r in reds) / k) ** 0.5
                cv = ecart_type / m_red
                coherence_photo = max(0.0, 1.0 - min(1.0, cv))
            else:
                coherence_photo = 0.5

            types = [o["type"] for o in obs]
            majoritaire = max(set(types), key=types.count)
            coherence_forme = types.count(majoritaire) / k
        else:
            coherence_position = 0.5
            coherence_photo = 0.5
            coherence_forme = 0.5

        confiance_moy = sum(o["confidence"] for o in obs) / k

        evidence = (persistance + coherence_position + coherence_photo +
                    coherence_forme + confiance_moy) / 5.0

        out.append({"x": p["x"], "y": p["y"], "evidence": evidence,
                    "persistance": persistance, "n_obs": k})
    return out


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    pts0 = _landmarks(img)
    if pts0 is None:
        raise SystemExit("aucun visage detecte sur l'image de base")

    marque = img.copy()
    plantees = []
    for zone in ZONES_PLANTEES:
        marque, p = plant(marque, pts0, zone, LESIONS_PAR_ZONE, seed=SEED_PLANT)
        plantees.extend(p)
    verite = _verite_terrain(marque, plantees)

    # Verification de plausibilite AVANT tout benchmark : la paire plantee
    # dans joue_d (17px d'ecart) fusionne-t-elle en UN SEUL blob, comme deja
    # documente dans diagnose_rotation.py ? Si oui, le recall maximum
    # atteignable par CE jeu de verite terrain n'est pas 8/8 mais 7/8 — un
    # plafond de mesure, pas une limite de la fusion evaluee plus bas.
    base_seule = analyze_face(_b64(marque))
    r_base, _, _ = _evaluer(base_seule.lesions, verite, RAYON_APPARIEMENT)
    plafond = round(r_base * len(verite))
    print(f"{len(verite)} lesions plantees, {SESSIONS} sessions, "
          f"seuils d'evidence balayes : {SEUILS_EVIDENCE}")
    print(f"recall sur l'image NON perturbee (sanity check) : {r_base:.3f} "
          f"({plafond}/{len(verite)}) — {'MOINS DE 8/8, plafond de mesure a garder en tete : ' + str(plafond) + '/' + str(len(verite)) + ' pas 8/8 (verifier une fusion de paire plantee trop proche)' if plafond < len(verite) else 'toutes separables au depart, aucun plafond de mesure connu'}\n")

    # ── Reference production N=3, recalculee dans CE run pour une comparaison
    # a tirages coherents plutot qu'un chiffre recopie d'une execution passee. ──
    prod_recalls, prod_precisions, prod_doublons, prod_sessions = [], [], [], []
    for s in range(SESSIONS):
        images = _vues_de_session(marque, 3, seed=2000 * 3 + 31 * s + 7)
        out = analyze_multi(images)
        r, p, d = _evaluer(out.lesions, verite, RAYON_APPARIEMENT)
        prod_recalls.append(r)
        prod_precisions.append(p)
        prod_doublons.append(d)
        prod_sessions.append(out.lesions)
    prod_faux_evt = [_fausse_evolution(prod_sessions[i], prod_sessions[i + 1], RAYON_APPARIEMENT)
                     for i in range(SESSIONS - 1)]
    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
    cible_recall = moy(prod_recalls)
    print(f"REFERENCE production N=3 : recall={cible_recall:.2f}  "
          f"precision={moy(prod_precisions):.2f}  doublons={moy(prod_doublons):.2f}  "
          f"faux-evt/paire={moy(prod_faux_evt):.2f}\n")

    for n in VUES_TESTEES:
        pistes_par_session = []
        for s in range(SESSIONS):
            images = _vues_de_session(marque, n, seed=2000 * n + 31 * s)
            vues = [analyze_face(im) for im in images]
            pistes_par_session.append(_pistes_par_evidence(vues, RAYON_APPARIEMENT))

        print(f"── N={n} vues ──")
        print(f"{'seuil':>6} {'recall':>7} {'precision':>10} {'doublons':>9} "
              f"{'faux-evt/paire':>15}  cible atteinte ?")
        for seuil in SEUILS_EVIDENCE:
            recalls, precisions, doublons_l = [], [], []
            filtres = []
            for pistes in pistes_par_session:
                gardees = [p for p in pistes if p["evidence"] >= seuil]
                r, p, d = _evaluer(gardees, verite, RAYON_APPARIEMENT)
                recalls.append(r)
                precisions.append(p)
                doublons_l.append(d)
                filtres.append(gardees)
            faux_evt = [_fausse_evolution(filtres[i], filtres[i + 1], RAYON_APPARIEMENT)
                       for i in range(SESSIONS - 1)]

            r_m, p_m, d_m, fe_m = moy(recalls), moy(precisions), moy(doublons_l), moy(faux_evt)
            cible = (r_m >= cible_recall - 0.01 and d_m <= 0.1 and fe_m < moy(prod_faux_evt))
            print(f"{seuil:>6.2f} {r_m:>7.2f} {p_m:>10.2f} {d_m:>9.2f} {fe_m:>15.2f}  "
                  f"{'OUI' if cible else ''}")
        print()

    print("Cible = recall >= reference production N=3, doublons <= 0,1, "
          "faux-evt/paire strictement sous la reference production. Poids de "
          "l'evidence egaux et non calibres — un seuil qui atteint la cible ici "
          "est un point de depart credible, pas une valeur a figer sans plus "
          "de sessions.")


if __name__ == "__main__":
    run()
