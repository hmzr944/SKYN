"""Chantier Per-View Candidate Recall -> Multi-View Evidence Fusion.

────────────────────────────────────────────────────────────────────────
L'HYPOTHESE TESTEE.

`multiview_evidence_bench.py` a montre que le recall perdu par la fusion
(0,84 en production -> ~0,75 quel que soit le seuil d'evidence, meme le
plus permissif) ne se recupere PAS en assouplissant le filtre de fusion —
donc la perte se joue EN AMONT, au moment ou une vue individuelle decide
seule si un signal devient candidat. Ce banc separe explicitement deux
niveaux, comme demande :

    candidate_threshold    — permissif : combien de blobs une vue laisse
                              entrer dans le pipeline (le k de
                              `_robust_thr`, PAS les regles de `_classify`)
    final_decision_threshold — inchange : la classification finale reste
                              exactement `_classify()` de production,
                              appliquee au signal MOYENNE d'une piste
                              confirmee plutot qu'a une observation unique

Rien dans `_classify()` ni dans les constantes de `calibration.py` n'est
modifie. Seul le `k` passe a `_blob_candidates()` (l'argument, pas une
constante globale) est mis a l'echelle par vue, pour generer le pool de
candidats — exactement le "candidate_threshold permissif" demande.

────────────────────────────────────────────────────────────────────────
NIVEAUX DE PERMISSIVITE (P0 = actuel, k = RED_BLOB_K/DARK_BLOB_K x facteur).

    P0 = x1.00 (production)
    P1 = x0.85
    P2 = x0.70
    P3 = x0.55

────────────────────────────────────────────────────────────────────────
EVIDENCE SCORE — cinq dimensions, poids EGAUX et NON CALIBRES (l'etalonnage
experimental demande couterait un vrai jeu d'entrainement, hors de portee
d'un seul banc offline ; ceci est un point de depart transparent, pas un
resultat calibre) :

    1. persistance temporelle   — fraction des vues qui ont vu le candidat
    2. evidence de signal       — fraction des observations dont le signal
                                   BRUT depasse deja, a lui seul, le seuil
                                   de PRODUCTION (k=x1.00) — pas un
                                   coefficient invente, le seuil reel
    3. coherence spatiale       — les observations restent-elles proches
                                   (std normalisee par le rayon d'appariement) ?
    4. coherence morphologique  — accord de `decision_0` (la classification
                                   `_classify()` REELLE par observation,
                                   y compris "aucune") entre observations
    5. coherence photometrique  — stabilite du signal dominant (rouge ou
                                   sombre) d'une observation a l'autre

La "qualite des frames" est une PORTE (vues `Quality.usable=False`
ecartees avant fusion), pas une 6e moyenne — memes raisons que dans
`multiview_evidence_bench.py`. Piste a moins de 2 observations : les 3
dimensions de coherence valent 0,5 (neutre), pas 1,0 (trivialement
"parfait" sur un seul point).

DECISION FINALE : une piste devient une lesion SEULEMENT SI evidence >=
seuil ET `_classify()` (production, inchangee) sur le signal MOYEN de la
piste renvoie un type. Les deux barrières sont necessaires — c'est la
regle absolue de la section 8.

────────────────────────────────────────────────────────────────────────
PORTEE ASSUMEE : le balayage P0-P3 complet tourne a N=9 vues (la
condition la plus prometteuse du banc precedent) plutot que sur toute la
grille (P x N), pour rester executable en un seul passage. Si un P gagnant
se degage, il est confirme rapidement a N=3 pour verifier qu'il tient
aussi au nombre de vues actuellement en production.

Verite terrain : les 8 lesions plantees deja utilisees dans
`multiview_persistence_bench.py` (memes zones, meme graine) — plafond
CONNU de 7/8 = 87,5 % (voir `multiview_evidence_bench.py`), pas 8/8.

Section 17 (obligatoire) : la configuration gagnante est ensuite testee
sur le same-skin benchmark, cette fois sur les VRAIES lesions ambigues de
la photo de reference plutot que sur les plants synthetiques, pour
verifier que le gain ne se paie pas en instabilite reelle.

Rien n'est modifie en production.

Usage :
    python3 backend/tools/per_view_recall_bench.py
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import calibration as C  # noqa: E402
from backend.skyn_engine.v2.lesions import (  # noqa: E402
    _blob_candidates,
    _classify,
    _local_excess,
    _robust_thr,
)
from backend.skyn_engine.v2.zones import FaceMap, build_face_map  # noqa: E402
from backend.tools.multiview_persistence_bench import (  # noqa: E402
    LESIONS_PAR_ZONE,
    SEED_PLANT,
    ZONES_PLANTEES,
)
from backend.tools.stability_bench import PERTURBATIONS, _b64  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
SESSIONS = 6
RAYON_APPARIEMENT = 0.05
N_PRINCIPAL = 9
N_CONFIRMATION = 3
NIVEAUX = [("P0", 1.00), ("P1", 0.85), ("P2", 0.70), ("P3", 0.55)]
SEUILS_EVIDENCE = [0.40, 0.50, 0.60]
SEUIL_RAPPORTE = 0.50  # utilise pour la matrice de tracabilite Cas A/B/C


# --------------------------------------------------------------------------
def _vues_de_session(marque: np.ndarray, n: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    return [_b64(p.applique(marque), quality=p.qualite_jpeg)
            for p in (rng.choice(PERTURBATIONS) for _ in range(n))]


def _candidats_permissifs(fm: FaceMap, k_facteur: float) -> List[dict]:
    """Genere les candidats bruts d'UNE vue au niveau de permissivite
    demande, et rapporte, PAR CANDIDAT, s'il aurait a lui seul franchi le
    seuil de PRODUCTION (k=x1,00) — c'est ca, la "signal evidence" : pas un
    coefficient invente, le seuil deja valide ailleurs dans ce projet."""
    face_w = max(1.0, float(fm.bbox[2]))
    px_per_mm = face_w / 140.0
    lab = fm.lab
    A = lab[:, :, 1] - 128.0
    B = lab[:, :, 2] - 128.0
    L = fm.l_flat
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]

    mask = fm.skin_mask
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    a_exc = _local_excess(A, mask, sigma_bg)
    l_exc = _local_excess(L, mask, sigma_bg)
    b_exc = _local_excess(B, mask, sigma_bg)

    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)
    for zn in ("sous_yeux_g", "sous_yeux_d"):
        z = fm.zones.get(zn)
        if z is not None and z.available:
            core_mask = cv2.bitwise_and(core_mask, cv2.bitwise_not(z.mask))

    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    core_sel = core_mask > 0
    if core_sel.sum() < 50:
        return []
    thr_red_prod = _robust_thr(a_exc[core_sel], C.RED_BLOB_K)
    thr_dark_prod = _robust_thr((-l_exc)[core_sel], C.DARK_BLOB_K)

    cands = {}
    for cx, cy, area, _ in _blob_candidates(a_exc, core_mask, k_facteur * C.RED_BLOB_K, a_min, a_max):
        cands[(cx, cy)] = (area, "rouge")
    for cx, cy, area, _ in _blob_candidates(-l_exc, core_mask, k_facteur * C.DARK_BLOB_K, a_min, a_max):
        if (cx, cy) not in cands:
            cands[(cx, cy)] = (area, "sombre")

    pts = sorted(cands.items(), key=lambda kv: -kv[1][0])
    min_sep = max(3.0, 1.2 * px_per_mm)
    kept = []
    for (cx, cy), (area, src) in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < min_sep ** 2 for kx, ky, _, _ in kept):
            continue
        kept.append((cx, cy, area, src))

    h, w = mask.shape
    skin_s = float(S[mask > 0].mean())
    x0, y0, bw, bh = fm.bbox
    out = []
    for cx, cy, area, src in kept:
        r_px = float(np.sqrt(area / np.pi))
        rr = max(1, int(round(r_px)))
        yy0, yy1 = max(0, cy - rr), min(h, cy + rr + 1)
        xx0, xx1 = max(0, cx - rr), min(w, cx + rr + 1)
        patch_m = mask[yy0:yy1, xx0:xx1] > 0
        if patch_m.sum() < 3:
            continue
        red = float(a_exc[yy0:yy1, xx0:xx1][patch_m].mean())
        dark = float(l_exc[yy0:yy1, xx0:xx1][patch_m].mean())
        yellow = float(b_exc[yy0:yy1, xx0:xx1][patch_m].mean())
        cr = max(1, int(r_px * 0.5))
        cy0, cy1 = max(0, cy - cr), min(h, cy + cr + 1)
        cx0, cx1 = max(0, cx - cr), min(w, cx + cr + 1)
        core_l = float(l_exc[cy0:cy1, cx0:cx1].mean())
        core_s = float(S[cy0:cy1, cx0:cx1].mean())
        d0 = _classify(red, dark, yellow, core_l, core_s, skin_s, r_px, px_per_mm, src)
        depasse_prod = (red > thr_red_prod) if src == "rouge" else (dark < -thr_dark_prod)
        out.append({
            "x": (cx - x0) / bw, "y": (cy - y0) / bh,
            "red": red, "dark": dark, "yellow": yellow,
            "core_l": core_l, "core_s": core_s, "skin_s": skin_s,
            "r_px": r_px, "px_per_mm": px_per_mm, "src": src,
            "decision_0": d0, "depasse_prod": depasse_prod,
        })
    return out


def _suivre(vues_candidats: List[List[dict]], rayon: float) -> List[dict]:
    pistes: List[dict] = []
    for cands in vues_candidats:
        for c in cands:
            x, y = c["x"], c["y"]
            meilleur, meilleure_dist = None, rayon
            for i, p in enumerate(pistes):
                d = ((p["x"] - x) ** 2 + (p["y"] - y) ** 2) ** 0.5
                if d < meilleure_dist:
                    meilleur, meilleure_dist = i, d
            if meilleur is not None:
                p = pistes[meilleur]
                p["obs"].append(c)
                p["x"] = sum(o["x"] for o in p["obs"]) / len(p["obs"])
                p["y"] = sum(o["y"] for o in p["obs"]) / len(p["obs"])
            else:
                pistes.append({"x": x, "y": y, "obs": [c]})
    return pistes


def _evaluer_piste(p: dict, n_vues: int, rayon: float) -> dict:
    obs = p["obs"]
    k = len(obs)
    persistance = k / n_vues
    evidence_signal = sum(1.0 for o in obs if o["depasse_prod"]) / k

    if k >= 2:
        xs = [o["x"] for o in obs]
        ys = [o["y"] for o in obs]
        mx, my = sum(xs) / k, sum(ys) / k
        std_pos = (sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / k) ** 0.5
        coherence_position = max(0.0, 1.0 - std_pos / rayon)

        signaux = [o["red"] if o["src"] == "rouge" else o["dark"] for o in obs]
        m_sig = sum(signaux) / k
        if abs(m_sig) > 1e-6:
            ecart_type = (sum((s - m_sig) ** 2 for s in signaux) / k) ** 0.5
            cv = ecart_type / abs(m_sig)
            coherence_photo = max(0.0, 1.0 - min(1.0, cv))
        else:
            coherence_photo = 0.5

        decisions = [o["decision_0"] for o in obs]
        majoritaire = max(set(decisions), key=decisions.count)
        coherence_forme = decisions.count(majoritaire) / k
    else:
        coherence_position = coherence_photo = coherence_forme = 0.5

    evidence = (persistance + evidence_signal + coherence_position +
                coherence_forme + coherence_photo) / 5.0

    reds = [o["red"] for o in obs]
    darks = [o["dark"] for o in obs]
    yellows = [o["yellow"] for o in obs]
    core_ls = [o["core_l"] for o in obs]
    core_ss = [o["core_s"] for o in obs]
    skin_ss = [o["skin_s"] for o in obs]
    r_pxs = [o["r_px"] for o in obs]
    ppms = [o["px_per_mm"] for o in obs]
    src_dominant = max(set(o["src"] for o in obs), key=lambda s: sum(1 for o in obs if o["src"] == s))
    decision_finale = _classify(
        sum(reds) / k, sum(darks) / k, sum(yellows) / k, sum(core_ls) / k,
        sum(core_ss) / k, sum(skin_ss) / k, sum(r_pxs) / k, sum(ppms) / k, src_dominant,
    )
    return {"x": p["x"], "y": p["y"], "evidence": evidence, "n_obs": k,
            "decision_finale": decision_finale}


def _evaluer(rapportees: List[dict], verite, rayon: float):
    matches = [0] * len(verite)
    faux_positifs = 0
    for r in rapportees:
        meilleur, meilleure_dist = None, rayon
        for i, (vx, vy) in enumerate(verite):
            d = ((r["x"] - vx) ** 2 + (r["y"] - vy) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            matches[meilleur] += 1
        else:
            faux_positifs += 1
    tp = sum(1 for m in matches if m > 0)
    recall = tp / len(verite) if verite else 0.0
    precision = ((len(rapportees) - faux_positifs) / len(rapportees)) if rapportees else 1.0
    doublons = sum(max(0, m - 1) for m in matches)
    return tp, len(verite) - tp, faux_positifs, recall, precision, doublons


def _fausse_evolution(a: List[dict], b: List[dict], rayon: float) -> int:
    dispo = list(range(len(b)))
    perdues = 0
    for r in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            n = b[i]
            d = ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            dispo.remove(meilleur)
        else:
            perdues += 1
    return perdues + len(dispo)


def _session(marque, n, k_facteur, seed, rayon=RAYON_APPARIEMENT):
    """Une session complete : genere N vues, extrait les candidats permissifs
    de chacune, suit les pistes, evalue leur evidence. Retourne les pistes
    BRUTES (evidence deja calculee, PAS filtrees) pour permettre un balayage
    de seuil sans refaire tourner le moteur."""
    images = _vues_de_session(marque, n, seed)
    vues_candidats = []
    n_utilisables = 0
    for im in images:
        fm = build_face_map(im)
        if not fm.detected or not fm.quality.usable:
            continue
        n_utilisables += 1
        vues_candidats.append(_candidats_permissifs(fm, k_facteur))
    if n_utilisables == 0:
        return [], 0, 0
    pistes_brutes = _suivre(vues_candidats, rayon)
    pistes_evaluees = [_evaluer_piste(p, n_utilisables, rayon) for p in pistes_brutes]
    n_candidats_total = sum(len(v) for v in vues_candidats)
    return pistes_evaluees, n_candidats_total, n_utilisables


def _candidat_atteint(pistes_brutes_evidence, verite, rayon):
    """Candidate recall : la verite a-t-elle ete vue comme candidate dans AU
    MOINS une vue, independamment de toute decision finale ?"""
    atteintes = 0
    for vx, vy in verite:
        if any(((p["x"] - vx) ** 2 + (p["y"] - vy) ** 2) ** 0.5 < rayon for p in pistes_brutes_evidence):
            atteintes += 1
    return atteintes


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
    verite = [((p.x - x0) / bw, (p.y - y0) / bh) for p in plantees]
    print(f"{len(verite)} lesions plantees, plafond connu 7/8 (fusion joue_d, "
          f"voir multiview_evidence_bench.py). {SESSIONS} sessions, N={N_PRINCIPAL}.\n")

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0

    print("=" * 100)
    print(f"B. TABLEAU P0-P3 (N={N_PRINCIPAL})")
    print("=" * 100)
    resultats = {}  # (niveau, seuil) -> dict de moyennes, pour la section D/F
    cas_par_niveau = {}

    for nom_niveau, k_facteur in NIVEAUX:
        toutes_pistes_par_session = []
        candidats_totaux, n_vues_ok_totaux, cpu_l = [], [], []
        for s in range(SESSIONS):
            t0 = time.process_time()
            pistes, n_cand, n_ok = _session(marque, N_PRINCIPAL, k_facteur, seed=3000 * s + 7)
            cpu_l.append(time.process_time() - t0)
            toutes_pistes_par_session.append(pistes)
            candidats_totaux.append(n_cand)
            n_vues_ok_totaux.append(n_ok)

        candidate_recalls = [
            _candidat_atteint(pistes, verite, RAYON_APPARIEMENT) / len(verite)
            for pistes in toutes_pistes_par_session
        ]

        print(f"\n── {nom_niveau} (k x{k_facteur:.2f}) ── "
              f"candidats/vue={moy(candidats_totaux)/max(1,moy(n_vues_ok_totaux)):.1f}  "
              f"pistes/session={moy([len(p) for p in toutes_pistes_par_session]):.1f}  "
              f"CPU/session={moy(cpu_l):.2f}s  "
              f"candidate_recall={moy(candidate_recalls):.2f}")
        print(f"{'seuil':>6} {'TP':>4} {'FN':>4} {'FPfinal':>8} {'recall_brut':>12} "
              f"{'recall_detect.':>15} {'precision':>10} {'F1':>6} {'doublons':>9} "
              f"{'faux-evt/paire':>15}")

        for seuil in SEUILS_EVIDENCE:
            tps, fns, fps, recalls, precisions, doublons_l = [], [], [], [], [], []
            filtres = []
            for pistes in toutes_pistes_par_session:
                gardees = [p for p in pistes if p["evidence"] >= seuil and p["decision_finale"] is not None]
                tp, fn, fp, r, prec, d = _evaluer(gardees, verite, RAYON_APPARIEMENT)
                tps.append(tp); fns.append(fn); fps.append(fp)
                recalls.append(r); precisions.append(prec); doublons_l.append(d)
                filtres.append(gardees)
            faux_evt = [_fausse_evolution(filtres[i], filtres[i + 1], RAYON_APPARIEMENT)
                       for i in range(SESSIONS - 1)]
            r_m, p_m = moy(recalls), moy(precisions)
            f1 = (2 * r_m * p_m / (r_m + p_m)) if (r_m + p_m) > 0 else 0.0
            recall_detectable = min(1.0, r_m * len(verite) / 7.0)

            resultats[(nom_niveau, seuil)] = {
                "recall": r_m, "precision": p_m, "doublons": moy(doublons_l),
                "faux_evt": moy(faux_evt), "f1": f1,
            }
            print(f"{seuil:>6.2f} {moy(tps):>4.1f} {moy(fns):>4.1f} {moy(fps):>8.1f} "
                  f"{r_m:>12.2f} {recall_detectable:>15.2f} {p_m:>10.2f} {f1:>6.2f} "
                  f"{moy(doublons_l):>9.2f} {moy(faux_evt):>15.2f}")

        # ── C. Matrice de tracabilite (Cas A/B/C), au seuil de rapport unique ──
        cas_a = cas_b = cas_c = 0
        for pistes in toutes_pistes_par_session:
            for vx, vy in verite:
                proches = [p for p in pistes if ((p["x"] - vx) ** 2 + (p["y"] - vy) ** 2) ** 0.5 < RAYON_APPARIEMENT]
                if not proches:
                    cas_a += 1
                elif any(p["evidence"] >= SEUIL_RAPPORTE and p["decision_finale"] is not None for p in proches):
                    cas_c += 1
                else:
                    cas_b += 1
        cas_par_niveau[nom_niveau] = (cas_a, cas_b, cas_c)

    print("\n" + "=" * 100)
    print(f"C. ANALYSE DES PERTES (seuil de rapport = {SEUIL_RAPPORTE}, "
          f"sur {SESSIONS} sessions x {len(verite)} lesions = {SESSIONS*len(verite)} instances)")
    print("=" * 100)
    print(f"{'niveau':<6} {'jamais candidate (Cas A)':>26} {'candidate mais rejetee (Cas B)':>32} "
          f"{'correctement fusionnee (Cas C)':>32}")
    for nom_niveau, _ in NIVEAUX:
        a, b, c = cas_par_niveau[nom_niveau]
        print(f"{nom_niveau:<6} {a:>26} {b:>32} {c:>32}")

    # ── F. Verdict : y a-t-il un (niveau, seuil) qui bat la production ? ──
    print("\n" + "=" * 100)
    print("D/F. TRADE-OFF ET VERDICT")
    print("=" * 100)
    print("Reference production N=3 (mesuree dans multiview_persistence_bench.py) : "
          "recall=0.84  precision=0.58  doublons=0.38  faux-evt/paire=6.57\n")

    CIBLE_RECALL = 0.84
    CIBLE_DOUBLONS = 0.1
    CIBLE_FAUX_EVT = 6.57

    gagnants = [(nom, s, v) for (nom, s), v in resultats.items()
               if v["recall"] >= CIBLE_RECALL - 0.005 and v["doublons"] <= CIBLE_DOUBLONS
               and v["faux_evt"] < CIBLE_FAUX_EVT]

    if gagnants:
        gagnants.sort(key=lambda g: -g[2]["f1"])
        meilleur_niveau, meilleur_seuil, meilleures_valeurs = gagnants[0]
        print(f"GO — {meilleur_niveau} (seuil={meilleur_seuil}) atteint la cible : {meilleures_valeurs}")
    else:
        meilleur = max(resultats.items(), key=lambda kv: kv[1]["f1"])
        (meilleur_niveau, meilleur_seuil), meilleures_valeurs = meilleur
        print(f"STOP cette branche telle quelle — aucune combinaison (niveau, seuil) n'atteint "
              f"recall>=0,84 ET doublons<=0,1 ET faux-evt<6,57 simultanement.")
        print(f"Meilleur compromis observe (F1 le plus haut) : {meilleur_niveau} "
              f"seuil={meilleur_seuil} -> {meilleures_valeurs}")

    # ── Confirmation rapide a N=3 avec le meilleur (niveau, seuil) trouve ──
    print(f"\nConfirmation a N={N_CONFIRMATION} avec {meilleur_niveau} (seuil={meilleur_seuil}) :")
    k_conf = dict(NIVEAUX)[meilleur_niveau]
    pistes_par_session_n3 = []
    for s in range(SESSIONS):
        pistes, _, _ = _session(marque, N_CONFIRMATION, k_conf, seed=4000 * s + 7)
        pistes_par_session_n3.append(pistes)
    recalls3, precisions3, doublons3, filtres3 = [], [], [], []
    for pistes in pistes_par_session_n3:
        gardees = [p for p in pistes if p["evidence"] >= meilleur_seuil and p["decision_finale"] is not None]
        tp, fn, fp, r, prec, d = _evaluer(gardees, verite, RAYON_APPARIEMENT)
        recalls3.append(r); precisions3.append(prec); doublons3.append(d)
        filtres3.append(gardees)
    faux_evt3 = [_fausse_evolution(filtres3[i], filtres3[i + 1], RAYON_APPARIEMENT)
                for i in range(SESSIONS - 1)]
    print(f"  recall={moy(recalls3):.2f}  precision={moy(precisions3):.2f}  "
          f"doublons={moy(doublons3):.2f}  faux-evt/paire={moy(faux_evt3):.2f}")

    # ── E. Same-skin obligatoire (section 17), sur les VRAIES lesions ──
    print("\n" + "=" * 100)
    print(f"E. SAME-SKIN sur la photo REELLE (lesions ambigues, pas les plants), "
          f"config gagnante {meilleur_niveau} seuil={meilleur_seuil}, N={N_PRINCIPAL}")
    print("=" * 100)
    pistes_reel_par_session = []
    for s in range(SESSIONS):
        pistes, _, _ = _session(img, N_PRINCIPAL, k_conf, seed=5000 * s + 7)
        gardees = [p for p in pistes if p["evidence"] >= meilleur_seuil and p["decision_finale"] is not None]
        pistes_reel_par_session.append(gardees)
    faux_evt_reel = [_fausse_evolution(pistes_reel_par_session[i], pistes_reel_par_session[i + 1], RAYON_APPARIEMENT)
                     for i in range(SESSIONS - 1)]
    comptes_reel = [len(p) for p in pistes_reel_par_session]
    print(f"lesions finales/session : {comptes_reel}  "
          f"(ecart-type={np.std(comptes_reel):.2f})")
    print(f"faux-evenements/paire sur peau REELLE inchangee : {moy(faux_evt_reel):.2f}  "
          f"(reference production N=3, synthetique : 6.57 ; reference persistance N=9, "
          f"synthetique : 4.57 — comparaison de contexte, pas un match exact puisque "
          f"la population de lesions differe)")

    print("\nG. Aucun changement de production : lesions.py et calibration.py inchanges — "
          "seul l'argument k de _blob_candidates() est mis a l'echelle localement dans ce script.")


if __name__ == "__main__":
    run()
