"""Guided Capture Protocol v0 — orchestration reutilisable, PAS encore
branchee a la production, PAS encore d'UX.

────────────────────────────────────────────────────────────────────────
CE QUE CE MODULE EST.

Le banc precedent (`capture_protocol_bench.py`) a montre que la part
d'observations "transitoires" (un seul coup, probablement pas
reproductibles) chute de 40 % a N=3 vues a 8,3 % a N=9 vues, sur le
pipeline deja valide (tracking -> nettoyage -> purete -> vote-gate). Ce
module PACKAGE ce pipeline valide derriere une API propre et reutilisable,
plus une logique d'arret adaptatif (min 5 / cible 7 / max 9), pour qu'un
banc — et plus tard, potentiellement, l'application — puisse l'appeler
sans reimplementer la tuyauterie a chaque fois.

AUCUN changement au detecteur, a la classification, au tracking, au
nettoyage, a la purete ou au vote-gate : ce fichier reutilise les MEMES
fonctions et les MEMES seuils que tous les bancs precedents, il ne fait
qu'orchestrer leur enchainement sur un flux de frames.

────────────────────────────────────────────────────────────────────────
ARRET ADAPTATIF — logique v0, volontairement simple.

Traite les frames une par une (comme un flux). Des que le nombre de vues
UTILISABLES (qualite OK) atteint `min_vues_utiles`, compare l'ensemble des
lesions confirmees a celui d'une frame utilisable plus tot :
    - stable (aucune lesion confirmee apparue/disparue) ET
      n_vues_utilisables >= cible_vues -> ARRET "cible_atteinte_stable"
    - n_vues_utilisables == max_vues -> ARRET "max_atteint" (toujours,
      meme instable)
    - plus de frames disponibles avant l'un des deux -> ARRET
      "frames_epuisees" (dans un vrai flux, ce serait "demander une frame
      de plus", pas une fin naturelle)

Rien n'est modifie en production.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.zones import build_face_map, FaceMap  # noqa: E402
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN, SEUIL_EVIDENCE, _suivre  # noqa: E402
from backend.tools.observation_outlier_bench import (  # noqa: E402
    _decision_vote_porte,
    _dimensions,
    _nettoyer,
)
from backend.tools.per_view_recall_bench import _candidats_permissifs  # noqa: E402

RAYON_APPARIEMENT = RAYON_MATCH_ANCIEN
SEUIL_NETTOYAGE = 9.5
SEUIL_PURETE = 0.5


@dataclass
class FrameMeta:
    """Une frame recue du client. `image_b64` est la seule donnee utilisee
    par le pipeline actuel ; timestamp/orientation_hint sont conserves pour
    diagnostic/metadonnees, pas encore exploites par la logique d'arret —
    v0 ne decide que sur la stabilite des observations, pas sur un angle
    estime (aucune estimation d'angle fiable n'existe encore dans ce
    projet)."""
    image_b64: str
    timestamp: Optional[float] = None
    orientation_hint: Optional[str] = None


@dataclass
class ScanConfig:
    min_vues_utiles: int = 5
    cible_vues: int = 7
    max_vues: int = 9


@dataclass
class ScanResult:
    lesions_confirmees: List[dict]
    n_vues_recues: int
    n_vues_utilisables: int
    raison_arret: str
    n_pistes_brutes: int


def _frame_utilisable(image_b64: str):
    """Detection + qualite + candidats de PRODUCTION (k=1,00) pour une
    frame. Retourne None si le visage n'est pas exploitable."""
    fm = build_face_map(image_b64)
    if not fm.detected or not fm.quality.usable:
        return None
    return _candidats_permissifs(fm, 1.00)


