"""Capture Protocol Prototype : le scan guide (plus de vues) ameliore-t-il
la REPRODUCTIBILITE — pas seulement le recall — d'une session a l'autre ?

────────────────────────────────────────────────────────────────────────
LIMITE STRUCTURELLE, A REDIRE ICI CAR ELLE COMPTE PLUS QUE JAMAIS.

Le protocole demande evoque des angles reels (15/30/45/60 degres). Ca ne
peut PAS etre simule fidelement a partir d'une seule photo 2D — deja
etabli dans `multiview_capture_bench.py` au debut de ce chantier : un vrai
virage de tete revele de la peau differemment occultee/eclairee, une
information qu'un warp affine 2D ne peut pas inventer. Ce que ce script
teste reste donc ce qui est honnetement testable : PLUS d'observations
quasi-frontales avec le bruit de capture deja calibre (rotation +-2°,
JPEG, luminosite, contraste — le meme jeu que `stability_bench.py`), pas
une vraie couverture angulaire 15-60°. C'est une question plus etroite
que celle posee, mais c'est la seule a laquelle ce jeu de donnees permet
de repondre honnetement.

────────────────────────────────────────────────────────────────────────
NOUVELLE METRIQUE : CAPTURE REPRODUCIBILITY.

Pas seulement "combien de lesions" par session — combien de PISTES
RESTENT LES MEMES d'une session a l'autre. Pour un N de vues donne, R
sessions independantes (memes tirages de bruit, meme peau) sont chacune
passees dans le pipeline valide (tracking -> nettoyage -> purete ->
vote-gate — TOUS les seuils fixes, inchanges depuis les bancs precedents).
Les positions confirmees de CHAQUE session sont ensuite regroupees ENTRE
sessions (meme logique d'appariement que partout ailleurs), formant des
"meta-pistes". Pour chaque meta-piste :
    persistance = nombre de sessions ou elle apparait / R
Rapporte : persistance moyenne, part des meta-pistes stables (>= la
moitie des sessions), part des meta-pistes transitoires (une seule
session — potentiellement un artefact, pas une vraie observation
recurrente).

Teste sur DEUX terrains, comme la demande le suggere implicitement :
    1. verite terrain synthetique (8 lesions plantees, plafond connu 7/8)
       -> recall/precision/doublons/faux-evt EN PLUS de la reproductibilite
    2. la photo reelle du pilote (capture_001.jpg, seule photo "propre"
       sans le facteur appareil confondu identifie dans le pilote) ->
       reproductibilite seule, pas de verite terrain sur une vraie photo

Variantes testees : N=3 (scan actuel) / N=7 (guide, demande) / N=9 (deja
teste dans les bancs precedents, garde comme point de repere).

Aucun changement au detecteur, aucun nouveau seuil, aucun changement au
tracking/nettoyage/purete/vote-gate. Rien modifie en production.

Usage :
    python3 backend/tools/capture_protocol_bench.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.multiview_persistence_bench import (  # noqa: E402
    LESIONS_PAR_ZONE,
    SEED_PLANT,
    ZONES_PLANTEES,
)
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN, SEUIL_EVIDENCE, _suivre  # noqa: E402
from backend.tools.observation_outlier_bench import (  # noqa: E402
    _decision_vote_porte,
    _dimensions,
    _nettoyer,
)
from backend.tools.per_view_recall_bench import (  # noqa: E402
    _candidats_permissifs,
    _evaluer,
    _fausse_evolution,
    _vues_de_session,
)
from backend.tools.real_skin_pilot_session_ab import _charger_oriente  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

DOSSIER_PILOTE = Path("/home/user/real_skin_pilot/subject_001")
IMAGE_SYNTH = Path("backend/tests/fixtures_face.jpg")
IMAGE_REELLE = DOSSIER_PILOTE / "capture_001.jpg"

R_SESSIONS = 6
N_VUES = [3, 7, 9]
SEUIL_NETTOYAGE = 9.5
SEUIL_PURETE = 0.5
RAYON_REGROUPEMENT_INTER_SESSION = 0.08


def _session_confirmees(img, n: int, seed_base: int) -> List[dict]:
    images = _vues_de_session(img, n, seed=seed_base)
    vues_candidats = []
    for im in images:
        fm = build_face_map(im)
        if not fm.detected or not fm.quality.usable:
            continue
        vues_candidats.append(_candidats_permissifs(fm, 1.00))
    if not vues_candidats:
        return []
    n_ok = len(vues_candidats)
    pistes_brutes = _suivre(vues_candidats, RAYON_MATCH_ANCIEN)
    confirmees = []
    for p in pistes_brutes:
        obs = _nettoyer(p["obs"], SEUIL_NETTOYAGE)
        dims = _dimensions(obs, n_ok, RAYON_MATCH_ANCIEN)
        if dims["evidence"] < SEUIL_EVIDENCE or dims["coherence_photo"] < SEUIL_PURETE:
            continue
        _, etat = _decision_vote_porte(obs)
        if etat == "CONFIRMEE":
            k = len(obs)
            confirmees.append({"x": sum(o["x"] for o in obs) / k, "y": sum(o["y"] for o in obs) / k})
    return confirmees


def _reproductibilite(sessions_confirmees: List[List[dict]], rayon: float) -> dict:
    """Regroupe les positions confirmees ENTRE sessions (meme peau, memes
    positions attendues) pour mesurer combien de "meta-pistes" persistent
    d'une session a l'autre, plutot que de ne comparer que des comptes."""
    meta_pistes: List[dict] = []
    for i, confirmees in enumerate(sessions_confirmees):
        for c in confirmees:
            meilleur, meilleure_dist = None, rayon
            for j, mp in enumerate(meta_pistes):
                d = ((mp["x"] - c["x"]) ** 2 + (mp["y"] - c["y"]) ** 2) ** 0.5
                if d < meilleure_dist:
                    meilleur, meilleure_dist = j, d
            if meilleur is not None:
                mp = meta_pistes[meilleur]
                mp["sessions"].add(i)
                mp["obs"].append(c)
                mp["x"] = sum(o["x"] for o in mp["obs"]) / len(mp["obs"])
                mp["y"] = sum(o["y"] for o in mp["obs"]) / len(mp["obs"])
            else:
                meta_pistes.append({"x": c["x"], "y": c["y"], "sessions": {i}, "obs": [c]})

    r = len(sessions_confirmees)
    persistances = [len(mp["sessions"]) / r for mp in meta_pistes]
    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
    stables = sum(1 for p in persistances if p >= 0.5)
    transitoires = sum(1 for p in persistances if p <= 1 / r + 1e-9)
    return {
        "n_meta_pistes": len(meta_pistes),
        "persistance_moyenne": moy(persistances),
        "part_stable": stables / len(meta_pistes) if meta_pistes else 0.0,
        "part_transitoire": transitoires / len(meta_pistes) if meta_pistes else 0.0,
    }


def run() -> None:
    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

    # ══════════════════════════════════════════════════════════════════
    # 1. Terrain synthetique (verite terrain connue)
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("1. TERRAIN SYNTHETIQUE (8 lesions plantees, plafond connu 7/8)")
    print("=" * 100)
    img = cv2.imread(str(IMAGE_SYNTH))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE_SYNTH}")
    pts0 = _landmarks(img)
    marque = img.copy()
    plantees = []
    for zone in ZONES_PLANTEES:
        marque, p = plant(marque, pts0, zone, LESIONS_PAR_ZONE, seed=SEED_PLANT)
        plantees.extend(p)
    base = build_face_map(_b64(marque, quality=100))
    x0, y0, bw, bh = base.bbox
    verite_xy = [((p.x - x0) / bw, (p.y - y0) / bh) for p in plantees]

    print(f"{'N vues':>7} {'recall':>7} {'rec.detect(/7)':>15} {'precision':>10} {'doublons':>9} "
          f"{'faux-evt':>9} {'persist.moy':>12} {'%stable':>8} {'%transit.':>10} {'CPU tot':>9}")
    for n in N_VUES:
        t0 = time.time()
        sessions = [_session_confirmees(marque, n, seed_base=5000 * n + 13 * s) for s in range(R_SESSIONS)]
        cpu = time.time() - t0

        recalls, precisions, doublons_l = [], [], []
        for confirmees in sessions:
            tp, fn, fp, r, prec, d = _evaluer(confirmees, verite_xy, RAYON_MATCH_ANCIEN)
            recalls.append(r); precisions.append(prec); doublons_l.append(d)
        faux_evt = [_fausse_evolution(sessions[i], sessions[i+1], RAYON_MATCH_ANCIEN)
                   for i in range(R_SESSIONS - 1)]
        repro = _reproductibilite(sessions, RAYON_REGROUPEMENT_INTER_SESSION)
        r_m = moy(recalls)
        print(f"{n:>7} {r_m:>7.2f} {min(1.0, r_m*len(verite_xy)/7):>15.2f} {moy(precisions):>10.2f} "
              f"{moy(doublons_l):>9.2f} {moy(faux_evt):>9.2f} {repro['persistance_moyenne']:>12.2f} "
              f"{repro['part_stable']:>8.1%} {repro['part_transitoire']:>10.1%} {cpu:>8.0f}s")

    # ══════════════════════════════════════════════════════════════════
    # 2. Photo reelle (capture_001, sans verite terrain -> reproductibilite seule)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("2. PHOTO REELLE (capture_001.jpg — pas de verite terrain, reproductibilite seule)")
    print("=" * 100)
    if not IMAGE_REELLE.exists():
        print("capture_001.jpg absente (ephemere entre sessions) — section ignoree.")
    else:
        img_reel = _charger_oriente(IMAGE_REELLE)
        print(f"{'N vues':>7} {'confirmees/session':<28} {'persist.moy':>12} {'%stable':>8} "
              f"{'%transit.':>10} {'CPU tot':>9}")
        for n in N_VUES:
            t0 = time.time()
            sessions = [_session_confirmees(img_reel, n, seed_base=6000 * n + 13 * s) for s in range(R_SESSIONS)]
            cpu = time.time() - t0
            repro = _reproductibilite(sessions, RAYON_REGROUPEMENT_INTER_SESSION)
            comptes = [len(s) for s in sessions]
            print(f"{n:>7} {str(comptes):<28} {repro['persistance_moyenne']:>12.2f} "
                  f"{repro['part_stable']:>8.1%} {repro['part_transitoire']:>10.1%} {cpu:>8.0f}s")

    print("\nAucun changement de detecteur, de tracking, de nettoyage, de purete ou de vote-gate. "
          "Rien modifie en production. Aucune image commitee.")


if __name__ == "__main__":
    run()
