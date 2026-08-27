"""Best-cost matching vs rayon fixe, avec fragmentation/contamination
mesurees separement du recall — la suite directe de
`lesion_tracking_audit.py`, qui a isole le probleme (13/14 pertes =
fragmentation) sans encore le resoudre proprement.

────────────────────────────────────────────────────────────────────────
POURQUOI "MEILLEUR RAYON" N'ETAIT PAS LA BONNE QUESTION.

Le banc precedent a montre : rayon 0,05 -> fragmentation (recall 0,54,
doublons 0,00) ; rayon 0,122 -> sur-fusion (recall 0,77, doublons 0,83).
Fait interessant NON releve avant : le tracker precedent choisissait deja,
a rayon fixe, le track le PLUS PROCHE parmi ceux a portee (pas le premier
trouve) — donc "gating large + meilleur cout spatial" (la variante C
demandee) est MECANIQUEMENT IDENTIQUE a "rayon large" (variante B) : les
deux ne comparent que la distance. Ce script le documente au lieu de le
re-executer inutilement, et teste plutot la vraie question neuve :
meilleur cout MULTI-CRITERES (variante D) fait-il mieux que la distance
seule au meme rayon de gating ?

VARIANTES :
    A — rayon fixe 0,05 (l'original)
    B — rayon fixe 0,122 (= C, gating + meilleur cout spatial seul —
        equivalence expliquee ci-dessus, pas reteste separement)
    D — gating 0,122 + cout MULTI-CRITERES (spatial + signal + classe +
        morphologie, poids EGAUX non calibres — memes raisons que partout
        ailleurs dans ce chantier : calibrer honnetement demanderait des
        donnees etiquetees hors de portee d'un banc offline)

La confirmation est FIXEE a vote majoritaire (l'architecture corrigee :
classifier par vue, puis suivre) pour LES TROIS variantes, pour isoler la
seule variable testee ici — l'association — de la confirmation.

────────────────────────────────────────────────────────────────────────
NOUVELLES METRIQUES (remplacent le "Track Recall" identifie comme trop
permissif dans le banc precedent — il valait 1,00 partout meme quand la
fragmentation etait totale) :

    Track Integrity — pour une verite terrain, la part de ses PROPRES
        observations (candidats reellement proches d'elle, toutes vues
        confondues) qui se retrouvent dans son MEILLEUR track unique.
        100 % = jamais fragmentee. Exemple verifie contre la demande :
        6+2 observations -> 75 % ; 3+3+2 -> 37,5 %.
    Track Fragmentation — nombre de tracks distincts qui contiennent au
        moins une observation de cette verite. 1 = ideal.
    Track Contamination — pour un track, nombre de verites terrain
        DIFFERENTES dont au moins une observation s'y trouve, moins 1.
        0 = pur. Mesuree sur tous les tracks, et separement sur les seuls
        tracks CONFIRMES (ceux qui produisent reellement un doublon dans
        le rapport final).

Rien n'est modifie en production.

Usage :
    python3 backend/tools/lesion_association_bench.py
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
from backend.tools.lesion_tracking_audit import (  # noqa: E402
    RAYON_CAPTURE,
    RAYON_MATCH_ANCIEN,
    SEUIL_EVIDENCE,
    _evidence_et_decision,
    _generer_sessions,
)
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
RAYON_LARGE = 0.122     # meme calibration empirique que le banc precedent


def _cout(cand: dict, piste: dict, gate: float, multi_critere: bool):
    d = ((cand["x"] - piste["x"]) ** 2 + (cand["y"] - piste["y"]) ** 2) ** 0.5
    if d >= gate:
        return None
    spatial = d / gate
    if not multi_critere:
        return spatial

    obs = piste["obs"]
    sig_piste = sum((o["red"] if o["src"] == "rouge" else o["dark"]) for o in obs) / len(obs)
    sig_cand = cand["red"] if cand["src"] == "rouge" else cand["dark"]
    denom = abs(sig_cand) + abs(sig_piste) + 1e-6
    signal_term = min(1.0, abs(sig_cand - sig_piste) / denom)

    decisions_piste = [o["decision_0"] for o in obs if o["decision_0"] is not None]
    if decisions_piste and cand["decision_0"] is not None:
        majoritaire = max(set(decisions_piste), key=decisions_piste.count)
        class_term = 0.0 if cand["decision_0"] == majoritaire else 1.0
    else:
        class_term = 0.0  # pas de conflit actif si l'un des deux est indetermine

    r_piste = sum(o["r_px"] for o in obs) / len(obs)
    denom_r = cand["r_px"] + r_piste + 1e-6
    morpho_term = min(1.0, abs(cand["r_px"] - r_piste) / denom_r)

    return (spatial + signal_term + class_term + morpho_term) / 4.0


def _suivre_meilleur_cout(vues_candidats: List[List[dict]], gate: float, multi_critere: bool) -> List[dict]:
    pistes: List[dict] = []
    for cands in vues_candidats:
        for c in cands:
            couts = [(i, _cout(c, p, gate, multi_critere)) for i, p in enumerate(pistes)]
            couts = [(i, co) for i, co in couts if co is not None]
            if couts:
                i_meilleur = min(couts, key=lambda t: t[1])[0]
                p = pistes[i_meilleur]
                p["obs"].append(c)
                p["x"] = sum(o["x"] for o in p["obs"]) / len(p["obs"])
                p["y"] = sum(o["y"] for o in p["obs"]) / len(p["obs"])
            else:
                pistes.append({"x": c["x"], "y": c["y"], "obs": [c]})
    return pistes


def _fragmentation_integrite(pistes, verites_avec_obs):
    """verites_avec_obs : liste de sets d'id() des observations reellement
    proches (rayon genereux) de chaque verite terrain, calcules UNE FOIS
    par session sur les vues brutes — independamment du tracker teste."""
    integrites, fragmentations = [], []
    for s_gt in verites_avec_obs:
        if not s_gt:
            continue
        tailles = []
        for p in pistes:
            n = sum(1 for o in p["obs"] if id(o) in s_gt)
            if n > 0:
                tailles.append(n)
        integrites.append(max(tailles) / len(s_gt) if tailles else 0.0)
        fragmentations.append(len(tailles))
    return integrites, fragmentations


def _contamination(pistes, verites_avec_obs, confirmees_only_idx=None):
    contaminations = []
    for i, p in enumerate(pistes):
        if confirmees_only_idx is not None and i not in confirmees_only_idx:
            continue
        obs_ids = {id(o) for o in p["obs"]}
        n_verites = sum(1 for s_gt in verites_avec_obs if s_gt and (s_gt & obs_ids))
        if n_verites > 0:
            contaminations.append(n_verites - 1)
    return contaminations


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    pts0 = _landmarks(img)
    if pts0 is None:
        raise SystemExit("aucun visage detecte")
    marque = img.copy()
    plantees = []
    for zone in ZONES_PLANTEES:
        marque, p = plant(marque, pts0, zone, LESIONS_PAR_ZONE, seed=SEED_PLANT)
        plantees.extend(p)
    base = build_face_map(_b64(marque, quality=100))
    x0, y0, bw, bh = base.bbox
    verite = [{"id": f"L{i+1}", "x": (p.x - x0) / bw, "y": (p.y - y0) / bh} for i, p in enumerate(plantees)]

    print(f"{len(verite)} lesions plantees, generation des sessions (~1 min)...\n")
    t0 = time.time()
    sessions = _generer_sessions(marque)
    print(f"(genere en {time.time()-t0:.0f}s)\n")

    verites_avec_obs_par_session = []
    for vues_candidats in sessions:
        par_verite = []
        for gt in verite:
            s = set()
            for cands in vues_candidats:
                for c in cands:
                    if ((c["x"] - gt["x"]) ** 2 + (c["y"] - gt["y"]) ** 2) ** 0.5 < RAYON_CAPTURE:
                        s.add(id(c))
            par_verite.append(s)
        verites_avec_obs_par_session.append(par_verite)

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

    VARIANTES = [
        ("A: rayon 0.05", RAYON_MATCH_ANCIEN, False),
        ("B=C: rayon 0.122 (gate+cout spatial seul)", RAYON_LARGE, False),
        ("D: gate 0.122 + cout multi-critere", RAYON_LARGE, True),
    ]

    print(f"{'variante':<42} {'recall':>7} {'precision':>10} {'doublons':>9} "
          f"{'faux-evt/paire':>15} {'integrite':>10} {'fragment.':>10} "
          f"{'contam.(tous)':>14} {'contam.(confirmes)':>19}")

    for nom, gate, multi in VARIANTES:
        pistes_par_session = []
        for vues_candidats in sessions:
            pistes_brutes = _suivre_meilleur_cout(vues_candidats, gate, multi)
            pistes = [_evidence_et_decision(p, len(vues_candidats), gate, vote_individuel=True)
                      for p in pistes_brutes]
            pistes_par_session.append((pistes, pistes_brutes))

        recalls, precisions, doublons_l = [], [], []
        integrites_tout, fragment_tout, contam_tout, contam_conf = [], [], [], []
        filtres = []
        for (pistes, pistes_brutes), verites_avec_obs in zip(pistes_par_session, verites_avec_obs_par_session):
            gardees = [p for p in pistes if p["evidence"] >= SEUIL_EVIDENCE and p["decision_finale"] is not None]
            verite_xy = [(g["x"], g["y"]) for g in verite]
            tp, fn, fp, r, prec, d = _evaluer(gardees, verite_xy, gate)
            recalls.append(r); precisions.append(prec); doublons_l.append(d)
            filtres.append(gardees)

            integ, frag = _fragmentation_integrite(pistes_brutes, verites_avec_obs)
            integrites_tout.extend(integ)
            fragment_tout.extend(frag)
            contam_tout.extend(_contamination(pistes_brutes, verites_avec_obs))
            idx_confirmes = {i for i, p in enumerate(pistes)
                             if p["evidence"] >= SEUIL_EVIDENCE and p["decision_finale"] is not None}
            contam_conf.extend(_contamination(pistes_brutes, verites_avec_obs, confirmees_only_idx=idx_confirmes))

        faux_evt = [_fausse_evolution(filtres[i], filtres[i+1], gate) for i in range(len(filtres)-1)]

        print(f"{nom:<42} {moy(recalls):>7.2f} {moy(precisions):>10.2f} {moy(doublons_l):>9.2f} "
              f"{moy(faux_evt):>15.2f} {moy(integrites_tout):>10.2f} {moy(fragment_tout):>10.2f} "
              f"{moy(contam_tout):>14.2f} {moy(contam_conf):>19.2f}")

    print(f"\nCible : recall >= 0.84 (production), doublons ~= 0, faux-evt < 6.57, "
          f"integrite en hausse, fragmentation en baisse (-> 1), contamination en baisse (-> 0).")
    print("Rien modifie en production.")


if __name__ == "__main__":
    run()