def _confirmer(vues_candidats: List[List[dict]]):
    """Le pipeline valide, inchange : tracking -> nettoyage -> purete ->
    vote-gate, exactement les memes fonctions et seuils que
    `track_clean_purity_bench.py` / `capture_protocol_bench.py`. Retourne
    (lesions_confirmees, nombre_de_pistes_brutes)."""
    if not vues_candidats:
        return [], 0
    n_ok = len(vues_candidats)
    pistes_brutes = _suivre(vues_candidats, RAYON_APPARIEMENT)
    confirmees = []
    for p in pistes_brutes:
        obs = _nettoyer(p["obs"], SEUIL_NETTOYAGE)
        dims = _dimensions(obs, n_ok, RAYON_APPARIEMENT)
        if dims["evidence"] < SEUIL_EVIDENCE or dims["coherence_photo"] < SEUIL_PURETE:
            continue
        _, etat = _decision_vote_porte(obs)
        if etat == "CONFIRMEE":
            k = len(obs)
            confirmees.append({"x": sum(o["x"] for o in obs) / k, "y": sum(o["y"] for o in obs) / k})
    return confirmees, len(pistes_brutes)


def _memes_positions(a: List[dict], b: List[dict], rayon: float) -> bool:
    """Deux ensembles de positions confirmees sont "les memes" si chaque
    point de l'un trouve un correspondant dans l'autre, et vice versa —
    ni apparition ni disparition."""
    if len(a) != len(b):
        return False
    dispo = list(range(len(b)))
    for pa in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            d = ((pa["x"] - b[i]["x"]) ** 2 + (pa["y"] - b[i]["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is None:
            return False
        dispo.remove(meilleur)
    return True


def orchestrer_scan(frames: List[FrameMeta], config: ScanConfig = ScanConfig()) -> ScanResult:
    """Traite les frames une par une (simule un flux) et applique l'arret
    adaptatif min/cible/max. Retourne le resultat confirme et pourquoi le
    scan s'est arrete."""
    vues_utilisables: List[List[dict]] = []
    confirmees_precedentes: Optional[List[dict]] = None
    n_pistes_brutes = 0

    for i, frame in enumerate(frames):
        cands = _frame_utilisable(frame.image_b64)
        if cands is None:
            continue
        vues_utilisables.append(cands)
        n = len(vues_utilisables)

        if n >= config.max_vues:
            confirmees, n_pistes_brutes = _confirmer(vues_utilisables)
            return ScanResult(confirmees, i + 1, n, "max_atteint", n_pistes_brutes)

        if n >= config.min_vues_utiles:
            confirmees, n_pistes_brutes = _confirmer(vues_utilisables)
            if (n >= config.cible_vues and confirmees_precedentes is not None
                    and _memes_positions(confirmees, confirmees_precedentes, RAYON_APPARIEMENT)):
                return ScanResult(confirmees, i + 1, n, "cible_atteinte_stable", n_pistes_brutes)
            confirmees_precedentes = confirmees

    # Frames epuisees avant d'atteindre une condition d'arret propre.
    if vues_utilisables:
        confirmees, n_pistes_brutes = _confirmer(vues_utilisables)
    else:
        confirmees = []
    return ScanResult(confirmees, len(frames), len(vues_utilisables), "frames_epuisees", n_pistes_brutes)


if __name__ == "__main__":
    # Auto-test minimal : verifie que le module s'importe et s'execute sur
    # l'image de reference, sans pretendre etre un banc complet (voir
    # capture_protocol_v0_bench.py pour la mesure serieuse).
    import cv2
    from backend.tools.per_view_recall_bench import _vues_de_session  # noqa: E402

    img = cv2.imread("backend/tests/fixtures_face.jpg")
    if img is None:
        raise SystemExit("image de reference introuvable")
    images = _vues_de_session(img, 9, seed=1)
    frames = [FrameMeta(image_b64=im) for im in images]
    resultat = orchestrer_scan(frames)
    print(f"auto-test : {resultat.n_vues_recues} frames recues, "
          f"{resultat.n_vues_utilisables} utilisables, "
          f"arret={resultat.raison_arret}, "
          f"{len(resultat.lesions_confirmees)} lesions confirmees "
          f"(sur {resultat.n_pistes_brutes} pistes brutes)")
