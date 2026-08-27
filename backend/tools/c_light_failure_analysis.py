"""C-Light Failure Analysis : pourquoi la capture C produit-elle 47
candidats contre 20 sur A, avec le meme score (48) ?

────────────────────────────────────────────────────────────────────────
CE QUE CE SCRIPT FAIT, ET NE FAIT PAS.

Compare les candidats BRUTS (production, k=1,00 — aucune permissivite,
aucun changement de seuil) entre les FaceMap de A et de C, identifie les
candidats de C sans correspondance en A, et caracterise chacun sur des
indicateurs de qualite de capture LOCAUX : saturation, luminance,
dynamique locale, chromaticite, reflet speculaire, exposition relative au
visage. Puis compare la distribution de ces indicateurs entre trois
groupes : candidats de A (population de reference), candidats de C
APPARIES a A (memes points physiques, sous l'eclairage de C), candidats
NOUVEAUX de C (les suspects).

Aucun seuil n'est propose. L'attribution de cause par candidat se fait
par classement RELATIF (quel indicateur devie le plus, en unites d'ecart-
type de la population de reference A, pas une valeur absolue inventee) —
c'est une lecture, pas une regle a coder.

INTERDICTIONS RESPECTEES : lesions.py, calibration.py, le tracking, le
vote-gate ne sont pas touches. Aucune normalisation de C. Aucune
recherche d'un meilleur score.

Rien n'est modifie en production. Aucune image commitee.

Usage :
    python3 backend/tools/c_light_failure_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.per_view_recall_bench import _candidats_permissifs  # noqa: E402
from backend.tools.real_skin_pilot_session_ab import _charger_oriente  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402

DOSSIER = Path("/home/user/real_skin_pilot/subject_001")
IMAGE_A = DOSSIER / "capture_001.jpg"
IMAGE_C = DOSSIER / "capture_003.jpg"
RAYON_APPARIEMENT = 0.08


def _features_locaux(fm, cx: int, cy: int, r_px: float) -> dict:
    """Indicateurs de qualite de capture autour d'UN candidat : saturation,
    luminance, dynamique locale (contraste), chromaticite (a*/b*), reflet
    speculaire (L eleve + S faible — la definition optique standard d'un
    highlight), exposition relative a la moyenne du visage."""
    h, w = fm.skin_mask.shape
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]
    L = fm.l_flat
    A_ = fm.lab[:, :, 1] - 128.0
    B_ = fm.lab[:, :, 2] - 128.0

    rr = max(2, int(round(r_px)))
    y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
    x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
    m = fm.skin_mask[y0:y1, x0:x1] > 0
    if m.sum() < 2:
        m = np.ones((y1 - y0, x1 - x0), dtype=bool)

    l_local = float(L[y0:y1, x0:x1][m].mean())
    s_local = float(S[y0:y1, x0:x1][m].mean())

    rr2 = rr * 3
    yy0, yy1 = max(0, cy - rr2), min(h, cy + rr2 + 1)
    xx0, xx1 = max(0, cx - rr2), min(w, cx + rr2 + 1)
    m2 = fm.skin_mask[yy0:yy1, xx0:xx1] > 0
    dynamique_locale = float(L[yy0:yy1, xx0:xx1][m2].std()) if m2.sum() > 2 else 0.0

    l_visage = float(L[fm.skin_mask > 0].mean())
    s_visage = float(S[fm.skin_mask > 0].mean())

    # reflet speculaire : L normalise haut ET S normalise bas, definition optique
    # standard (highlight = brillant et desature) — pas une formule inventee
    l_norm = min(1.0, max(0.0, l_local / 220.0))
    s_norm = min(1.0, max(0.0, s_local / max(1.0, s_visage * 2)))
    reflet_speculaire = l_norm * (1.0 - s_norm)

    return {
        "luminance": l_local,
        "saturation": s_local,
        "dynamique_locale": dynamique_locale,
        "chroma_a": float(A_[y0:y1, x0:x1][m].mean()),
        "chroma_b": float(B_[y0:y1, x0:x1][m].mean()),
        "reflet_speculaire": reflet_speculaire,
        "exposition_relative": l_local - l_visage,
        "saturation_relative": s_local - s_visage,
    }


def _appareiller_positions(a: List[tuple], b: List[tuple], rayon: float):
    dispo = list(range(len(b)))
    out = []
    for r in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            n = b[i]
            d = ((r[0] - n[0]) ** 2 + (r[1] - n[1]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            out.append((r, meilleur))
            dispo.remove(meilleur)
        else:
            out.append((r, None))
    return out


def run() -> None:
    img_a = _charger_oriente(IMAGE_A)
    img_c = _charger_oriente(IMAGE_C)
    fm_a = build_face_map(_b64(img_a, quality=100))
    fm_c = build_face_map(_b64(img_c, quality=100))
    if not fm_a.detected or not fm_c.detected:
        raise SystemExit("visage non detecte sur A ou C")

    cands_a = _candidats_permissifs(fm_a, 1.00)
    cands_c = _candidats_permissifs(fm_c, 1.00)
    print(f"candidats bruts (production, k=1.00) : A={len(cands_a)}  C={len(cands_c)}\n")

    pts_a = [(c["x"], c["y"]) for c in cands_a]
    appariement = _appareiller_positions(pts_a, [(c["x"], c["y"]) for c in cands_c], RAYON_APPARIEMENT)
    idx_c_apparies = {j for _, j in appariement if j is not None}
    c_apparies = [cands_c[j] for j in idx_c_apparies]
    c_nouveaux = [c for i, c in enumerate(cands_c) if i not in idx_c_apparies]
    print(f"candidats de C apparies a un candidat de A : {len(c_apparies)}")
    print(f"candidats NOUVEAUX de C (sans correspondance en A) : {len(c_nouveaux)}\n")

    def _mesurer(cands, fm):
        return [_features_locaux(fm, int(round(c["x"] * fm.bbox[2] + fm.bbox[0])),
                                  int(round(c["y"] * fm.bbox[3] + fm.bbox[1])), c["r_px"])
                for c in cands]

    feats_a = _mesurer(cands_a, fm_a)
    feats_c_apparies = _mesurer(c_apparies, fm_c)
    feats_c_nouveaux = _mesurer(c_nouveaux, fm_c)

    moy = lambda xs: sum(xs) / len(xs) if xs else 0.0
    ecart_type = lambda xs: (sum((x - moy(xs)) ** 2 for x in xs) / len(xs)) ** 0.5 if xs else 0.0

    cles = ["luminance", "saturation", "dynamique_locale", "chroma_a", "chroma_b",
            "reflet_speculaire", "exposition_relative", "saturation_relative"]

    print("=" * 100)
    print("ETAPE 3-4 : DISTRIBUTIONS COMPARees (candidats de A vs C-apparies vs C-nouveaux)")
    print("=" * 100)
    print(f"{'indicateur':<20} {'A (ref)':>16} {'C apparies':>16} {'C NOUVEAUX':>16}")
    stats_a = {}
    stats_c_apparies = {}
    for cle in cles:
        va = [f[cle] for f in feats_a]
        vb = [f[cle] for f in feats_c_apparies]
        vc = [f[cle] for f in feats_c_nouveaux]
        stats_a[cle] = (moy(va), ecart_type(va))
        stats_c_apparies[cle] = (moy(vb), ecart_type(vb))
        print(f"{cle:<20} {moy(va):>9.2f}+-{ecart_type(va):<5.2f} "
              f"{moy(vb):>9.2f}+-{ecart_type(vb):<5.2f} "
              f"{moy(vc):>9.2f}+-{ecart_type(vc):<5.2f}")

    # ══════════════════════════════════════════════════════════════════
    # ETAPE 2 : cause par candidat nouveau — DEUX lectures, pas une seule.
    # ══════════════════════════════════════════════════════════════════
    # Lecture 1 (contre A) melangerait un effet GLOBAL (tout C differe de A,
    # meme les points apparies) avec ce qui est SPECIFIQUE aux nouveaux
    # candidats -> pas fiable pour attribuer une cause locale.
    # Lecture 2 (contre C-apparies, MEME image/eclairage) isole ce qui rend
    # un nouveau candidat different du reste de C sous les MEMES conditions
    # — c'est la comparaison qui repond vraiment a la question posee.
    def _causes(reference_stats, cands, feats):
        out = {}
        for c, f in zip(cands, feats):
            deviations = {}
            for cle in cles:
                m, s = reference_stats[cle]
                if s > 1e-6:
                    deviations[cle] = abs(f[cle] - m) / s
            cause = max(deviations, key=deviations.get) if deviations else "indetermine"
            out[cause] = out.get(cause, 0) + 1
        return out

    print("\n" + "=" * 100)
    print("ETAPE 2a : cause si on compare a A (melange effet global C-vs-A et effet local)")
    print("=" * 100)
    for cause, n in sorted(_causes(stats_a, c_nouveaux, feats_c_nouveaux).items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {cause}")

    print("\n" + "=" * 100)
    print("ETAPE 2b : cause si on compare a C-APPARIES (meme image/eclairage — "
          "isole ce qui distingue un nouveau candidat du reste de C)")
    print("=" * 100)
    for cause, n in sorted(_causes(stats_c_apparies, c_nouveaux, feats_c_nouveaux).items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {cause}")

    # ══════════════════════════════════════════════════════════════════
    # Niveau image entiere : uniformite d'eclairage, reflets, exposition
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("NIVEAU IMAGE ENTIERE (peau uniquement)")
    print("=" * 100)
    for nom, fm in (("A", fm_a), ("C", fm_c)):
        hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        S = hsv[:, :, 1][fm.skin_mask > 0]
        L = fm.l_flat[fm.skin_mask > 0]
        l_norm = np.clip(L / 220.0, 0, 1)
        s_norm = np.clip(S / max(1.0, float(S.mean()) * 2), 0, 1)
        reflet = l_norm * (1 - s_norm)
        part_reflet = float((reflet > np.percentile(reflet, 95)).mean())  # top 5% comme reference relative
        print(f"  {nom} : luminance_moy={L.mean():.1f}  luminance_std(non-uniformite)={L.std():.1f}  "
              f"saturation_moy={S.mean():.1f}  reflet_speculaire_moy={reflet.mean():.3f}")

    print("\nAucune correction de seuil proposee. Aucune modification de production.")


if __name__ == "__main__":
    run()
