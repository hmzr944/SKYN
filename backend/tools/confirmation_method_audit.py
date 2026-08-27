"""Experience isolee : classify(mean_signal) vs vote majoritaire, TOUT LE
RESTE FIXE (rayon 0,05, meme tracker, memes candidats, memes 9 vues, meme
jeu de donnees). Une seule variable change.

────────────────────────────────────────────────────────────────────────
POURQUOI CETTE EXPERIENCE MAINTENANT.

`lesion_association_bench.py` a change DEUX choses a la fois entre son
"ancien" (0,54 recall) et ses variantes A/B/D (0,73-0,83) : la methode de
confirmation (mean -> vote) ET l'algorithme d'association (rayon fixe ->
best-cost). Impossible de savoir laquelle porte le gain. Ce script isole
la SEULE variable confirmation, rayon et tracker restant strictement ceux
de l'origine (0,05, plus proche voisin, sans porte de classe).

Deux methodes de decision de classe, calculees sur les MEMES pistes :
    MOYENNE — `_classify()` de production sur le signal moyen de la piste
              (l'architecture d'origine, avant tout ce chantier)
    VOTE    — pluralite des classifications INDIVIDUELLES par vue
              (`decision_0`, deja calculee a la generation de chaque
              candidat) — PAS de seuil de marge invente : le vote retient
              la classe non-None la plus frequente, quelle que soit sa
              marge ; la marge est MESUREE, pas imposee (section
              suivante), pour eventuellement en tirer un seuil plus tard
              a partir de la distribution reelle plutot que d'une
              intuition.
Le seuil d'evidence de confirmation (>= 0,50, memes 5 dimensions que
partout ailleurs dans ce chantier) reste identique pour les deux —
seule la determination de la CLASSE change.

Livrables demandes :
    1. Comparaison recall/precision/doublons/faux-evt, rayon fixe, une
       seule variable.
    2. Repartition des votes sur les pistes liees a une verite terrain
       (toutes les lesions plantees sont des papules par construction —
       voir plus bas — donc la "matrice de confusion" degenere en une
       repartition simple plutot qu'une vraie matrice N x N).
    3. Cas de desaccord : sequence de decisions par vue + signal associe,
       pour les pistes liees a une verite terrain dont les votes ne sont
       PAS unanimes.
    4. Distribution de la marge de vote (compte_majoritaire / nb_obs),
       SANS seuil impose — juste la distribution mesuree.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/confirmation_method_audit.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

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
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")


def _evidence(p: dict, n_vues: int, rayon: float) -> float:
    """La meme evidence a 5 dimensions que partout ailleurs — inchangee,
    puisque seule la determination de CLASSE est la variable testee ici."""
    obs = p["obs"]
    k = len(obs)
    persistance = k / n_vues
    evidence_signal = sum(1.0 for o in obs if o["depasse_prod"]) / k
    if k >= 2:
        xs = [o["x"] for o in obs]; ys = [o["y"] for o in obs]
        mx, my = sum(xs) / k, sum(ys) / k
        std_pos = (sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / k) ** 0.5
        coherence_position = max(0.0, 1.0 - std_pos / rayon)
        signaux = [o["red"] if o["src"] == "rouge" else o["dark"] for o in obs]
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
    return (persistance + evidence_signal + coherence_position + coherence_forme + coherence_photo) / 5.0


def _decision_moyenne(p: dict):
    obs = p["obs"]; k = len(obs)
    reds = [o["red"] for o in obs]; darks = [o["dark"] for o in obs]; yellows = [o["yellow"] for o in obs]
    core_ls = [o["core_l"] for o in obs]; core_ss = [o["core_s"] for o in obs]; skin_ss = [o["skin_s"] for o in obs]
    r_pxs = [o["r_px"] for o in obs]; ppms = [o["px_per_mm"] for o in obs]
    src_dom = max(set(o["src"] for o in obs), key=lambda s: sum(1 for o in obs if o["src"] == s))
    return _classify(sum(reds)/k, sum(darks)/k, sum(yellows)/k, sum(core_ls)/k,
                     sum(core_ss)/k, sum(skin_ss)/k, sum(r_pxs)/k, sum(ppms)/k, src_dom)


def _decision_vote(p: dict):
    """Pluralite des classifications individuelles, SANS seuil de marge
    invente — la classe non-None la plus frequente l'emporte, quelle que
    soit sa marge (mesuree separement, pas imposee ici)."""
    votes_valides = [o["decision_0"] for o in p["obs"] if o["decision_0"] is not None]
    if not votes_valides:
        return None, 0, len(p["obs"])
    majoritaire = max(set(votes_valides), key=votes_valides.count)
    compte = votes_valides.count(majoritaire)
    return majoritaire, compte, len(p["obs"])


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
    # Toutes les lesions de `plant()` sont peintes comme des papules
    # inflammatoires (deja verifie : sur l'image non perturbee, les 7
    # lesions separables sont TOUTES rapportees "papule") — la verite de
    # classe est donc constante, pas une hypothese.
    CLASSE_ATTENDUE = "papule"

    print(f"{len(verite)} lesions plantees (classe attendue = {CLASSE_ATTENDUE}), "
          f"generation des sessions...\n")
    t0 = time.time()
    sessions = _generer_sessions(marque)
    print(f"(genere en {time.time()-t0:.0f}s)\n")

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

    # ══════════════════════════════════════════════════════════════════
    # 1. UNE SEULE VARIABLE : moyenne vs vote, rayon 0.05 fixe, meme tracker
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("1. COMPARAISON ISOLEE (rayon=0.05, meme tracker, meme seuil d'evidence=0.50)")
    print("=" * 100)

    pistes_par_session = []
    for vues_candidats in sessions:
        pistes_par_session.append(_suivre(vues_candidats, RAYON_MATCH_ANCIEN))

    for nom_methode, decideur in (("MOYENNE (classify sur signal moyen)", "moyenne"),
                                   ("VOTE (pluralite des classifications individuelles)", "vote")):
        recalls, precisions, doublons_l = [], [], []
        filtres = []
        for pistes_brutes, vues_candidats in zip(pistes_par_session, sessions):
            n_vues = len(vues_candidats)
            gardees = []
            for p in pistes_brutes:
                ev = _evidence(p, n_vues, RAYON_MATCH_ANCIEN)
                if ev < SEUIL_EVIDENCE:
                    continue
                d = _decision_moyenne(p) if decideur == "moyenne" else _decision_vote(p)[0]
                if d is not None:
                    gardees.append({"x": p["x"], "y": p["y"]})
            verite_xy = [(g["x"], g["y"]) for g in verite]
            tp, fn, fp, r, prec, dbl = _evaluer(gardees, verite_xy, RAYON_MATCH_ANCIEN)
            recalls.append(r); precisions.append(prec); doublons_l.append(dbl)
            filtres.append(gardees)
        faux_evt = [_fausse_evolution(filtres[i], filtres[i+1], RAYON_MATCH_ANCIEN) for i in range(len(filtres)-1)]
        print(f"{nom_methode:<55} recall={moy(recalls):.2f}  precision={moy(precisions):.2f}  "
              f"doublons={moy(doublons_l):.2f}  faux-evt/paire={moy(faux_evt):.2f}")

    # ══════════════════════════════════════════════════════════════════
    # 2+3+4. Repartition des votes, desaccords, marge — sur pistes liees a une verite
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("2-3-4. VOTES SUR LES PISTES LIEES A UNE VERITE TERRAIN")
    print("=" * 100)

    repartition_votes = {}
    marges = []
    desaccords = []

    for vues_candidats, pistes_brutes in zip(sessions, pistes_par_session):
        for gt in verite:
            proches = [p for p in pistes_brutes
                      if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if not proches:
                continue
            piste = max(proches, key=lambda p: len(p["obs"]))  # le fragment le plus riche
            vote, compte, n_obs = _decision_vote(piste)
            repartition_votes[str(vote)] = repartition_votes.get(str(vote), 0) + 1
            marges.append(compte / n_obs if n_obs else 0.0)

            votes_bruts = [o["decision_0"] for o in piste["obs"]]
            if len(set(votes_bruts)) > 1:
                signaux = [round(o["red"] if o["src"] == "rouge" else o["dark"], 2) for o in piste["obs"]]
                desaccords.append((gt["id"], votes_bruts, signaux))

    print(f"\nRepartition des votes ({sum(repartition_votes.values())} pistes liees a une verite = {CLASSE_ATTENDUE}) :")
    for classe, n in sorted(repartition_votes.items(), key=lambda kv: -kv[1]):
        marque_correct = "  <- classe attendue" if classe == CLASSE_ATTENDUE else ("  <- ERREUR" if classe != "None" else "  (aucun vote valide)")
        print(f"  {classe:<15} {n:>3}{marque_correct}")

    print(f"\n{len(desaccords)} cas de DESACCORD (votes individuels non unanimes) sur "
          f"{sum(repartition_votes.values())} pistes liees a une verite :")
    for lid, votes_bruts, signaux in desaccords[:20]:
        print(f"  {lid} : votes={votes_bruts}  signal_dominant_par_vue={signaux}")
    if len(desaccords) > 20:
        print(f"  ... et {len(desaccords)-20} autres")

    print(f"\nDISTRIBUTION DE LA MARGE DE VOTE (compte_majoritaire / nb_observations, "
          f"aucun seuil impose — juste mesuree) :")
    bornes = [(1.0, 1.0, "= 1.0 (unanime)"), (0.75, 0.999, "[0.75, 1.0)"),
              (0.5, 0.749, "[0.50, 0.75)"), (0.0, 0.499, "< 0.50")]
    for lo, hi, label in bornes:
        n = sum(1 for m in marges if lo <= m <= hi)
        print(f"  {label:<15} {n:>3} / {len(marges)}")


if __name__ == "__main__":
    run()
