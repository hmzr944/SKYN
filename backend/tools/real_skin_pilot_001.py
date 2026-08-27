"""Real-Skin Pilot — Subject 001.

────────────────────────────────────────────────────────────────────────
CE QUE CE PILOTE EST, ET CE QU'IL N'EST PAS.

Ce n'est PAS une preuve que SKYN est precis en general — un seul visage,
une seule personne, un seul phototype, une seule camera ne generalisent a
rien. C'est un test de STABILITE INTRA-PERSONNE : est-ce que le moteur
raconte la meme histoire quand la peau n'a pas change ? C'est exactement
la question centrale de tout ce chantier, testee cette fois sur une vraie
peau plutot que sur des lesions plantees.

Consequence methodologique importante : il n'y a PAS de verite terrain
connue sur une vraie photo. Les metriques recall/precision de tous les
bancs precedents (fondees sur `synth_lesions.plant()`) n'ont pas de sens
ici. Ce script mesure exclusivement de la REPETABILITE — comptes,
positions, fragmentation, faux-evenements — jamais "combien de vraies
lesions SKYN a-t-il trouvees ?", faute de reference.

────────────────────────────────────────────────────────────────────────
DONNEES PERSONNELLES : REGLE ABSOLUE.

L'image source vit HORS du depot Git (`/home/user/real_skin_pilot/subject_001/`,
un chemin en dehors de l'arborescence `SKYN`), et n'est jamais lue par
aucun autre outil de ce depot. Ce script ne l'embarque pas, ne l'encode
pas en base64 dans un fichier commite, et n'imprime que des metriques
(comptes, scores, distances) — jamais l'image elle-meme.

IMPORTANT — environnement ephemere : ce conteneur cloud est reconstruit a
chaque session. Rien ne survit d'une session a l'autre sauf ce qui est
commite dans Git. Puisque l'image ne DOIT PAS etre commitee, elle ne
survivra pas a la fin de cette session — c'est le prix de la regle de
confidentialite ci-dessus, pas un oubli. Pour reutiliser ce pilote plus
tard, l'image devra etre re-fournie.

Usage :
    python3 backend/tools/real_skin_pilot_001.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import analyze_face, analyze_multi  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN, SEUIL_EVIDENCE, _suivre  # noqa: E402
from backend.tools.observation_outlier_bench import (  # noqa: E402
    _decision_vote_porte,
    _dimensions,
    _nettoyer,
)
from backend.tools.per_view_recall_bench import _candidats_permissifs, _vues_de_session  # noqa: E402
from backend.tools.stability_bench import PERTURBATIONS, _appareiller, _b64  # noqa: E402

IMAGE = Path("/home/user/real_skin_pilot/subject_001/capture_001.jpg")
SESSIONS = 6
SEUIL_NETTOYAGE = 9.5
SEUIL_PURETE = 0.5


def _generer_sessions_n(img, n, sessions):
    out = []
    for s in range(sessions):
        images = _vues_de_session(img, n, seed=3000 * s + 7)
        vues = []
        for im in images:
            fm = build_face_map(im)
            if not fm.detected or not fm.quality.usable:
                continue
            vues.append(_candidats_permissifs(fm, 1.00))
        out.append((images, vues))
    return out


def run() -> None:
    if not IMAGE.exists():
        raise SystemExit(
            f"Pas d'image de pilote a {IMAGE} — attendu, cette image ne survit pas entre "
            f"sessions (regle de confidentialite : jamais commitee). Refournir l'image pour relancer."
        )
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image illisible : {IMAGE}")

    # ══════════════════════════════════════════════════════════════════
    # A. Rapport de base (une seule capture, telle quelle)
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("A. RAPPORT DE BASE (une capture, sans perturbation)")
    print("=" * 100)
    base = analyze_face(_b64(img, quality=100))
    if not base.ok:
        raise SystemExit(f"visage non detecte : {base.diagnosis}")
    print(f"score={base.global_score}  confiance={base.confidence:.2f}  "
          f"phototype={base.phototype}  type_peau={base.skin_type}")
    print(f"lesions={len(base.lesions)}  types={[l['type'] for l in base.lesions]}")
    print(f"zones={[l['zone'] for l in base.lesions]}")
    print(f"qualite={base.quality}  flags={base.flags}")

    # ══════════════════════════════════════════════════════════════════
    # B. Stabilite same-skin, une seule vue (reprend stability_bench.py)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("B. STABILITE SAME-SKIN (une vue, meme methodologie que stability_bench.py)")
    print("=" * 100)
    print(f"{'perturbation':<18} {'score':>7} {'lesions':>9} {'derive_px':>11} {'perdues':>9}")
    deltas_score, deltas_n = [], []
    for p in PERTURBATIONS:
        modifiee = p.applique(img)
        out = analyze_face(_b64(modifiee, quality=p.qualite_jpeg))
        if not out.ok:
            print(f"{p.nom:<18}  ECHEC (visage non detecte apres perturbation)")
            continue
        score_delta = out.global_score - base.global_score
        n_delta = len(out.lesions) - len(base.lesions)
        deltas_score.append(score_delta); deltas_n.append(n_delta)
        appariees = _appareiller(base.lesions, out.lesions)
        derives = [((r["x"]-n["x"])**2+(r["y"]-n["y"])**2)**0.5 for r, n in appariees if n is not None]
        perdues = sum(1 for _, n in appariees if n is None)
        print(f"{p.nom:<18} {score_delta:>+7} {len(out.lesions):>5}({n_delta:>+3}) "
              f"{(sum(derives)/len(derives) if derives else 0):>11.3f} {perdues:>9}")

    moy = lambda xs: sum(xs)/len(xs) if xs else 0.0
    print(f"\n|ecart score| moyen={moy([abs(d) for d in deltas_score]):.1f}  "
          f"|ecart lesions| moyen={moy([abs(d) for d in deltas_n]):.1f}")

    # ══════════════════════════════════════════════════════════════════
    # C. Repetabilite multi-vue : production N=3 vs N=9, meme peau
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("C. REPETABILITE MULTI-VUE, MEME PEAU (analyze_multi production, non modifie)")
    print("=" * 100)
    print(f"{'N vues':>7} {'|Delta score| moy':>18} {'|Delta compte| moy':>19} {'CPU/session':>13}")
    for n in (3, 9):
        sessions_scores, sessions_counts, cpu_l = [], [], []
        for s in range(SESSIONS):
            images = _vues_de_session(img, n, seed=1000 * n + 17 * s)
            t0 = time.process_time()
            out = analyze_multi(images) if n > 1 else analyze_face(images[0])
            cpu_l.append(time.process_time() - t0)
            sessions_scores.append(out.global_score)
            sessions_counts.append(sum(out.lesion_counts.values()))
        d_score = [abs(sessions_scores[i+1]-sessions_scores[i]) for i in range(SESSIONS-1)]
        d_count = [abs(sessions_counts[i+1]-sessions_counts[i]) for i in range(SESSIONS-1)]
        print(f"{n:>7} {moy(d_score):>18.2f} {moy(d_count):>19.2f} {moy(cpu_l):>13.2f}")

    # ══════════════════════════════════════════════════════════════════
    # D. Meme peau, pipeline valide (tracking + nettoyage + purete + vote-gate)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("D. MEME PEAU, PIPELINE MULTI-VUE VALIDE (clean -> purete -> vote-gate), N=3 vs N=9")
    print("=" * 100)
    print(f"{'N vues':>7} {'confirmees/session':<25} {'pistes brutes/session':<25} {'|Delta confirmees| moy':>22}")
    for n in (3, 9):
        sessions_data = _generer_sessions_n(img, n, SESSIONS)
        comptes, comptes_bruts = [], []
        for images, vues_candidats in sessions_data:
            n_vues = len(vues_candidats)
            if n_vues == 0:
                comptes.append(0); comptes_bruts.append(0)
                continue
            pistes_brutes = _suivre(vues_candidats, RAYON_MATCH_ANCIEN)
            comptes_bruts.append(len(pistes_brutes))
            n_confirmees = 0
            for p in pistes_brutes:
                obs = _nettoyer(p["obs"], SEUIL_NETTOYAGE)
                dims = _dimensions(obs, n_vues, RAYON_MATCH_ANCIEN)
                if dims["evidence"] < SEUIL_EVIDENCE or dims["coherence_photo"] < SEUIL_PURETE:
                    continue
                _, etat = _decision_vote_porte(obs)
                if etat == "CONFIRMEE":
                    n_confirmees += 1
            comptes.append(n_confirmees)
        d_count = [abs(comptes[i+1]-comptes[i]) for i in range(SESSIONS-1)]
        print(f"{n:>7} {str(comptes):<25} {str(comptes_bruts):<25} {moy(d_count):>22.2f}")

    print("\n(Pas de mesure de fragmentation/contamination ici : ces metriques exigent une "
          "verite terrain par lesion, absente sur une vraie photo. 'pistes brutes' donne une "
          "idee indirecte du volume de candidats bruts par rapport au compte final confirme.)")

    print("\nAucune image commitee. Aucune modification de production. "
          "Metriques uniquement — voir la note de confidentialite en tete de fichier.")


if __name__ == "__main__":
    run()
