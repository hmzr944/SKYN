"""Guided Capture Protocol v0 — benchmark : N=3 fixe (actuel) vs N=7 fixe
vs N=9 fixe vs ADAPTATIF (min=5 / cible=7 / max=9), via `guided_capture_
protocol.orchestrer_scan()`.

────────────────────────────────────────────────────────────────────────
CE QUE CE BANC AJOUTE PAR RAPPORT A `capture_protocol_bench.py`.

Le banc precedent mesurait N fixe uniquement. Celui-ci passe par le
module d'orchestration reutilisable (`guided_capture_protocol.py`) et
ajoute donc la vraie question posee : le mecanisme d'ARRET ADAPTATIF
(min 5 / cible 7 / max 9) obtient-il une reproductibilite comparable a
N=9 fixe, en utilisant MOINS de vues en moyenne — le compromis produit
recherche (ne pas faire tourner l'utilisateur pour rien si 5-7 vues
suffisent deja) ?

LIMITE INCHANGEE, a redire : toujours pas de vraie diversite d'angle
15-60°, seulement des vues quasi-frontales avec le bruit de capture deja
calibre. "A -> nouvelle session" reste, pour la partie synthetique, des
tirages de bruit differents sur la MEME photo de reference — pas une
nouvelle capture reelle. La section 2 (photo reelle) reste limitee a
`capture_001.jpg`, la seule photo du pilote sans le facteur appareil
confondu identifie precedemment.

METRIQUES : recall / recall_detectable(/7) / precision / doublons /
faux-evenements / %stable / %transitoire / CPU / nombre de vues
REELLEMENT utilisees (utile precisement pour juger l'adaptatif). "Score"
et "temps utilisateur" ne sont PAS mesures ici et ne le seront pas tant
qu'ils ne sont pas honnetement mesurables : `orchestrer_scan()` ne calcule
aucun score produit (ce n'est pas `analyze_face`), et le temps de capture
reel depend d'une vraie interface, absente de ce banc offline.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/capture_protocol_v0_bench.py
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
from backend.tools.guided_capture_protocol import FrameMeta, ScanConfig, orchestrer_scan  # noqa: E402
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN  # noqa: E402
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution, _vues_de_session  # noqa: E402
from backend.tools.real_skin_pilot_session_ab import _charger_oriente  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

DOSSIER_PILOTE = Path("/home/user/real_skin_pilot/subject_001")
IMAGE_SYNTH = Path("backend/tests/fixtures_face.jpg")
IMAGE_REELLE = DOSSIER_PILOTE / "capture_001.jpg"

R_SESSIONS = 6
RAYON_REGROUPEMENT_INTER_SESSION = 0.08

VARIANTES = [
    ("N=3 fixe (actuel)", ScanConfig(min_vues_utiles=3, cible_vues=3, max_vues=3)),
    ("N=7 fixe", ScanConfig(min_vues_utiles=7, cible_vues=7, max_vues=7)),
    ("N=9 fixe", ScanConfig(min_vues_utiles=9, cible_vues=9, max_vues=9)),
    ("ADAPTATIF (min5/cible7/max9)", ScanConfig(min_vues_utiles=5, cible_vues=7, max_vues=9)),
]


def _reproductibilite(sessions_confirmees: List[List[dict]], rayon: float) -> dict:
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
    return {"persistance_moyenne": moy(persistances),
            "part_stable": stables / len(meta_pistes) if meta_pistes else 0.0,
            "part_transitoire": transitoires / len(meta_pistes) if meta_pistes else 0.0}


def _sessions_pour(img, config: ScanConfig, seed_base_par_n: int, r_sessions: int):
    """Genere R sessions ; le nombre de vues fournies suit toujours
    `config.max_vues` (assez pour laisser l'adaptatif s'arreter plus tot,
    ou pour forcer exactement N pour les variantes fixes)."""
    sessions_resultats = []
    for s in range(r_sessions):
        images = _vues_de_session(img, config.max_vues, seed=seed_base_par_n + 13 * s)
        frames = [FrameMeta(image_b64=im) for im in images]
        sessions_resultats.append(orchestrer_scan(frames, config))
    return sessions_resultats


def run() -> None:
    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

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

    print(f"{'variante':<30} {'recall':>7} {'rec.det(/7)':>12} {'precision':>10} {'doublons':>9} "
          f"{'faux-evt':>9} {'persist.':>9} {'%stable':>8} {'%transit':>9} {'vues util.moy':>14} "
          f"{'CPU tot':>9}")
    for i_variante, (nom, config) in enumerate(VARIANTES):
        t0 = time.time()
        resultats = _sessions_pour(marque, config, seed_base_par_n=7000 + 100 * i_variante, r_sessions=R_SESSIONS)
        cpu = time.time() - t0
        sessions_confirmees = [r.lesions_confirmees for r in resultats]

        recalls, precisions, doublons_l = [], [], []
        for confirmees in sessions_confirmees:
            tp, fn, fp, r, prec, d = _evaluer(confirmees, verite_xy, RAYON_MATCH_ANCIEN)
            recalls.append(r); precisions.append(prec); doublons_l.append(d)
        faux_evt = [_fausse_evolution(sessions_confirmees[i], sessions_confirmees[i+1], RAYON_MATCH_ANCIEN)
                   for i in range(R_SESSIONS - 1)]
        repro = _reproductibilite(sessions_confirmees, RAYON_REGROUPEMENT_INTER_SESSION)
        vues_util = [r.n_vues_utilisables for r in resultats]
        r_m = moy(recalls)
        print(f"{nom:<30} {r_m:>7.2f} {min(1.0, r_m*len(verite_xy)/7):>12.2f} {moy(precisions):>10.2f} "
              f"{moy(doublons_l):>9.2f} {moy(faux_evt):>9.2f} {repro['persistance_moyenne']:>9.2f} "
              f"{repro['part_stable']:>8.1%} {repro['part_transitoire']:>9.1%} {moy(vues_util):>14.1f} "
              f"{cpu:>8.0f}s")

    print("\n" + "=" * 100)
    print("2. PHOTO REELLE (capture_001.jpg — reproductibilite seule, pas de verite terrain)")
    print("=" * 100)
    if not IMAGE_REELLE.exists():
        print("capture_001.jpg absente (ephemere entre sessions) — section ignoree.")
    else:
        img_reel = _charger_oriente(IMAGE_REELLE)
        print(f"{'variante':<30} {'persist.':>9} {'%stable':>8} {'%transit':>9} "
              f"{'vues util.moy':>14} {'CPU tot':>9}")
        for i_variante, (nom, config) in enumerate(VARIANTES):
            t0 = time.time()
            resultats = _sessions_pour(img_reel, config, seed_base_par_n=8000 + 100 * i_variante, r_sessions=R_SESSIONS)
            cpu = time.time() - t0
            sessions_confirmees = [r.lesions_confirmees for r in resultats]
            repro = _reproductibilite(sessions_confirmees, RAYON_REGROUPEMENT_INTER_SESSION)
            vues_util = [r.n_vues_utilisables for r in resultats]
            print(f"{nom:<30} {repro['persistance_moyenne']:>9.2f} {repro['part_stable']:>8.1%} "
                  f"{repro['part_transitoire']:>9.1%} {moy(vues_util):>14.1f} {cpu:>8.0f}s")

    print("\n'Score' et 'temps utilisateur' non mesures — hors de la portee de ce pipeline offline "
          "(voir l'entete du fichier). Aucun changement de detecteur/tracking/nettoyage/purete/"
          "vote-gate. Rien modifie en production. Aucune image commitee.")


if __name__ == "__main__":
    run()
