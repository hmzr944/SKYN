"""Banc de STABILITE DE MESURE : meme peau, capture legerement differente.

────────────────────────────────────────────────────────────────────────
CE QUE CE BANC MESURE, ET POURQUOI IL EXISTE.

Le banc `synth_lesions.py` repond a « le moteur retrouve-t-il les lesions
qu'on lui montre ? ». Celui-ci repond a une question differente, et pour
SKYN plus importante : « si RIEN n'a change sur la peau, le moteur le
sait-il ? ».

Une application de suivi cutane vend une comparaison dans le temps. Si une
photo prise deux fois de suite, dans des conditions plausiblement
differentes (compression du telephone, luminosite de la salle de bain,
angle de prise legerement autre), produit des scores ou des comptes de
lesions differents, l'ecart de mesure se confond avec une vraie evolution
de la peau — et c'est precisement ce que l'utilisateur est venu verifier.

La premiere mesure de cette famille (un seul niveau de recompression JPEG,
verrouillee dans `test_stable_under_jpeg_recompression`) a deja trouve un
ecart de 4 points de score et d'une lesion sur un cas. Ce banc genere la
meme famille de perturbations que celles listees pour l'auditer serieusement
— qualite JPEG, luminosite, contraste, bruit, rotation, translation, recadrage
— et mesure, pour chacune, a quel point le RESULTAT bouge alors que la peau,
elle, n'a pas bouge d'un pixel.

Ce banc NE PROPOSE AUCUN SEUIL DE STABILITE. Les seuils doivent venir de
cette mesure, pas l'inverse — les inventer avant d'avoir les chiffres serait
exactement l'erreur que ce projet a deja pris soin d'eviter ailleurs.

Usage :
    python3 backend/tools/stability_bench.py
"""
from __future__ import annotations

import base64
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import FaceAnalysis, analyze_face  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")

# Rayon d'appariement, en fraction de la plus grande dimension de la boite du
# visage : deux lesions sont "la meme" si leurs positions normalisees restent
# a moins de cette distance l'une de l'autre d'une capture a l'autre.
APPARIEMENT = 0.05


def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


# --------------------------------------------------------------------------
# Les perturbations. Chacune modifie l'image, PAS la peau : aucune n'ajoute
# ni ne retire de lesion, aucune ne change la personne photographiee.
# --------------------------------------------------------------------------
@dataclass
class Perturbation:
    nom: str
    applique: Callable[[np.ndarray], np.ndarray]
    qualite_jpeg: int = 95  # sauf pour les perturbations QUI SONT la qualite


def _luminosite(delta: int) -> Callable[[np.ndarray], np.ndarray]:
    def f(img: np.ndarray) -> np.ndarray:
        return np.clip(img.astype(np.int16) + delta, 0, 255).astype(np.uint8)
    return f


def _contraste(facteur: float) -> Callable[[np.ndarray], np.ndarray]:
    def f(img: np.ndarray) -> np.ndarray:
        moy = img.astype(np.float32).mean()
        out = (img.astype(np.float32) - moy) * facteur + moy
        return np.clip(out, 0, 255).astype(np.uint8)
    return f


