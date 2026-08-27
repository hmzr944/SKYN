"""Banc reproductible : fusion par persistance vs `analyze_multi()` actuel,
avec verite terrain, precision/recall, doublons et cout CPU.

────────────────────────────────────────────────────────────────────────
CE QUI CHANGE PAR RAPPORT A `multiview_capture_bench.py`.

Ce premier prototype mesurait la stabilite meme-peau sur les vraies lesions
(ambigues) de la photo de reference — utile pour la question "le mecanisme
aide-t-il ?", mais sans verite terrain il ne pouvait pas repondre a
precision/recall ni compter des doublons proprement. Ce banc plante des
lesions a des positions CONNUES (comme `synth_lesions.py`) pour pouvoir
mesurer :

    recall      — fraction des lesions plantees retrouvees
    precision   — fraction des lesions rapportees qui correspondent a une vraie
    doublons    — une meme lesion plantee rapportee plusieurs fois (sur-
                  segmentation), plutot qu'un vrai second signal
    faux-evenements — lesions qui apparaissent/disparaissent entre deux
                  sessions de la MEME peau plantee (deja mesure precedemment,
                  repris ici avec verite terrain en plus)
    cout CPU    — temps CPU (process_time) du traitement moteur par session

Groupes compares, exactement ceux demandes :
    A — 3 vues, `analyze_multi()` production (non modifie)
    B — 3 vues, fusion par persistance (prototype)
    C — 5 vues, fusion par persistance
    D — 9 vues, fusion par persistance
Le groupe A a une seule vue (N=1, sans fusion) reste imprime en reference,
comme dans le banc precedent.

LIMITE ASSUMEE, memes raisons que le banc precedent : une seule photo de
reference, donc pas de vraie diversite de pose (yaw/pitch) — seulement des
vues quasi-frontales avec le bruit de capture de `stability_bench.py`
(dont 2 perturbations geometriques : rotation +-2 deg, translation 5px,
recadrage 3%).

LIMITE DE MESURE ADDITIONNELLE, propre a ce banc : la position "verite
terrain" de chaque lesion plantee est calculee UNE FOIS sur l'image non
perturbee (coordonnees normalisees par sa boite de visage), puis comparee
telle quelle aux positions rapportees sur CHAQUE vue perturbee — sans
recalcul analytique par type de perturbation. Le rayon d'appariement
(0,05, identique a `stability_bench.py`) est concu pour absorber exactement
ce type de derive (deja mesuree ailleurs dans ce projet comme bien
inferieure a ce rayon pour ces memes perturbations) ; ce n'est donc pas une
approximation nouvelle, mais elle merite d'etre nommee plutot que supposee.

Le "temps de scan" demande est le temps de CAPTURE reel par l'utilisateur —
ca depend de l'appareil et du guidage UX, ce banc ne peut pas le mesurer
hors application. Il rapporte a la place le temps de TRAITEMENT moteur
(CPU), qui est la seule des deux composantes que du code hors-ligne peut
honnetement chiffrer.

Usage :
    python3 backend/tools/multiview_persistence_bench.py
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import (  # noqa: E402
    FaceAnalysis,
    analyze_face,
    analyze_multi,
)
from backend.tools.stability_bench import PERTURBATIONS, _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
ZONES_PLANTEES = ("joue_g", "joue_d", "front", "menton")
LESIONS_PAR_ZONE = 2
SEED_PLANT = 5

SESSIONS = 8
RAYON_APPARIEMENT = 0.05
SEUIL_PERSISTANCE = 0.4

# Exactement les 4 groupes demandes, plus N=1 comme reference deja etablie.
GROUPES = [
    ("N=1 (reference, sans fusion)", 1, "prod"),
    ("A: N=3 production (analyze_multi reel)", 3, "prod"),
    ("B: N=3 persistance", 3, "persist"),
    ("C: N=5 persistance", 5, "persist"),
    ("D: N=9 persistance", 9, "persist"),
]


def _verite_terrain(marque: np.ndarray, plantees) -> List[Tuple[float, float]]:
    base = analyze_face(_b64(marque, quality=100))
    if not base.ok:
        raise SystemExit("visage non detecte sur l'image plantee (non perturbee)")
    fb = base.face_box
    return [((p.x - fb["x"]) / fb["w"], (p.y - fb["y"]) / fb["h"]) for p in plantees]


def _vues_de_session(marque: np.ndarray, n: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    return [_b64(p.applique(marque), quality=p.qualite_jpeg)
            for p in (rng.choice(PERTURBATIONS) for _ in range(n))]


def _fusionner_par_persistance(vues: List[FaceAnalysis], seuil: float,
                                rayon: float) -> List[dict]:
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
    return [{"x": p["x"], "y": p["y"], "persistance": len(p["obs"]) / n}
            for p in pistes if len(p["obs"]) / n >= seuil]


def _evaluer(rapportees: List[dict], verite: List[Tuple[float, float]], rayon: float):
    """Precision/recall/doublons par appariement au plus proche verite —
    volontairement PAS d'appariement bijectif : une meme verite matchee par
    plusieurs lesions rapportees est exactement ce qu'on veut compter comme
    doublon, pas masquer."""
    matches = [0] * len(verite)
    faux_positifs = 0
    for r in rapportees:
        meilleur, meilleure_dist = None, rayon
        for i, (vx, vy) in enumerate(verite):
            d = ((r["x"] - vx) ** 2 + (r["y"] - vy) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            matches[meilleur] += 1
        else:
            faux_positifs += 1
    recall = sum(1 for m in matches if m > 0) / len(verite) if verite else 0.0
    precision = ((len(rapportees) - faux_positifs) / len(rapportees)) if rapportees else 1.0
    doublons = sum(max(0, m - 1) for m in matches)
    return recall, precision, doublons


def _fausse_evolution(a: List[dict], b: List[dict], rayon: float) -> int:
    dispo = list(range(len(b)))
    perdues = 0
    for r in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            n = b[i]
            d = ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            dispo.remove(meilleur)
        else:
            perdues += 1
    nouvelles = len(dispo)
    return perdues + nouvelles


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
    print(f"{len(verite)} lesions plantees ({', '.join(ZONES_PLANTEES)}) "
          f"comme verite terrain, {SESSIONS} sessions par groupe\n")

    print(f"{'groupe':<40} {'recall':>7} {'precision':>10} {'doublons':>9} "
          f"{'faux-evt/paire':>15} {'CPU s/session':>14}")

    for nom, n, mode in GROUPES:
        recalls, precisions, doublons_l, cpu_l = [], [], [], []
        rapports_sessions = []
        for s in range(SESSIONS):
            images = _vues_de_session(marque, n, seed=2000 * n + 31 * s + (7 if mode == "prod" else 0))

            t0 = time.process_time()
            if mode == "prod":
                out = analyze_multi(images) if n > 1 else analyze_face(images[0])
                rapportees = out.lesions
            else:
                vues = [analyze_face(im) for im in images]
                rapportees = _fusionner_par_persistance(vues, SEUIL_PERSISTANCE, RAYON_APPARIEMENT)
            cpu_l.append(time.process_time() - t0)

            r, p, d = _evaluer(rapportees, verite, RAYON_APPARIEMENT)
            recalls.append(r)
            precisions.append(p)
            doublons_l.append(d)
            rapports_sessions.append(rapportees)

        faux_evt = [_fausse_evolution(rapports_sessions[i], rapports_sessions[i + 1], RAYON_APPARIEMENT)
                   for i in range(SESSIONS - 1)]

        moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
        print(f"{nom:<40} {moy(recalls):>7.2f} {moy(precisions):>10.2f} "
              f"{moy(doublons_l):>9.2f} {moy(faux_evt):>15.2f} {moy(cpu_l):>14.3f}")

    print("\nNote : le groupe 'production' n'evalue que `base.lesions`, la liste "
          "de la SEULE vue la plus frontale — `analyze_multi()` ne fusionne pas "
          "les positions individuelles (voir multiview_capture_bench.py). Le "
          "'temps de scan' (capture reelle utilisateur) n'est pas mesurable "
          "hors application ; seul le temps CPU du traitement moteur est rapporte.")


if __name__ == "__main__":
    run()
