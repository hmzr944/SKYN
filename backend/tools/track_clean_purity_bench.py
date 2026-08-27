"""Recombinaison : nettoyage observationnel PUIS pureté du track PUIS
vote-gate — dans cet ordre, pas l'inverse.

────────────────────────────────────────────────────────────────────────
POURQUOI L'ORDRE COMPTE.

`track_purity_gate_bench.py` appliquait la pureté sur le track BRUT (avec
contamination) : L8 avait coherence_photo=0,000 et se faisait rejeter en
bloc, recall 0,73 -> 0,60. `observation_outlier_bench.py` a ensuite montre
qu'on peut retirer les observations aberrantes SANS abimer L8 (32
observations contaminantes identifiees, score 10,53-22, contre 0,00-2,46
pour les observations genuines de L8 et jusqu'a 8,75 pour la variation
naturelle des autres verites) — mais mesurait la pureté sur le track
ENCORE contamine, donc le gain ne se voyait nulle part.

Ce script fait l'experience manquante : nettoyer D'ABORD, recalculer
coherence_photo SUR LE TRACK NETTOYE, et SEULEMENT ENSUITE decider si le
track (desormais purge de sa contamination) merite d'etre confirme.

Pipeline teste :
    tracking (rayon=0,05, inchange)
        -> observation outlier removal (statistique robuste, meme
           constante 1,4826xMAD que `_robust_thr()` en production)
        -> track NETTOYE (position, evidence, coherence_photo, vote
           TOUS recalcules sur les observations restantes — pas de
           moyenne polluee par les observations retirees)
        -> track purity gate (seuil mesure APRES nettoyage, pas repris
           de l'experience precedente)
        -> vote-gate (ratio>=0,5, marge>=0,8, inchange)

Trois variantes comparees sur le meme jeu de sessions :
    A — VOTE-GATE seul (reference deja connue)
    B — NETTOYAGE puis VOTE-GATE (sans porte de purete)
    C — NETTOYAGE puis PURETE puis VOTE-GATE (la recombinaison complete)

IMPORTANT — ce que la pureté valide et ce qu'elle NE valide PAS : elle
detecte la coherence INTERNE d'un track, pas la verite. Les faux positifs
de l'experience precedente avaient une purete tres elevee (0,880-1,000) —
plus haute encore que les vraies lesions. La porte de purete ne remplace
pas le vote-gate, elle le complete.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/track_clean_purity_bench.py
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
    _generer_sessions,
    _suivre,
)
from backend.tools.lesion_association_bench import _contamination, _fragmentation_integrite  # noqa: E402
from backend.tools.observation_outlier_bench import (  # noqa: E402
    _decision_vote_porte,
    _dimensions,
    _nettoyer,
)
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
SEUILS_NETTOYAGE = [6.0, 7.0, 8.0, 9.5, 11.0]  # encadre le vrai gap mesure [8.75, 10.53]
SEUIL_NETTOYAGE_PRINCIPAL = 9.5


def _position(obs: List[dict]):
    k = len(obs)
    return sum(o["x"] for o in obs) / k, sum(o["y"] for o in obs) / k


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

    print(f"{len(verite)} lesions plantees, generation des sessions...\n")
    t0 = time.time()
    sessions = _generer_sessions(marque)
    print(f"(genere en {time.time()-t0:.0f}s)\n")

    pistes_par_session = [_suivre(vc, RAYON_MATCH_ANCIEN) for vc in sessions]
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

    # ══════════════════════════════════════════════════════════════════
    # MESURE 1 : coherence_photo APRES nettoyage (pas avant) — L8 vs le reste
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print(f"MESURE : coherence_photo APRES nettoyage (seuil={SEUIL_NETTOYAGE_PRINCIPAL}), "
          f"sur les tracks que le vote-gate confirmerait")
    print("=" * 100)

    categories = {"L8 (contaminee, nettoyee)": [], "autre verite terrain": [], "faux positif": []}
    for vues_candidats, pistes_brutes in zip(sessions, pistes_par_session):
        n_vues = len(vues_candidats)
        for p in pistes_brutes:
            obs_nettoyees = _nettoyer(p["obs"], SEUIL_NETTOYAGE_PRINCIPAL)
            dims = _dimensions(obs_nettoyees, n_vues, RAYON_MATCH_ANCIEN)
            if dims["evidence"] < SEUIL_EVIDENCE:
                continue
            _, etat = _decision_vote_porte(obs_nettoyees)
            if etat != "CONFIRMEE":
                continue
            cx, cy = _position(obs_nettoyees)
            correspond = [i for i, gt in enumerate(verite)
                         if ((cx-gt["x"])**2 + (cy-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if 7 in correspond:
                categories["L8 (contaminee, nettoyee)"].append(dims["coherence_photo"])
            elif correspond:
                categories["autre verite terrain"].append(dims["coherence_photo"])
            else:
                categories["faux positif"].append(dims["coherence_photo"])

    for nom, valeurs in categories.items():
        if valeurs:
            print(f"  {nom:<28} n={len(valeurs):>3}  moyenne={moy(valeurs):.3f}  "
                  f"min={min(valeurs):.3f}  max={max(valeurs):.3f}")
        else:
            print(f"  {nom:<28} n=0")

    l8_vals = categories["L8 (contaminee, nettoyee)"]
    autres_vals = categories["autre verite terrain"]
    if l8_vals and autres_vals:
        print(f"\nL8 apres nettoyage : {min(l8_vals):.3f}-{max(l8_vals):.3f}  vs  "
              f"autres verites : {min(autres_vals):.3f}-{max(autres_vals):.3f}")
    print(f"(Les seuils de purete testes plus bas (0.4/0.5/0.6) sont choisis en lisant la "
          f"distribution ci-dessus, pas calcules automatiquement.)")

    # ══════════════════════════════════════════════════════════════════
    # BENCHMARK A / B / C
    # ══════════════════════════════════════════════════════════════════
    def _mesurer(seuil_nettoyage, seuil_purete_gate):
        recalls, precisions, doublons_l = [], [], []
        integrites, fragmentations, contams = [], [], []
        filtres = []
        for pistes_brutes, vues_candidats, verites_avec_obs in zip(pistes_par_session, sessions, verites_avec_obs_par_session):
            n_vues = len(vues_candidats)
            gardees, idx_confirmees = [], set()
            for i, p in enumerate(pistes_brutes):
                obs = _nettoyer(p["obs"], seuil_nettoyage) if seuil_nettoyage is not None else p["obs"]
                dims = _dimensions(obs, n_vues, RAYON_MATCH_ANCIEN)
                if dims["evidence"] < SEUIL_EVIDENCE:
                    continue
                if seuil_purete_gate is not None and dims["coherence_photo"] < seuil_purete_gate:
                    continue
                _, etat = _decision_vote_porte(obs)
                if etat != "CONFIRMEE":
                    continue
                cx, cy = _position(obs)
                gardees.append({"x": cx, "y": cy})
                idx_confirmees.add(i)
            verite_xy = [(g["x"], g["y"]) for g in verite]
            tp, fn, fp, r, prec, dbl = _evaluer(gardees, verite_xy, RAYON_MATCH_ANCIEN)
            recalls.append(r); precisions.append(prec); doublons_l.append(dbl)
            filtres.append(gardees)
            integ, frag = _fragmentation_integrite(pistes_brutes, verites_avec_obs)
            integrites.extend(integ); fragmentations.extend(frag)
            contams.extend(_contamination(pistes_brutes, verites_avec_obs, confirmees_only_idx=idx_confirmees))
        faux_evt = [_fausse_evolution(filtres[i], filtres[i+1], RAYON_MATCH_ANCIEN) for i in range(len(filtres)-1)]
        return {"recall": moy(recalls), "precision": moy(precisions), "doublons": moy(doublons_l),
                "faux_evt": moy(faux_evt), "integrite": moy(integrites), "fragmentation": moy(fragmentations),
                "contamination": moy(contams)}

    print("\n" + "=" * 100)
    print("BENCHMARK A / B / C")
    print("=" * 100)
    print(f"{'variante':<42} {'recall':>7} {'precision':>10} {'doublons':>9} {'faux-evt':>9} "
          f"{'integrite':>10} {'fragment.':>10} {'contam.':>8}")

    rA = _mesurer(None, None)
    print(f"{'A: VOTE-GATE seul':<42} {rA['recall']:>7.2f} {rA['precision']:>10.2f} "
          f"{rA['doublons']:>9.2f} {rA['faux_evt']:>9.2f} {rA['integrite']:>10.2f} "
          f"{rA['fragmentation']:>10.2f} {rA['contamination']:>8.2f}")

    for s in SEUILS_NETTOYAGE:
        rB = _mesurer(s, None)
        print(f"{f'B: NETTOYAGE({s}) -> VOTE-GATE':<42} {rB['recall']:>7.2f} {rB['precision']:>10.2f} "
              f"{rB['doublons']:>9.2f} {rB['faux_evt']:>9.2f} {rB['integrite']:>10.2f} "
              f"{rB['fragmentation']:>10.2f} {rB['contamination']:>8.2f}")

    for sp in (0.4, 0.5, 0.6):
        rC = _mesurer(SEUIL_NETTOYAGE_PRINCIPAL, sp)
        print(f"{f'C: NETTOYAGE({SEUIL_NETTOYAGE_PRINCIPAL})->PURETE(>={sp})->VOTE-GATE':<42} "
              f"{rC['recall']:>7.2f} {rC['precision']:>10.2f} {rC['doublons']:>9.2f} "
              f"{rC['faux_evt']:>9.2f} {rC['integrite']:>10.2f} {rC['fragmentation']:>10.2f} "
              f"{rC['contamination']:>8.2f}")

    print(f"\nCible : recall proche de 0.73, precision proche de 0.75, doublons=0, "
          f"faux-evt < 2.60 — mais on cherche un front de Pareto, pas un seul chiffre.")

    # ══════════════════════════════════════════════════════════════════
    # L8 de bout en bout : avant nettoyage -> apres nettoyage -> decision
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print(f"L8 DE BOUT EN BOUT (nettoyage={SEUIL_NETTOYAGE_PRINCIPAL}, purete>=0.5)")
    print("=" * 100)
    gt = verite[7]
    for s, (pistes_brutes, vues_candidats) in enumerate(zip(pistes_par_session, sessions)):
        proches = [p for p in pistes_brutes
                  if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
        if not proches:
            print(f"  session {s} : aucun candidat a portee")
            continue
        piste = max(proches, key=lambda p: len(p["obs"]))
        n_vues = len(vues_candidats)
        dims_avant = _dimensions(piste["obs"], n_vues, RAYON_MATCH_ANCIEN)
        obs_apres = _nettoyer(piste["obs"], SEUIL_NETTOYAGE_PRINCIPAL)
        dims_apres = _dimensions(obs_apres, n_vues, RAYON_MATCH_ANCIEN)
        _, etat_final = _decision_vote_porte(obs_apres)
        passe_purete = dims_apres["coherence_photo"] >= 0.5
        decision = etat_final if (etat_final == "CONFIRMEE" and passe_purete) else \
                  ("REJETEE_PURETE" if etat_final == "CONFIRMEE" else etat_final)
        print(f"  session {s} : purete AVANT={dims_avant['coherence_photo']:.3f}  "
              f"purete APRES nettoyage ({len(piste['obs'])}->{len(obs_apres)} obs)="
              f"{dims_apres['coherence_photo']:.3f}  decision finale={decision}")

    print("\nRien modifie en production.")


if __name__ == "__main__":
    run()
