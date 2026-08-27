"""Banc Multi-View Capture : passer de 3 vues a plus (5, 9, capture continue)
reduit-il vraiment le taux de fausses evolutions, ou l'aggrave-t-il ?

────────────────────────────────────────────────────────────────────────
LA QUESTION POSEE, ET LA LIMITE HONNETE DE CE BANC.

L'idee proposee : une capture guidee multi-angle (type Face ID) donnerait
plusieurs observations du meme visage, et un candidat confirme sur PLUSIEURS
vues serait plus digne de confiance qu'un candidat vu une seule fois. C'est
exactement le mecanisme qui manque aujourd'hui a SKYN pour distinguer un
signal fragile d'un signal solide.

Mais attention a une chose que ce banc NE PEUT PAS tester : nous n'avons
qu'UNE seule photo de reference, prise de face. Simuler un vrai virage de
tete (grand lacet/tangage, joue qui disparait derriere le nez, peau
nouvellement visible) demanderait soit de vraies photos de profil, soit un
modele 3D du visage — aucun des deux n'est disponible ici. Ce banc simule
donc des vues "repetees" quasi-frontales avec le meme bruit de capture
naturel que `stability_bench.py` (compression, luminosite, contraste, leger
angle) — PAS une vraie diversite de pose. Il repond a une question plus
etroite mais deja utile : "le MECANISME de fusion aide-t-il a distinguer le
signal du bruit, une fois qu'on a plusieurs observations bruitees du meme
signal ?" — independamment de la question, separee, de savoir si la
capture circulaire apporterait en plus une vraie couverture anatomique
supplementaire (ca, seul un vrai jeu de vues a angles reels pourra le dire).

────────────────────────────────────────────────────────────────────────
DECOUVERTE PREALABLE, EN LISANT LE CODE AVANT DE BENCHMARKER QUOI QUE CE
SOIT (`analyze_multi` dans pipeline.py) :

La fusion multi-angle ACTUELLEMENT EN PRODUCTION ne fait PAS ce que l'idee
propose. Pour chaque zone, elle retient la vue qui y a vu le PLUS de
lesions (`sum(lesions.values())` maximal) — un maximum sur les vues, pas un
consensus. Et la confiance globale est augmentee de +0.06 par vue
SUPPLEMENTAIRE, INCONDITIONNELLEMENT — meme si les vues ne sont pas du tout
d'accord entre elles. Aucun suivi de candidat individuel entre vues n'existe
(`base.lesions`, la liste position-par-position, n'est meme pas mise a jour
par la fusion — seul `lesion_counts`, l'agregat par type, l'est). Ajouter
des vues au mecanisme ACTUEL revient donc structurellement a l'anti-motif
deja identifie par l'utilisateur ("100 detections -> 27 lesions") : plus de
vues, c'est plus de chances qu'AU MOINS UNE d'entre elles ait un pic de
bruit dans une zone donnee, et ce pic devient le nouveau maximum retenu.
C'est precisement testable, et c'est ce que ce banc mesure en premier.

────────────────────────────────────────────────────────────────────────
DEUX STRATEGIES COMPAREES, MEME DONNEES D'ENTREE.

PRODUCTION — `analyze_multi()` reel, non modifie : agregats
    lesion_counts / global_score apres fusion max-par-zone actuelle.

PROTOTYPE  — fusion par persistance construite dans CE script (pas touche a
    la production) : chaque lesion brute de chaque vue individuelle
    (`analyze_face` par vue, positions x,y normalisees) est associee a la
    piste la plus proche (rayon = tolerance d'appariement de
    `stability_bench.py`) ; une piste n'est retenue que si elle a ete vue
    dans au moins `SEUIL_PERSISTANCE` des vues. C'est le mecanisme de
    confirmation par redondance decrit dans la demande.

Metrique : sur R "sessions" independantes de N vues chacune (memes
perturbations de peau INCHANGEE, tirages differents), on compare chaque
paire de sessions consecutives comme deux visites du meme utilisateur.
Ground truth = zero evolution reelle. Tout ecart mesure EST une fausse
evolution, par construction.

Usage :
    python3 backend/tools/multiview_capture_bench.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import (  # noqa: E402
    FaceAnalysis,
    analyze_face,
    analyze_multi,
)
from backend.tools.stability_bench import PERTURBATIONS, _appareiller, _b64  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")

VUES_PAR_STRATEGIE = [1, 3, 5, 9]  # A=3 (actuel), B=5, C=9 ; D continue extrapolee
SESSIONS_PAR_N = 5
SEUIL_PERSISTANCE = 0.4
RAYON_APPARIEMENT = 0.05  # identique a stability_bench.py, meme definition de "meme lesion"


def _vues_de_session(img, n: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    images_b64 = []
    for _ in range(n):
        p = rng.choice(PERTURBATIONS)
        modifiee = p.applique(img)
        images_b64.append(_b64(modifiee, quality=p.qualite_jpeg))
    return images_b64


def _fusionner_par_persistance(vues: List[FaceAnalysis], seuil: float,
                                rayon: float) -> List[dict]:
    """Chaque lesion brute de chaque vue est associee a sa piste la plus
    proche (ou en cree une). Une piste ne survient dans le rapport final que
    si elle a ete confirmee sur au moins `seuil` des vues — le mecanisme de
    confirmation par redondance decrit dans la demande, absent de la fusion
    de production actuelle."""
    pistes: List[dict] = []
    for vue in vues:
        for l in vue.lesions:
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

    n = len(vues)
    out = []
    for p in pistes:
        persistance = len(p["obs"]) / n
        if persistance < seuil:
            continue
        types = [o["type"] for o in p["obs"]]
        type_majoritaire = max(set(types), key=types.count)
        conf = sum(o["confidence"] for o in p["obs"]) / len(p["obs"])
        out.append({"x": p["x"], "y": p["y"], "type": type_majoritaire,
                    "confidence": conf, "persistance": persistance})
    return out


def _fausse_evolution(a: List[dict], b: List[dict]) -> int:
    """Nombre de lesions apparemment nouvelles ou perdues entre deux
    sessions de la MEME peau inchangee — donc, par construction, un compte
    d'artefacts de mesure, pas d'evolution reelle."""
    appariees = _appareiller(a, b)
    perdues = sum(1 for _, n in appariees if n is None)
    retrouvees_dans_b = sum(1 for _, n in appariees if n is not None)
    nouvelles = len(b) - retrouvees_dans_b
    return perdues + nouvelles


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    if not analyze_face(_b64(img)).ok:
        raise SystemExit("visage non detecte sur l'image de reference")

    print(f"{SESSIONS_PAR_N} sessions par N, vues tirees parmi les "
          f"{len(PERTURBATIONS)} perturbations de stability_bench.py, "
          f"seuil de persistance prototype = {SEUIL_PERSISTANCE}\n")

    print(f"{'N vues':>7} | {'PRODUCTION (analyze_multi reel)':^36} | "
          f"{'PROTOTYPE (fusion par persistance)':^40}")
    print(f"{'':>7} | {'|Δscore| moy':>14} {'|Δcompte| moy':>14} {'':>6} | "
          f"{'|Δcompte| moy':>16} {'faux-evenements/paire':>22}")

    for n in VUES_PAR_STRATEGIE:
        sessions_prod = []
        sessions_proto = []
        for s in range(SESSIONS_PAR_N):
            images = _vues_de_session(img, n, seed=1000 * n + 17 * s)

            out_multi = analyze_multi(images)
            sessions_prod.append({
                "count": sum(out_multi.lesion_counts.values()),
                "score": out_multi.global_score,
            })

            vues = [analyze_face(im) for im in images]
            fused = _fusionner_par_persistance(vues, SEUIL_PERSISTANCE, RAYON_APPARIEMENT)
            sessions_proto.append(fused)

        deltas_score = [abs(sessions_prod[i + 1]["score"] - sessions_prod[i]["score"])
                        for i in range(SESSIONS_PAR_N - 1)]
        deltas_count_prod = [abs(sessions_prod[i + 1]["count"] - sessions_prod[i]["count"])
                             for i in range(SESSIONS_PAR_N - 1)]
        deltas_count_proto = [abs(len(sessions_proto[i + 1]) - len(sessions_proto[i]))
                              for i in range(SESSIONS_PAR_N - 1)]
        faux_evenements = [_fausse_evolution(sessions_proto[i], sessions_proto[i + 1])
                           for i in range(SESSIONS_PAR_N - 1)]

        moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
        print(f"{n:>7} | {moy(deltas_score):>14.2f} {moy(deltas_count_prod):>14.2f} {'':>6} | "
              f"{moy(deltas_count_proto):>16.2f} {moy(faux_evenements):>22.2f}")

    print("\n'Capture duration' n'est pas mesurable hors application (c'est un "
          "temps d'acquisition reel, pas une propriete du moteur) — volontairement "
          "absent de ce tableau plutot qu'invente.")


if __name__ == "__main__":
    run()
