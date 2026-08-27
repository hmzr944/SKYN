"""Observation-Level Outlier Rejection : nettoyer un track observation par
observation plutot que le rejeter en bloc.

────────────────────────────────────────────────────────────────────────
CE QUE `track_purity_gate_bench.py` A MONTRE, ET LA LEcON A EN TIRER.

`coherence_photo` separe L8 (contaminee, 0,000 dans les 6 sessions) du
reste (0,655-0,994) de facon quasi parfaite. Mais utilisee comme veto du
TRACK ENTIER, elle a fait chuter le recall de 0,73 a 0,60 — parce que L8
est une VRAIE lesion dont la piste absorbe AUSSI un artefact sombre
voisin. Rejeter le track jette le signal reel avec la contamination.

Ce script deplace la meme mesure d'un niveau : au lieu de juger le track,
juger chaque OBSERVATION par rapport au noyau du track, et ne retirer que
celles qui sont incompatibles — avant que le vote/evidence ne soit
calcule sur ce qu'il reste.

────────────────────────────────────────────────────────────────────────
METHODE — statistique robuste, pas une regle inventee.

Pour chaque piste d'au moins 3 observations :
    signal(o) = red si src="rouge" sinon dark   (deja ce que
                `coherence_photo` comparait, au niveau du track)
    mediane, MAD = statistiques robustes du track
    score_aberrant(o) = |signal(o) - mediane| / (1,4826 x MAD)

Ce facteur 1,4826 n'est pas invente pour l'occasion : c'est EXACTEMENT la
constante deja utilisee par `_robust_thr()` en production (mediane +
k x 1,4826 x MAD) — la meme idee de statistique robuste, appliquee ici a
l'echelle d'une piste au lieu de l'echelle d'un visage entier, pour rester
coherent avec la philosophie deja validee du moteur plutot que d'importer
une nouvelle idee statistique.

AVANT de choisir un seuil, ce script MESURE le score_aberrant separement
pour trois populations connues :
    1. les observations CONTAMINANTES connues de L8 (signal tres negatif,
       identifiees a la main a partir des traces deja publiees)
    2. les observations GENUINES de L8 (le reste de sa piste)
    3. les observations des AUTRES verites terrain (variation naturelle
       d'angle/capture, aucune contamination connue)
Le seuil n'est choisi qu'apres avoir vu si ces trois populations se
separent reellement.

Rayon (0,05), tracker, vote-gate (ratio>=0,5, marge>=0,8), classification
individuelle : tous INCHANGES. Seule variable : le nettoyage des
observations avant evidence/vote.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/observation_outlier_bench.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.lesions import _classify  # noqa: E402
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
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
RATIO_MIN, SHARE_MIN = 0.5, 0.8
FACTEUR_MAD = 1.4826  # meme constante que _robust_thr() en production


def _signal(o: dict) -> float:
    return o["red"] if o["src"] == "rouge" else o["dark"]


def _scores_aberrants(obs: List[dict]):
    """Retourne un score par observation, ou None si le track est trop
    petit pour une statistique robuste (< 3 obs)."""
    if len(obs) < 3:
        return None
    signaux = sorted(_signal(o) for o in obs)
    n = len(signaux)
    mediane = signaux[n // 2] if n % 2 else (signaux[n // 2 - 1] + signaux[n // 2]) / 2.0
    ecarts = sorted(abs(s - mediane) for s in signaux)
    mad = ecarts[n // 2] if n % 2 else (ecarts[n // 2 - 1] + ecarts[n // 2]) / 2.0
    if mad < 0.05:  # spread quasi nul : pas de division instable, tout est "normal"
        return [0.0 for _ in obs]
    return [abs(_signal(o) - mediane) / (FACTEUR_MAD * mad) for o in obs]


def _nettoyer(obs: List[dict], seuil: float) -> List[dict]:
    scores = _scores_aberrants(obs)
    if scores is None:
        return obs
    gardees = [o for o, s in zip(obs, scores) if s <= seuil]
    return gardees if len(gardees) >= 2 else obs  # ne jamais vider une piste sous 2 obs


def _dimensions(obs: List[dict], n_vues: int, rayon: float) -> dict:
    k = len(obs)
    persistance = k / n_vues
    evidence_signal = sum(1.0 for o in obs if o["depasse_prod"]) / k
    if k >= 2:
        xs = [o["x"] for o in obs]; ys = [o["y"] for o in obs]
        mx, my = sum(xs) / k, sum(ys) / k
        std_pos = (sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / k) ** 0.5
        coherence_position = max(0.0, 1.0 - std_pos / rayon)
        signaux = [_signal(o) for o in obs]
        m_sig = sum(signaux) / k
        if abs(m_sig) > 1e-6:
            ecart_type = (sum((s - m_sig) ** 2 for s in signaux) / k) ** 0.5
            coherence_photo = max(0.0, 1.0 - min(1.0, ecart_type / abs(m_sig)))
        else:
            coherence_photo = 0.5
        decisions = [o["decision_0"] for o in obs]
        majoritaire = max(set(decisions), key=decisions.count)
        coherence_forme = decisions.count(majoritaire) / k
    else:
        coherence_position = coherence_photo = coherence_forme = 0.5
    evidence = (persistance + evidence_signal + coherence_position + coherence_forme + coherence_photo) / 5.0
    return {"evidence": evidence, "coherence_photo": coherence_photo}


def _decision_vote_porte(obs: List[dict], ratio_min: float = RATIO_MIN, share_min: float = SHARE_MIN):
    votes_valides = [o["decision_0"] for o in obs if o["decision_0"] is not None]
    n = len(obs)
    ratio = len(votes_valides) / n if n else 0.0
    if not votes_valides:
        return None, "REJETEE"
    majoritaire = max(set(votes_valides), key=votes_valides.count)
    share = votes_valides.count(majoritaire) / len(votes_valides)
    if ratio >= ratio_min and share >= share_min:
        return majoritaire, "CONFIRMEE"
    return None, "INCERTAINE"


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
    # MESURE : le score aberrant separe-t-il vraiment contamination /
    # variation naturelle, avant de choisir un seuil ?
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("MESURE : score_aberrant sur trois populations connues (L8 confirmee par le vote-gate)")
    print("=" * 100)

    scores_contaminantes, scores_genuines_l8, scores_autres = [], [], []
    for gt_idx, (gt) in enumerate(verite):
        for pistes_brutes in pistes_par_session:
            proches = [p for p in pistes_brutes
                      if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if not proches:
                continue
            piste = max(proches, key=lambda p: len(p["obs"]))
            _, etat = _decision_vote_porte(piste["obs"])
            if etat != "CONFIRMEE":
                continue
            scores = _scores_aberrants(piste["obs"])
            if scores is None:
                continue
            for o, s in zip(piste["obs"], scores):
                if gt_idx == 7:  # L8
                    (scores_contaminantes if _signal(o) < 0 and o["src"] == "sombre" else scores_genuines_l8).append(s)
                else:
                    scores_autres.append(s)

    for nom, valeurs in (("L8 : observations contaminantes (signal sombre)", scores_contaminantes),
                        ("L8 : observations genuines (signal rouge)", scores_genuines_l8),
                        ("autres verites : variation naturelle", scores_autres)):
        if valeurs:
            print(f"  {nom:<48} n={len(valeurs):>4}  moyenne={moy(valeurs):.2f}  "
                  f"min={min(valeurs):.2f}  max={max(valeurs):.2f}")
        else:
            print(f"  {nom:<48} n=0")

    # ══════════════════════════════════════════════════════════════════
    # BENCHMARK : vote-gate seul vs vote-gate + nettoyage par observation
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("BENCHMARK")
    print("=" * 100)

    def _mesurer(seuil_nettoyage):
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
                _, etat = _decision_vote_porte(obs)
                if etat != "CONFIRMEE":
                    continue
                gardees.append({"x": p["x"], "y": p["y"]})
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

    print(f"{'variante':<38} {'recall':>7} {'precision':>10} {'doublons':>9} {'faux-evt':>9} "
          f"{'integrite':>10} {'fragment.':>10} {'contam.':>8}")

    r0 = _mesurer(None)
    print(f"{'VOTE-GATE seul (reference)':<38} {r0['recall']:>7.2f} {r0['precision']:>10.2f} "
          f"{r0['doublons']:>9.2f} {r0['faux_evt']:>9.2f} {r0['integrite']:>10.2f} "
          f"{r0['fragmentation']:>10.2f} {r0['contamination']:>8.2f}")

    for seuil in (1.5, 2.0, 3.0, 4.0):
        r = _mesurer(seuil)
        print(f"{'+ nettoyage seuil ' + str(seuil):<38} {r['recall']:>7.2f} {r['precision']:>10.2f} "
              f"{r['doublons']:>9.2f} {r['faux_evt']:>9.2f} {r['integrite']:>10.2f} "
              f"{r['fragmentation']:>10.2f} {r['contamination']:>8.2f}")

    print(f"\nCible : recall >= 0.73, precision >= 0.75 idealement, doublons=0, faux-evt <= 2.60.")

    # ══════════════════════════════════════════════════════════════════
    # Cas dedies L1 / L8
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("CAS DEDIES (seuil de nettoyage = 3.0)")
    print("=" * 100)
    seuil_ref = 3.0

    for cible_id, cible_idx in (("L1", 0), ("L8", 7)):
        gt = verite[cible_idx]
        print(f"\n{cible_id} :")
        for s, (pistes_brutes, vues_candidats) in enumerate(zip(pistes_par_session, sessions)):
            proches = [p for p in pistes_brutes
                      if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if not proches:
                print(f"  session {s} : aucun candidat a portee")
                continue
            piste = max(proches, key=lambda p: len(p["obs"]))
            obs_avant = piste["obs"]
            obs_apres = _nettoyer(obs_avant, seuil_ref)
            n_retirees = len(obs_avant) - len(obs_apres)
            _, etat_avant = _decision_vote_porte(obs_avant)
            _, etat_apres = _decision_vote_porte(obs_apres)
            print(f"  session {s} : {len(obs_avant)} obs -> {len(obs_apres)} apres nettoyage "
                  f"({n_retirees} retirees)  AVANT={etat_avant}  APRES={etat_apres}")

    print("\nRien modifie en production.")


if __name__ == "__main__":
    run()
