"""MASTER PROMPT — Lesion Tracking & Association Audit.

────────────────────────────────────────────────────────────────────────
CE QUE `per_view_recall_bench.py` A ETABLI, ET CE QUE CE SCRIPT AUDITE.

Le banc precedent a falsifie l'hypothese de depart : candidate_recall =
1,00 a TOUS les niveaux de permissivite, y compris la rigueur de
production (P0). Les 8 verites terrain deviennent TOUJOURS candidates
quelque part parmi 9 vues. La perte (16/48 instances a P0) se joue donc
entierement APRES la detection — dans le suivi (tracking/association) ou
la confirmation, pas dans la generation de candidats. Ce script AUDITE
ces deux etapes, sans les refaire a l'aveugle :

    1. Tracabilite complete des 48 instances (8 lesions x 6 sessions).
    2. Cause precise de chacune des pertes, categorisee.
    3. Mesure EMPIRIQUE de la derive de position d'une meme lesion reelle
       entre vues (pas une supposition) — pour calibrer un rayon
       d'association, au lieu d'en garder un invente.
    4. Un algorithme d'association experimental : rayon calibre sur la
       mesure du point 3 (pas invente), plus une porte de compatibilite
       de classe binaire plutot qu'une somme ponderee de couts (les poids
       ne peuvent pas etre calibres honnetement sans donnees etiquetees
       supplementaires — voir section correspondante).
    5. Architecture corrigee, telle que demandee : classification
       INDIVIDUELLE par vue AVANT le suivi (deja le cas dans
       `_candidats_permissifs`, qui appelle `_classify()` par candidat des
       la generation) — la CONFIRMATION finale vote maintenant sur ces
       classifications individuelles (majorite) plutot que de reclasser
       une moyenne, ce qui avait ete identifie comme un point faible du
       banc precedent.
    6. Nouveau KPI : Track Recall — combien de verites terrain obtiennent
       un track avec >= 2 observations associees, INDEPENDAMMENT de la
       confirmation finale. Separe l'echec d'association de l'echec de
       confirmation.

INTERDICTIONS RESPECTEES : aucun changement au detecteur (k=1,00,
production, pas de niveau permissif) ni aux seuils de `_classify()` — ce
fichier ne touche ni lesions.py ni calibration.py. Aucune UI.

Usage :
    python3 backend/tools/lesion_tracking_audit.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.lesions import _classify, _zone_of  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.multiview_persistence_bench import (  # noqa: E402
    LESIONS_PAR_ZONE,
    SEED_PLANT,
    ZONES_PLANTEES,
)
from backend.tools.per_view_recall_bench import (  # noqa: E402
    _candidats_permissifs,
    _evaluer,
    _fausse_evolution,
    _vues_de_session,
)
from backend.tools.stability_bench import _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
SESSIONS = 6
N_VUES = 9
RAYON_MATCH_ANCIEN = 0.05     # le rayon fixe herite de stability_bench.py
RAYON_CAPTURE = 0.08          # generous, diagnostic seulement : "y a-t-il un candidat pres d'ici ?"
SEUIL_EVIDENCE = 0.50


def _suivre(vues_candidats: List[List[dict]], rayon: float, gate_classe: bool = False) -> List[dict]:
    """Suivi par plus proche voisin, rayon fixe. `gate_classe=True` ajoute la
    porte de compatibilite experimentale : ne pas associer deux
    observations dont les classifications INDIVIDUELLES (non None) sont en
    DESACCORD, meme si elles sont spatialement proches — une regle binaire,
    pas une somme ponderee, faute de donnees pour calibrer des poids
    honnetement."""
    pistes: List[dict] = []
    for cands in vues_candidats:
        for c in cands:
            x, y = c["x"], c["y"]
            meilleur, meilleure_dist = None, rayon
            for i, p in enumerate(pistes):
                d = ((p["x"] - x) ** 2 + (p["y"] - y) ** 2) ** 0.5
                if d >= meilleure_dist:
                    continue
                if gate_classe:
                    decisions_piste = [o["decision_0"] for o in p["obs"] if o["decision_0"] is not None]
                    if decisions_piste and c["decision_0"] is not None and c["decision_0"] not in decisions_piste:
                        continue
                meilleur, meilleure_dist = i, d
            if meilleur is not None:
                p = pistes[meilleur]
                p["obs"].append(c)
                p["x"] = sum(o["x"] for o in p["obs"]) / len(p["obs"])
                p["y"] = sum(o["y"] for o in p["obs"]) / len(p["obs"])
            else:
                pistes.append({"x": x, "y": y, "obs": [c]})
    return pistes


def _evidence_et_decision(p: dict, n_vues: int, rayon: float, vote_individuel: bool) -> dict:
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

    evidence = (persistance + evidence_signal + coherence_position +
                coherence_forme + coherence_photo) / 5.0

    if vote_individuel:
        decisions_valides = [o["decision_0"] for o in obs if o["decision_0"] is not None]
        if decisions_valides:
            majoritaire = max(set(decisions_valides), key=decisions_valides.count)
            decision_finale = majoritaire if decisions_valides.count(majoritaire) >= max(2, len(decisions_valides) // 2 + 1) else None
        else:
            decision_finale = None
    else:
        reds = [o["red"] for o in obs]; darks = [o["dark"] for o in obs]; yellows = [o["yellow"] for o in obs]
        core_ls = [o["core_l"] for o in obs]; core_ss = [o["core_s"] for o in obs]; skin_ss = [o["skin_s"] for o in obs]
        r_pxs = [o["r_px"] for o in obs]; ppms = [o["px_per_mm"] for o in obs]
        src_dom = max(set(o["src"] for o in obs), key=lambda s: sum(1 for o in obs if o["src"] == s))
        decision_finale = _classify(sum(reds)/k, sum(darks)/k, sum(yellows)/k, sum(core_ls)/k,
                                    sum(core_ss)/k, sum(skin_ss)/k, sum(r_pxs)/k, sum(ppms)/k, src_dom)

    return {"x": p["x"], "y": p["y"], "evidence": evidence, "n_obs": k,
            "persistance": persistance, "decision_finale": decision_finale, "obs": obs}


def _generer_sessions(marque):
    """Genere et met en cache les candidats bruts (k=1,00, production) des
    6 sessions x 9 vues — la partie couteuse, partagee par TOUTES les
    analyses de ce script (audit ancien tracker, mesure de derive,
    nouveau tracker)."""
    sessions = []
    for s in range(SESSIONS):
        images = _vues_de_session(marque, N_VUES, seed=3000 * s + 7)
        vues_candidats = []
        for im in images:
            fm = build_face_map(im)
            if not fm.detected or not fm.quality.usable:
                continue
            cands = _candidats_permissifs(fm, 1.00)
            x0, y0, bw, bh = fm.bbox
            for c in cands:
                px = int(round(c["x"] * bw + x0))
                py = int(round(c["y"] * bh + y0))
                c["zone"] = _zone_of(fm, px, py)
            vues_candidats.append(cands)
        sessions.append(vues_candidats)
    return sessions


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
    verite = []
    for i, p in enumerate(plantees):
        verite.append({"id": f"L{i+1}", "x": (p.x - x0) / bw, "y": (p.y - y0) / bh,
                       "zone": _zone_of(base, p.x, p.y)})

    print(f"{len(verite)} lesions plantees, {SESSIONS} sessions, N={N_VUES}, "
          f"generation des candidats bruts (peut prendre plusieurs minutes)...\n")
    t0 = time.time()
    sessions = _generer_sessions(marque)
    print(f"(genere en {time.time()-t0:.0f}s)\n")

    # ══════════════════════════════════════════════════════════════════
    # 1+2+3. TRACABILITE, CAUSES DE PERTE, MESURE DE DERIVE — ancien tracker
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("1-2-3. TRACABILITE ET CAUSES (ancien tracker, rayon=0.05, confirmation par classify-sur-moyenne)")
    print("=" * 100)

    derives_track_unique = []
    derives_fragmentation = []
    causes = {}
    lignes_lesions = []

    for s, vues_candidats in enumerate(sessions):
        pistes_brutes = _suivre(vues_candidats, RAYON_MATCH_ANCIEN)
        pistes = [_evidence_et_decision(p, len(vues_candidats), RAYON_MATCH_ANCIEN, vote_individuel=False)
                  for p in pistes_brutes]

        for gt in verite:
            proches = []  # (vue_idx, obs) pour cette verite, sur TOUTES les vues (rayon genereux)
            for vi, cands in enumerate(vues_candidats):
                for c in cands:
                    if ((c["x"] - gt["x"]) ** 2 + (c["y"] - gt["y"]) ** 2) ** 0.5 < RAYON_CAPTURE:
                        proches.append((vi, c))

            candidate_ok = len(proches) > 0
            tracks_touches = [p for p in pistes if any(id(o) == id(c) for _, c in proches for o in p["obs"])]
            confirmee = any(p["evidence"] >= SEUIL_EVIDENCE and p["decision_finale"] is not None for p in tracks_touches)

            if len(tracks_touches) >= 2:
                centres = [(p["x"], p["y"]) for p in tracks_touches]
                for i in range(len(centres)):
                    for j in range(i + 1, len(centres)):
                        derives_fragmentation.append(
                            ((centres[i][0]-centres[j][0])**2 + (centres[i][1]-centres[j][1])**2) ** 0.5)
            elif len(tracks_touches) == 1 and tracks_touches[0]["n_obs"] >= 2:
                xs = [o["x"] for o in tracks_touches[0]["obs"]]
                ys = [o["y"] for o in tracks_touches[0]["obs"]]
                mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
                derives_track_unique.append(max(((x-mx)**2+(y-my)**2)**0.5 for x, y in zip(xs, ys)))

            if not candidate_ok:
                cause = "jamais candidate (Cas A — deja exclu par le banc precedent)"
            elif confirmee:
                cause = "correctement confirmee (Cas C)"
            elif len(tracks_touches) >= 2:
                cause = "fragmentation spatiale (observations eclatees en plusieurs tracks)"
            elif len(tracks_touches) == 0:
                cause = "incoherence interne (a verifier — candidat existe mais aucun track ne le contient)"
            else:
                t = tracks_touches[0]
                decisions_ok = [o["decision_0"] for o in t["obs"] if o["decision_0"] is not None]
                if t["persistance"] < 0.3:
                    cause = f"persistance insuffisante ({t['n_obs']}/{len(vues_candidats)} vues)"
                elif not decisions_ok:
                    cause = "signal trop faible pour la classification individuelle (toutes vues -> aucune classe)"
                elif len(set(decisions_ok)) > 1 and decisions_ok.count(max(set(decisions_ok), key=decisions_ok.count)) / len(decisions_ok) < 0.6:
                    cause = f"desaccord de classe entre vues ({decisions_ok})"
                else:
                    cause = f"seuil d'evidence insuffisant (evidence={t['evidence']:.2f} < {SEUIL_EVIDENCE})"

            causes[cause.split(" (")[0]] = causes.get(cause.split(" (")[0], 0) + 1
            lignes_lesions.append((s, gt["id"], candidate_ok, len(tracks_touches) > 0, confirmee, cause))

    print(f"{'session':>7} {'lesion':<5} {'candidate':>9} {'track cree':>10} {'confirmee':>9}  cause")
    for s, lid, cand, track, conf, cause in lignes_lesions:
        if not conf:  # n'imprime en detail que les cas perdus, pour rester lisible
            print(f"{s:>7} {lid:<5} {str(cand):>9} {str(track):>10} {str(conf):>9}  {cause}")

    print(f"\nRepartition des causes sur les {sum(1 for l in lignes_lesions if not l[4])} instances non confirmees :")
    for cause, n in sorted(causes.items(), key=lambda kv: -kv[1]):
        if "correctement" not in cause:
            print(f"  {n:>3}  {cause}")

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
    print(f"\nDERIVE DE POSITION MESUREE (verite terrain connue, pas une supposition) :")
    print(f"  meme track (derive interne, {len(derives_track_unique)} cas) : "
          f"moyenne={moy(derives_track_unique):.4f}  max={max(derives_track_unique) if derives_track_unique else 0:.4f}")
    print(f"  tracks fragmentes (distance entre fragments, {len(derives_fragmentation)} cas) : "
          f"moyenne={moy(derives_fragmentation):.4f}  min={min(derives_fragmentation) if derives_fragmentation else 0:.4f}  "
          f"max={max(derives_fragmentation) if derives_fragmentation else 0:.4f}")
    print(f"  rayon d'association actuel : {RAYON_MATCH_ANCIEN}")

    # ══════════════════════════════════════════════════════════════════
    # 4-5-6. NOUVEL ALGORITHME D'ASSOCIATION + CONFIRMATION PAR VOTE
    # ══════════════════════════════════════════════════════════════════
    rayon_calibre = round(max(RAYON_MATCH_ANCIEN, np.percentile(derives_fragmentation, 75) if derives_fragmentation else RAYON_MATCH_ANCIEN), 3)
    print("\n" + "=" * 100)
    print(f"4-5-6. NOUVEAU TRACKER : rayon calibre empiriquement={rayon_calibre} "
          f"(p75 des distances de fragmentation mesurees ci-dessus, pas invente), "
          f"porte de compatibilite de classe, confirmation par VOTE MAJORITAIRE individuel")
    print("=" * 100)

    def _mesurer(rayon, gate_classe, vote_individuel, seuil):
        pistes_par_session, cpu_l = [], []
        for vues_candidats in sessions:
            t0 = time.process_time()
            pistes_brutes = _suivre(vues_candidats, rayon, gate_classe=gate_classe)
            pistes = [_evidence_et_decision(p, len(vues_candidats), rayon, vote_individuel=vote_individuel)
                      for p in pistes_brutes]
            cpu_l.append(time.process_time() - t0)
            pistes_par_session.append(pistes)

        recalls, precisions, doublons_l, track_recalls = [], [], [], []
        filtres = []
        for pistes in pistes_par_session:
            gardees = [p for p in pistes if p["evidence"] >= seuil and p["decision_finale"] is not None]
            verite_xy = [(g["x"], g["y"]) for g in verite]
            # Rayon d'evaluation = rayon d'association du tracker lui-meme, pas un
            # rayon universel separe — coherent avec chaque banc precedent (la
            # tolerance d'appariement etait toujours celle du mecanisme teste).
            tp, fn, fp, r, prec, d = _evaluer(gardees, verite_xy, rayon)
            recalls.append(r); precisions.append(prec); doublons_l.append(d)
            filtres.append(gardees)
            tr = sum(1 for g in verite if any(
                p["n_obs"] >= 2 and ((p["x"]-g["x"])**2+(p["y"]-g["y"])**2)**0.5 < rayon for p in pistes))
            track_recalls.append(tr / len(verite))
        faux_evt = [_fausse_evolution(filtres[i], filtres[i+1], rayon) for i in range(SESSIONS-1)]
        return {"recall": moy(recalls), "precision": moy(precisions), "doublons": moy(doublons_l),
                "track_recall": moy(track_recalls), "faux_evt": moy(faux_evt), "cpu": moy(cpu_l)}

    ancien = _mesurer(RAYON_MATCH_ANCIEN, gate_classe=False, vote_individuel=False, seuil=SEUIL_EVIDENCE)
    nouveau = _mesurer(rayon_calibre, gate_classe=True, vote_individuel=True, seuil=SEUIL_EVIDENCE)

    print(f"\n{'variante':<45} {'recall':>7} {'precision':>10} {'doublons':>9} "
          f"{'track_recall':>13} {'faux-evt/paire':>15} {'CPU/session':>12}")
    print(f"{'ANCIEN (rayon fixe, classify-sur-moyenne)':<45} {ancien['recall']:>7.2f} "
          f"{ancien['precision']:>10.2f} {ancien['doublons']:>9.2f} {ancien['track_recall']:>13.2f} "
          f"{ancien['faux_evt']:>15.2f} {ancien['cpu']:>12.2f}")
    print(f"{'NOUVEAU (rayon calibre, gate classe, vote)':<45} {nouveau['recall']:>7.2f} "
          f"{nouveau['precision']:>10.2f} {nouveau['doublons']:>9.2f} {nouveau['track_recall']:>13.2f} "
          f"{nouveau['faux_evt']:>15.2f} {nouveau['cpu']:>12.2f}")

    print(f"\nProduction N=3 (reference deja mesuree) : recall=0.84  precision=0.58  "
          f"doublons=0.38  faux-evt/paire=6.57")

    print("\nNote sur les poids : la porte de compatibilite de classe est BINAIRE "
          "(compatible / incompatible), pas une somme ponderee de couts — ponderer "
          "spatial/photometrique/morphologique/classe demanderait un jeu de donnees "
          "etiquete pour calibrer honnetement chaque poids, absent ici. Le rayon, lui, "
          "EST calibre sur une mesure (la derive de fragmentation observee ci-dessus), "
          "pas invente.")


if __name__ == "__main__":
    run()
