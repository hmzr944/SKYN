"""Track Purity Gate : coherence_photo mesuree separement du vote, comme
une question DIFFERENTE ("ce track est-il pur ?") plutot qu'une 5e
composante moyennee de l'evidence.

────────────────────────────────────────────────────────────────────────
CE QUE `vote_gate_bench.py` A MONTRE, ET LA LIMITE QU'IL A REVELEE.

Le vote-gate (ratio de votes valides >= 0,5, majorite >= 0,8) a resolu le
mode d'echec de L1 (signal epars/faible : valid_ratio tres bas -> track
correctement retrograde en INCERTAINE) sans sacrifier la precision (0,75,
au-dessus meme de la moyenne). Mais il a laisse passer L8 (piste
contaminee) dans les 6 sessions, identique au vote naif — parce que les
observations contaminantes recoivent `decision_0=None` plutot qu'une
classe CONCURRENTE, le vote ne voit donc aucun desaccord a punir.

Ce script teste l'hypothese : `coherence_photo` (deja calculee comme une
des 5 dimensions de l'evidence, noyee dans une moyenne a poids egaux)
peut-elle devenir une PORTE independante plutot qu'une composante
moyennee, et rattraper specifiquement L8 sans abimer L1 ni le reste ?

────────────────────────────────────────────────────────────────────────
DEMARCHE : mesurer AVANT de choisir un seuil.

Etape 1 — sur tous les tracks CONFIRMES par le vote-gate seul (sans porte
de purete), on releve `coherence_photo` et on les etiquette : "L8 (piste
contaminee connue)", "autre verite terrain", ou "faux positif" (ne
correspond a aucune verite terrain a portee). On regarde si L8 se separe
reellement de la distribution du reste — pas suppose, mesure.

Etape 2 — seulement alors, un ou deux seuils informes par cette mesure
sont testes comme porte de purete AJOUTEE au vote-gate deja fixe (rayon,
tracking, vote-gate : STRICTEMENT inchanges — une seule variable de plus).

Benchmarks obligatoires, comme demande : recall (brut ET sur lesions
detectables, plafond connu 7/8 — pas 8/8), precision, doublons,
faux-evenements, integrite, fragmentation, contamination, et le
comportement dedie de L1 et L8.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/track_purity_gate_bench.py
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
RATIO_MIN, SHARE_MIN = 0.5, 0.8  # le vote-gate deja retenu, fige pour cette experience
PLAFOND_DETECTABLE = 7  # meme plafond connu que tous les bancs precedents


def _dimensions(p: dict, n_vues: int, rayon: float) -> dict:
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
    evidence = (persistance + evidence_signal + coherence_position + coherence_forme + coherence_photo) / 5.0
    return {"persistance": persistance, "evidence_signal": evidence_signal,
            "coherence_position": coherence_position, "coherence_forme": coherence_forme,
            "coherence_photo": coherence_photo, "evidence": evidence}


def _decision_vote_porte(p: dict, ratio_min: float = RATIO_MIN, share_min: float = SHARE_MIN):
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

    # ══════════════════════════════════════════════════════════════════
    # ETAPE 1 — mesurer coherence_photo, categorisee, AVANT de choisir un seuil
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("ETAPE 1 : distribution de coherence_photo sur les tracks CONFIRMES par le vote-gate seul")
    print("=" * 100)

    categories = {"L8 (contaminee connue)": [], "autre verite terrain": [], "faux positif": []}
    for vues_candidats, pistes_brutes in zip(sessions, pistes_par_session):
        n_vues = len(vues_candidats)
        for p in pistes_brutes:
            dims = _dimensions(p, n_vues, RAYON_MATCH_ANCIEN)
            if dims["evidence"] < SEUIL_EVIDENCE:
                continue
            _, etat, _, _ = _decision_vote_porte(p)
            if etat != "CONFIRMEE":
                continue
            correspond = [i for i, gt in enumerate(verite)
                         if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if 7 in correspond:  # L8 = index 7
                categories["L8 (contaminee connue)"].append(dims["coherence_photo"])
            elif correspond:
                categories["autre verite terrain"].append(dims["coherence_photo"])
            else:
                categories["faux positif"].append(dims["coherence_photo"])

    for nom, valeurs in categories.items():
        if valeurs:
            print(f"  {nom:<26} n={len(valeurs):>3}  moyenne={moy(valeurs):.3f}  "
                  f"min={min(valeurs):.3f}  max={max(valeurs):.3f}")
        else:
            print(f"  {nom:<26} n=0")

    # ══════════════════════════════════════════════════════════════════
    # ETAPE 2 — porte de purete, informee par la mesure ci-dessus
    # ══════════════════════════════════════════════════════════════════
    l8_max = max(categories["L8 (contaminee connue)"]) if categories["L8 (contaminee connue)"] else 0.0
    autres_min = min(categories["autre verite terrain"]) if categories["autre verite terrain"] else 1.0
    print(f"\nL8 max mesure = {l8_max:.3f}   autres verites min mesure = {autres_min:.3f}")
    if l8_max < autres_min:
        print("-> separation nette : un seuil entre les deux existe naturellement.")
    else:
        print("-> PAS de separation nette entre L8 et les autres verites — teste quand meme "
              "un seuil pres du maximum de L8, en connaissance de cause.")
    seuils_testes = sorted(set(round(v, 2) for v in [l8_max + 0.02, (l8_max + autres_min) / 2, autres_min]))

    def _mesurer(decideur_purete):
        recalls, precisions, doublons_l = [], [], []
        integrites, fragmentations, contams = [], [], []
        filtres = []
        for pistes_brutes, vues_candidats, verites_avec_obs in zip(pistes_par_session, sessions, verites_avec_obs_par_session):
            n_vues = len(vues_candidats)
            gardees, idx_confirmees = [], set()
            for i, p in enumerate(pistes_brutes):
                dims = _dimensions(p, n_vues, RAYON_MATCH_ANCIEN)
                if dims["evidence"] < SEUIL_EVIDENCE:
                    continue
                d, etat, _, _ = _decision_vote_porte(p)
                if etat != "CONFIRMEE":
                    continue
                if not decideur_purete(dims):
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
        r_m = moy(recalls)
        return {"recall": r_m, "recall_detectable": min(1.0, r_m * len(verite) / PLAFOND_DETECTABLE),
                "precision": moy(precisions), "doublons": moy(doublons_l), "faux_evt": moy(faux_evt),
                "integrite": moy(integrites), "fragmentation": moy(fragmentations), "contamination": moy(contams)}

    print("\n" + "=" * 100)
    print("ETAPE 2 : benchmark complet")
    print("=" * 100)
    print(f"{'variante':<38} {'recall':>7} {'rec.detect':>10} {'precision':>10} {'doublons':>9} "
          f"{'faux-evt':>9} {'integrite':>10} {'fragment.':>10} {'contam.':>8}")

    # Reference MOYENNE (calcul complet, pas juste re-affichage du chiffre precedent)
    def _decision_moyenne_complet(p):
        obs = p["obs"]; k = len(obs)
        reds = [o["red"] for o in obs]; darks = [o["dark"] for o in obs]; yellows = [o["yellow"] for o in obs]
        core_ls = [o["core_l"] for o in obs]; core_ss = [o["core_s"] for o in obs]; skin_ss = [o["skin_s"] for o in obs]
        r_pxs = [o["r_px"] for o in obs]; ppms = [o["px_per_mm"] for o in obs]
        src_dom = max(set(o["src"] for o in obs), key=lambda s: sum(1 for o in obs if o["src"] == s))
        return _classify(sum(reds)/k, sum(darks)/k, sum(yellows)/k, sum(core_ls)/k,
                         sum(core_ss)/k, sum(skin_ss)/k, sum(r_pxs)/k, sum(ppms)/k, src_dom)

    recalls, precisions, doublons_l, filtres = [], [], [], []
    integrites, fragmentations, contams = [], [], []
    for pistes_brutes, vues_candidats, verites_avec_obs in zip(pistes_par_session, sessions, verites_avec_obs_par_session):
        n_vues = len(vues_candidats)
        gardees, idx_confirmees = [], set()
        for i, p in enumerate(pistes_brutes):
            dims = _dimensions(p, n_vues, RAYON_MATCH_ANCIEN)
            if dims["evidence"] < SEUIL_EVIDENCE:
                continue
            if _decision_moyenne_complet(p) is not None:
                gardees.append({"x": p["x"], "y": p["y"]}); idx_confirmees.add(i)
        verite_xy = [(g["x"], g["y"]) for g in verite]
        tp, fn, fp, r, prec, dbl = _evaluer(gardees, verite_xy, RAYON_MATCH_ANCIEN)
        recalls.append(r); precisions.append(prec); doublons_l.append(dbl); filtres.append(gardees)
        integ, frag = _fragmentation_integrite(pistes_brutes, verites_avec_obs)
        integrites.extend(integ); fragmentations.extend(frag)
        contams.extend(_contamination(pistes_brutes, verites_avec_obs, confirmees_only_idx=idx_confirmees))
    faux_evt = [_fausse_evolution(filtres[i], filtres[i+1], RAYON_MATCH_ANCIEN) for i in range(len(filtres)-1)]
    r_m = moy(recalls)
    resultats = {"MOYENNE (reference)": {"recall": r_m, "recall_detectable": min(1.0, r_m*len(verite)/PLAFOND_DETECTABLE),
                 "precision": moy(precisions), "doublons": moy(doublons_l), "faux_evt": moy(faux_evt),
                 "integrite": moy(integrites), "fragmentation": moy(fragmentations), "contamination": moy(contams)}}

    resultats["VOTE-GATE seul (coherence_photo moyennee)"] = _mesurer(lambda dims: True)
    for seuil in seuils_testes:
        resultats[f"VOTE-GATE + PURETE >= {seuil:.2f}"] = _mesurer(lambda dims, s=seuil: dims["coherence_photo"] >= s)

    for nom, r in resultats.items():
        print(f"{nom:<38} {r['recall']:>7.2f} {r['recall_detectable']:>10.2f} {r['precision']:>10.2f} "
              f"{r['doublons']:>9.2f} {r['faux_evt']:>9.2f} {r['integrite']:>10.2f} "
              f"{r['fragmentation']:>10.2f} {r['contamination']:>8.2f}")

    print(f"\nCible : recall ~0.73+ (ou recall_detectable equivalent), faux-evt -> <= 2.60, "
          f"doublons sans remonter. Reference production N=3 : recall=0.84 precision=0.58 "
          f"doublons=0.38 faux-evt=6.57.")

    # ══════════════════════════════════════════════════════════════════
    # Cas dedies L1 / L8, avec et sans porte de purete
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("CAS DEDIES avec la meilleure porte de purete testee")
    print("=" * 100)
    meilleur_seuil = seuils_testes[len(seuils_testes)//2] if seuils_testes else 0.5

    for cible_id, cible_idx in (("L1", 0), ("L8", 7)):
        gt = verite[cible_idx]
        print(f"\n{cible_id} (porte de purete >= {meilleur_seuil:.2f}) :")
        for s, (pistes_brutes, vues_candidats) in enumerate(zip(pistes_par_session, sessions)):
            proches = [p for p in pistes_brutes
                      if ((p["x"]-gt["x"])**2 + (p["y"]-gt["y"])**2)**0.5 < RAYON_CAPTURE]
            if not proches:
                print(f"  session {s} : aucun candidat a portee")
                continue
            piste = max(proches, key=lambda p: len(p["obs"]))
            dims = _dimensions(piste, len(vues_candidats), RAYON_MATCH_ANCIEN)
            _, etat_vote, ratio, share = _decision_vote_porte(piste)
            etat_final = etat_vote if (etat_vote == "CONFIRMEE" and dims["coherence_photo"] >= meilleur_seuil) else \
                        ("REJETEE_PURETE" if etat_vote == "CONFIRMEE" else etat_vote)
            print(f"  session {s} : coherence_photo={dims['coherence_photo']:.2f}  "
                  f"valid_ratio={ratio:.2f} majority_share={share:.2f}  "
                  f"VOTE-GATE={etat_vote}  AVEC PURETE={etat_final}")

    print("\nRien modifie en production.")


if __name__ == "__main__":
    run()
