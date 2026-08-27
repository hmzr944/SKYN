"""Vote gated par marge + proportion de votes valides — troisieme etage de
l'audit de confirmation. Une seule variable de plus par rapport a
`confirmation_method_audit.py` : rayon, tracker, generation de candidats et
classification individuelle restent strictement identiques.

────────────────────────────────────────────────────────────────────────
CE QUE `confirmation_method_audit.py` A MONTRE.

Le vote naif recupere +21 points de recall (0,54 -> 0,75) mais fait
s'effondrer la precision (0,70 -> 0,27) et triple les faux-evenements
(1,80 -> 6,00). Les traces ont montre DEUX profils d'echec distincts :
    L1 — signal reellement borderline, jamais assez fort pour convaincre,
         peu de vues classifiees.
    L8 — piste CONTAMINEE : alterne entre un signal papule fort et un
         signal tres negatif (probablement un artefact different), et le
         vote peut donner une reponse majoritaire alors meme que la piste
         melange deux realites physiques distinctes.

────────────────────────────────────────────────────────────────────────
CE QUE CE SCRIPT AJOUTE — deux mesures separees, comme demande :

    valid_vote_ratio = votes_valides / observations_totales
        (une piste "3 papule / 6 None" et une piste "3 papule / 1 None"
        avaient la MEME "part majoritaire" dans l'audit precedent — ce
        chiffre les distingue)
    majority_share    = votes_de_la_classe_majoritaire / votes_VALIDES
        (la marge de la decision, une fois les None ecartes)

TROIS ETATS, pas un booleen :
    CONFIRMEE  — valid_vote_ratio ET majority_share au-dessus de la porte
                 -> comptee dans le rapport final
    INCERTAINE — signal present mais insuffisant/incoherent -> PAS comptee
                 dans le score, mais distinguee du bruit (pas supprimee de
                 l'analyse, juste non comptabilisee — l'idee du produit)
    REJETEE    — aucun vote valide du tout

Porte testee sur une petite grille (pas un seul chiffre invente, une
sensibilite mesuree) : valid_vote_ratio in {0.3, 0.5}, majority_share in
{0.6, 0.8} — 4 combinaisons, a cote de MOYENNE et VOTE NAIF pour reference.

Cas dedies L1 (borderline reel) et L8 (piste contaminee), session par
session, sous chaque variante — la question posee par la demande : "le
gate rejette-t-il L1 proprement sans détruire tout le recall, et
detecte-t-il l'incoherence de L8 ?"

Rien n'est modifie en production.

Usage :
    python3 backend/tools/vote_gate_bench.py
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
from backend.tools.lesion_association_bench import _contamination, _fragmentation_integrite  # noqa: E402
from backend.tools.per_view_recall_bench import _evaluer, _fausse_evolution  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
GRILLE_PORTE = [(0.3, 0.6), (0.3, 0.8), (0.5, 0.6), (0.5, 0.8)]


def _evidence(p: dict, n_vues: int, rayon: float) -> float:
    obs = p["obs"]; k = len(obs)
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
    d = _classify(sum(reds)/k, sum(darks)/k, sum(yellows)/k, sum(core_ls)/k,
                 sum(core_ss)/k, sum(skin_ss)/k, sum(r_pxs)/k, sum(ppms)/k, src_dom)
    return d, ("CONFIRMEE" if d is not None else "REJETEE"), None, None


def _decision_vote_naif(p: dict):
    votes_valides = [o["decision_0"] for o in p["obs"] if o["decision_0"] is not None]
    n = len(p["obs"])
    ratio = len(votes_valides) / n if n else 0.0
    if not votes_valides:
        return None, "REJETEE", ratio, 0.0
    majoritaire = max(set(votes_valides), key=votes_valides.count)
    share = votes_valides.count(majoritaire) / len(votes_valides)
    return majoritaire, "CONFIRMEE", ratio, share


def _decision_vote_porte(p: dict, ratio_min: float, share_min: float):
    votes_valides = [o["decision_0"] for o in p["obs"] if o["decision_0"] is not None]
    n = len(p["obs"])
    ratio = len(votes_valides) / n if n else 0.0
    if not votes_valides:
        return None, "REJETEE", ratio, 0.0
    majoritaire = max(set(votes_valides), key=votes_valides.count)
    share = votes_valides.count(majoritaire) / len(votes_valides)
    if ratio >= ratio_min and share >= share_min:
        return majoritaire, "CONFIRMEE", ratio, share
    return None, "INCERTAINE", ratio, share


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

    def _mesurer(decideur_fn):
        recalls, precisions, doublons_l = [], [], []
        integrites, fragmentations, contams = [], [], []
        filtres = []
        etats_compte = {"CONFIRMEE": 0, "INCERTAINE": 0, "REJETEE": 0}
        for pistes_brutes, vues_candidats, verites_avec_obs in zip(pistes_par_session, sessions, verites_avec_obs_par_session):
            n_vues = len(vues_candidats)
            gardees, idx_confirmees = [], set()
            for i, p in enumerate(pistes_brutes):
                ev = _evidence(p, n_vues, RAYON_MATCH_ANCIEN)
                d, etat, ratio, share = decideur_fn(p)
                etat_final = etat if ev >= SEUIL_EVIDENCE else "REJETEE"
                etats_compte[etat_final] += 1
                if etat_final == "CONFIRMEE":
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
                "contamination": moy(contams), "etats": etats_compte}

    print("=" * 110)
    print("BENCHMARK : moyenne vs vote naif vs vote gated (rayon=0.05, tracker inchange)")
    print("=" * 110)
    print(f"{'variante':<28} {'recall':>7} {'precision':>10} {'doublons':>9} {'faux-evt':>9} "
          f"{'integrite':>10} {'fragment.':>10} {'contam.':>8}  etats(C/I/R)")

    resultats = {}
    for nom, fn in (("MOYENNE", _decision_moyenne), ("VOTE NAIF", _decision_vote_naif)):
        r = _mesurer(fn)
        resultats[nom] = r
        e = r["etats"]
        print(f"{nom:<28} {r['recall']:>7.2f} {r['precision']:>10.2f} {r['doublons']:>9.2f} "
              f"{r['faux_evt']:>9.2f} {r['integrite']:>10.2f} {r['fragmentation']:>10.2f} "
              f"{r['contamination']:>8.2f}  {e['CONFIRMEE']}/{e['INCERTAINE']}/{e['REJETEE']}")

    for ratio_min, share_min in GRILLE_PORTE:
        nom = f"VOTE GATE r>={ratio_min} s>={share_min}"
        r = _mesurer(lambda p, rm=ratio_min, sm=share_min: _decision_vote_porte(p, rm, sm))
        resultats[nom] = r
        e = r["etats"]
        print(f"{nom:<28} {r['recall']:>7.2f} {r['precision']:>10.2f} {r['doublons']:>9.2f} "
              f"{r['faux_evt']:>9.2f} {r['integrite']:>10.2f} {r['fragmentation']:>10.2f} "
              f"{r['contamination']:>8.2f}  {e['CONFIRMEE']}/{e['INCERTAINE']}/{e['REJETEE']}")

    print(f"\nReference production N=3 : recall=0.84  precision=0.58  doublons=0.38  faux-evt=6.57")

    # ══════════════════════════════════════════════════════════════════
    # Cas dedies L1 (borderline) et L8 (contaminee)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("CAS DEDIES : L1 (signal borderline reel) et L8 (piste suspectee contaminee)")
    print("=" * 110)
    porte_principale = (0.5, 0.8)

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
            n_ev = _evidence(piste, len(vues_candidats), RAYON_MATCH_ANCIEN)
            _, etat_moy, _, _ = _decision_moyenne(piste)
            _, etat_vote, ratio, share = _decision_vote_naif(piste)
            _, etat_porte, _, _ = _decision_vote_porte(piste, *porte_principale)
            print(f"  session {s} : {len(piste['obs'])} obs, evidence={n_ev:.2f}, "
                  f"valid_ratio={ratio:.2f}, majority_share={share:.2f}  |  "
                  f"MOYENNE={etat_moy}  VOTE={etat_vote}  GATE={etat_porte}")

    print("\nRien modifie en production.")


if __name__ == "__main__":
    run()
