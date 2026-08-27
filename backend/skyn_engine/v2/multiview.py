"""Guided multi-view scan orchestration.

────────────────────────────────────────────────────────────────────────
CE QUE CE MODULE EST, ET N'EST PAS.

Chaque mecanisme ici a ete valide separement, avec BASELINE/NEW/DELTA
mesures, dans le chantier de bancs sous `backend/tools/` (candidate
generation : `per_view_recall_bench.py` ; tracking : `lesion_tracking_
audit.py` ; nettoyage par observation : `observation_outlier_bench.py` ;
purete + vote-gate : `vote_gate_bench.py`, `track_clean_purity_bench.py` ;
arret adaptatif : `capture_protocol_v0_bench.py` + verification
statistique a R=16). Ce module ORCHESTRE ces mecanismes deja valides,
inchanges — il ne modifie NI `lesions.py` NI `calibration.py` : la
detection par vue et la classification individuelle restent exactement le
moteur existant. La seule chose nouvelle ici est l'enchainement entre
plusieurs vues.

Les constantes ci-dessous (rayon d'appariement, seuils de nettoyage/
purete/evidence, ratio et marge du vote-gate) sont EXACTEMENT celles
retenues a l'issue de ce chantier — pas des valeurs choisies pour ce
fichier. Toute modification doit repasser par un banc, pas etre ajustee
ici a l'oeil.

Usage prevu : un endpoint API convertit une liste d'images (base64) en
appel a `orchestrer_scan()`, qui gere elle-meme l'arret adaptatif
(cible/minimum/maximum de vues utilisables).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

from . import calibration as C
from .lesions import _blob_candidates, _classify, _local_excess, _robust_thr
from .zones import FaceMap, build_face_map

# Valeurs retenues a l'issue du chantier de bancs (backend/tools/) — voir
# l'entete de ce fichier pour les references.
RAYON_APPARIEMENT = 0.05
SEUIL_NETTOYAGE = 9.5
SEUIL_PURETE = 0.5
SEUIL_EVIDENCE = 0.50
RATIO_VOTE_MIN = 0.5
SHARE_VOTE_MIN = 0.8
FACTEUR_MAD = 1.4826  # meme constante que _robust_thr(), appliquee ici a l'echelle d'un track


@dataclass
class ScanConfig:
    min_vues_utiles: int = 5
    cible_vues: int = 7
    max_vues: int = 9


@dataclass
class ScanResult:
    lesions_confirmees: List[dict]
    n_vues_recues: int
    n_vues_utilisables: int
    raison_arret: str


def _candidats_par_vue(fm: FaceMap) -> List[dict]:
    """Candidats bruts d'UNE vue, a la rigueur de production (k=1,00,
    exactement `C.RED_BLOB_K` / `C.DARK_BLOB_K`) — port direct de
    `_candidats_permissifs(fm, 1.00)` dans `per_view_recall_bench.py`."""
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
    for cx, cy, area, _ in _blob_candidates(a_exc, core_mask, C.RED_BLOB_K, a_min, a_max):
        cands[(cx, cy)] = (area, "rouge")
    for cx, cy, area, _ in _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K, a_min, a_max):
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


def _suivre(vues_candidats: List[List[dict]]) -> List[dict]:
    """Plus proche voisin, rayon fixe — port direct de `_suivre()` dans
    `lesion_tracking_audit.py`."""
    pistes: List[dict] = []
    for cands in vues_candidats:
        for c in cands:
            x, y = c["x"], c["y"]
            meilleur, meilleure_dist = None, RAYON_APPARIEMENT
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


def _signal(o: dict) -> float:
    return o["red"] if o["src"] == "rouge" else o["dark"]


def _nettoyer(obs: List[dict]) -> List[dict]:
    """Retire les observations aberrantes d'un track par statistique
    robuste (mediane + FACTEUR_MAD x MAD) — port direct de `_nettoyer()`
    dans `observation_outlier_bench.py`."""
    if len(obs) < 3:
        return obs
    signaux = sorted(_signal(o) for o in obs)
    n = len(signaux)
    mediane = signaux[n // 2] if n % 2 else (signaux[n // 2 - 1] + signaux[n // 2]) / 2.0
    ecarts = sorted(abs(s - mediane) for s in signaux)
    mad = ecarts[n // 2] if n % 2 else (ecarts[n // 2 - 1] + ecarts[n // 2]) / 2.0
    if mad < 0.05:
        return obs
    scores = [abs(_signal(o) - mediane) / (FACTEUR_MAD * mad) for o in obs]
    gardees = [o for o, s in zip(obs, scores) if s <= 3.0]
    return gardees if len(gardees) >= 2 else obs


def _dimensions(obs: List[dict], n_vues: int) -> dict:
    """Evidence a 5 dimensions + purete photometrique — port direct de
    `_dimensions()` dans `observation_outlier_bench.py`."""
    k = len(obs)
    persistance = k / n_vues
    evidence_signal = sum(1.0 for o in obs if o["depasse_prod"]) / k
    if k >= 2:
        xs = [o["x"] for o in obs]
        ys = [o["y"] for o in obs]
        mx, my = sum(xs) / k, sum(ys) / k
        std_pos = (sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / k) ** 0.5
        coherence_position = max(0.0, 1.0 - std_pos / RAYON_APPARIEMENT)
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


def _decision_vote(obs: List[dict]):
    """Vote-gate : pluralite des classifications individuelles, avec porte
    de marge/proportion de votes valides — port direct de
    `_decision_vote_porte()` dans `observation_outlier_bench.py`."""
    votes_valides = [o["decision_0"] for o in obs if o["decision_0"] is not None]
    n = len(obs)
    ratio = len(votes_valides) / n if n else 0.0
    if not votes_valides:
        return None, "REJETEE"
    majoritaire = max(set(votes_valides), key=votes_valides.count)
    share = votes_valides.count(majoritaire) / len(votes_valides)
    if ratio >= RATIO_VOTE_MIN and share >= SHARE_VOTE_MIN:
        return majoritaire, "CONFIRMEE"
    return None, "INCERTAINE"


def _confirmer(vues_candidats: List[List[dict]]) -> List[dict]:
    """Le pipeline complet valide : tracking -> nettoyage -> purete ->
    vote-gate, sur les candidats deja accumules."""
    if not vues_candidats:
        return []
    n_ok = len(vues_candidats)
    pistes_brutes = _suivre(vues_candidats)
    confirmees = []
    for p in pistes_brutes:
        obs = _nettoyer(p["obs"])
        dims = _dimensions(obs, n_ok)
        if dims["evidence"] < SEUIL_EVIDENCE or dims["coherence_photo"] < SEUIL_PURETE:
            continue
        classe, etat = _decision_vote(obs)
        if etat != "CONFIRMEE":
            continue
        k = len(obs)
        confirmees.append({
            "x": sum(o["x"] for o in obs) / k,
            "y": sum(o["y"] for o in obs) / k,
            "type": classe,
            "n_observations": k,
        })
    return confirmees


def _memes_positions(a: List[dict], b: List[dict], rayon: float = RAYON_APPARIEMENT) -> bool:
    if len(a) != len(b):
        return False
    dispo = list(range(len(b)))
    for pa in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            d = ((pa["x"] - b[i]["x"]) ** 2 + (pa["y"] - b[i]["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is None:
            return False
        dispo.remove(meilleur)
    return True


def orchestrer_scan(images_b64: List[str], config: Optional[ScanConfig] = None) -> ScanResult:
    """Traite une liste d'images (une par vue) et applique l'arret
    adaptatif : plafond dur a `max_vues`, arret anticipe des que
    `cible_vues` est atteinte ET que l'ensemble confirme est reste stable
    entre deux vues utilisables consecutives, sinon continue jusqu'a
    epuisement des images fournies."""
    config = config or ScanConfig()
    vues_utilisables: List[List[dict]] = []
    confirmees_precedentes: Optional[List[dict]] = None

    for i, image_b64 in enumerate(images_b64):
        fm = build_face_map(image_b64)
        if not fm.detected or not fm.quality.usable:
            continue
        vues_utilisables.append(_candidats_par_vue(fm))
        n = len(vues_utilisables)

        if n >= config.max_vues:
            return ScanResult(_confirmer(vues_utilisables), i + 1, n, "max_atteint")

        if n >= config.min_vues_utiles:
            confirmees = _confirmer(vues_utilisables)
            if (n >= config.cible_vues and confirmees_precedentes is not None
                    and _memes_positions(confirmees, confirmees_precedentes)):
                return ScanResult(confirmees, i + 1, n, "cible_atteinte_stable")
            confirmees_precedentes = confirmees

    confirmees = _confirmer(vues_utilisables) if vues_utilisables else []
    return ScanResult(confirmees, len(images_b64), len(vues_utilisables), "frames_epuisees")