def _bruit(sigma: float, seed: int) -> Callable[[np.ndarray], np.ndarray]:
    def f(img: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(seed)
        bruit = rng.normal(0, sigma, img.shape)
        return np.clip(img.astype(np.float32) + bruit, 0, 255).astype(np.uint8)
    return f


def _rotation(deg: float) -> Callable[[np.ndarray], np.ndarray]:
    def f(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return f


def _translation(dx: int, dy: int) -> Callable[[np.ndarray], np.ndarray]:
    def f(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return f


def _recadrage(pct: float) -> Callable[[np.ndarray], np.ndarray]:
    """Retire `pct` de chaque bord puis redimensionne a la taille d'origine —
    un leger zoom, comme un cadrage un peu plus serre au meme telephone."""
    def f(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        mx, my = int(w * pct), int(h * pct)
        crop = img[my:h - my, mx:w - mx]
        return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)
    return f


def _identite(img: np.ndarray) -> np.ndarray:
    return img


PERTURBATIONS: List[Perturbation] = [
    Perturbation("jpeg_q100", _identite, qualite_jpeg=100),
    Perturbation("jpeg_q95", _identite, qualite_jpeg=95),
    Perturbation("jpeg_q90", _identite, qualite_jpeg=90),
    Perturbation("jpeg_q85", _identite, qualite_jpeg=85),
    Perturbation("jpeg_q75", _identite, qualite_jpeg=75),
    Perturbation("jpeg_q60", _identite, qualite_jpeg=60),
    Perturbation("luminosite_+15", _luminosite(15)),
    Perturbation("luminosite_-15", _luminosite(-15)),
    Perturbation("contraste_+15%", _contraste(1.15)),
    Perturbation("contraste_-15%", _contraste(0.85)),
    Perturbation("bruit_leger", _bruit(4.0, seed=1)),
    Perturbation("rotation_+2deg", _rotation(2.0)),
    Perturbation("rotation_-2deg", _rotation(-2.0)),
    Perturbation("translation_5px", _translation(5, 3)),
    Perturbation("recadrage_3%", _recadrage(0.03)),
]


# --------------------------------------------------------------------------
def _appareiller(ref: List[dict], nouveau: List[dict]) -> List[Tuple[dict, Optional[dict]]]:
    """Associe chaque lesion de reference a sa plus proche voisine dans le
    nouveau rapport, sans qu'une meme lesion nouvelle ne serve deux fois."""
    dispo = list(range(len(nouveau)))
    out = []
    for r in ref:
        meilleur, meilleure_dist = None, APPARIEMENT
        for i in dispo:
            n = nouveau[i]
            d = ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            out.append((r, nouveau[meilleur]))
            dispo.remove(meilleur)
        else:
            out.append((r, None))
    return out


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")

    base = analyze_face(_b64(img, quality=100))
    if not base.ok:
        raise SystemExit("visage non detecte sur l'image de reference")

    print(f"REFERENCE : score={base.global_score}  lesions={len(base.lesions)}  "
          f"zones_notees={len(base.zone_scores)}")
    print(f"  types : {[l['type'] for l in base.lesions]}")
    print(f"  zones : {[l['zone'] for l in base.lesions]}\n")

    lignes = []
    for p in PERTURBATIONS:
        modifiee = p.applique(img)
        out = analyze_face(_b64(modifiee, quality=p.qualite_jpeg))
        if not out.ok:
            lignes.append((p.nom, None))
            continue

        score_delta = out.global_score - base.global_score
        n_delta = len(out.lesions) - len(base.lesions)

        appariees = _appareiller(base.lesions, out.lesions)
        derives = [
            ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            for r, n in appariees if n is not None
        ]
        non_retrouvees = sum(1 for _, n in appariees if n is None)
        type_change = sum(1 for r, n in appariees if n is not None and n["type"] != r["type"])
        zone_change = sum(1 for r, n in appariees if n is not None and n["zone"] != r["zone"])

        lignes.append((p.nom, {
            "score_delta": score_delta,
            "n_delta": n_delta,
            "n_lesions": len(out.lesions),
            "derive_moy": (sum(derives) / len(derives)) if derives else 0.0,
            "derive_max": max(derives) if derives else 0.0,
            "non_retrouvees": non_retrouvees,
            "type_change": type_change,
            "zone_change": zone_change,
        }))

    print(f"{'perturbation':<18} {'score':>7} {'lesions':>9} {'derive_px':>11} "
          f"{'perdues':>9} {'type':>6} {'zone':>6}")
    for nom, r in lignes:
        if r is None:
            print(f"{nom:<18}  ECHEC (visage non detecte apres perturbation)")
            continue
        print(f"{nom:<18} {r['score_delta']:>+7} {r['n_lesions']:>5}({r['n_delta']:>+3}) "
              f"{r['derive_moy']:>7.3f}/{r['derive_max']:<3.2f} "
              f"{r['non_retrouvees']:>9} {r['type_change']:>6} {r['zone_change']:>6}")

    valides = [r for _, r in lignes if r is not None]
    scores = [r["score_delta"] for r in valides]
    print(f"\nSCORE   : ecart min={min(scores):+d}  max={max(scores):+d}  "
          f"|ecart| moyen={sum(abs(s) for s in scores) / len(scores):.1f}")
    print(f"LESIONS PERDUES (sur {len(base.lesions)} de reference) : "
          f"{sum(r['non_retrouvees'] for r in valides)} occurrences sur {len(valides)} perturbations")
    print(f"CHANGEMENTS DE TYPE : {sum(r['type_change'] for r in valides)}")
    print(f"CHANGEMENTS DE ZONE : {sum(r['zone_change'] for r in valides)}")


if __name__ == "__main__":
    run()
