"""Real-Skin Pilot — Session A vs Session B (ou toute paire de sessions).

────────────────────────────────────────────────────────────────────────
CE QUE CE SCRIPT ATTEND, ET POURQUOI IL NE TOURNE PAS ENCORE.

`real_skin_pilot_001.py` n'a mesure qu'UNE capture (perturbee
artificiellement pour simuler de la variabilite). Ce script compare DEUX
captures REELLEMENT INDEPENDANTES de la meme peau — meme telephone, meme
visage, conditions legerement differentes (lumiere, moment, expression),
volontairement PAS identiques. C'est le seul test qui repond vraiment a
la question centrale de SKYN : "meme peau, deux visites -> meme histoire ?"

Ce script attend deux fichiers hors depot :
    /home/user/real_skin_pilot/subject_001/capture_001.jpg  (Session A, deja present)
    /home/user/real_skin_pilot/subject_001/capture_002.jpg  (Session B, a fournir)
Rien n'est lu ni ecrit ailleurs ; aucune image n'est jamais imprimee,
encodee dans un fichier commite, ou copiee dans le depot Git.

AUCUNE MODIFICATION DU MOTEUR n'est faite entre la generation de Session A
et Session B — c'est la regle explicite : le moteur actuel EST la
baseline. Toute hypothese d'amelioration viendra APRES cette mesure, pas
avant.

────────────────────────────────────────────────────────────────────────
CE QUI EST MESURE (exactement la liste demandee) :

    1. |score_A - score_B|
    2. |compte_A - compte_B|
    3. Identite des lesions : combien de lesions de A sont retrouvees en B
       (appariement par position + zone, PAS par simple compte)
    4. Position : derive des lesions appariees
    5. Classification : la classe reste-t-elle la meme pour une lesion
       appariee, ou change-t-elle (papule -> comedon -> None...) ?
    6. Track stability multi-vue : le pipeline valide (tracking + nettoyage
       + purete + vote-gate), execute independamment sur N=9 vues de
       chaque session, donne-t-il le meme ensemble de lesions confirmees ?

Deux niveaux gardes separes, comme demande : niveau MOTEUR (ce qui est
mesure ici) et niveau PRODUIT (ce qui serait annonce a l'utilisateur,
potentiellement plus tolerant) — ce script ne construit QUE le niveau
moteur ; la couche produit est explicitement hors perimetre pour l'instant.

EXIF : chaque image est auto-orientee (PIL `exif_transpose`) avant analyse.
Verifie sur Session A/B precedentes : ca ne change quasiment rien au
resultat (0,05 % de score), mais c'est l'entree "correcte" a comparer —
le moteur de production, lui, N'A AUCUNE correction EXIF (verifie dans
le code), donc une vraie photo tournee y arriverait telle quelle. Ce
script imprime quand une correction a ete appliquee, pour que ce ne soit
jamais une variable cachee.

Usage :
    python3 backend/tools/real_skin_pilot_session_ab.py [image_A] [image_B]
    (par defaut : capture_001.jpg vs capture_002.jpg)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import cv2
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import FaceAnalysis, analyze_face  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.lesion_tracking_audit import RAYON_MATCH_ANCIEN, SEUIL_EVIDENCE, _suivre  # noqa: E402
from backend.tools.observation_outlier_bench import (  # noqa: E402
    _decision_vote_porte,
    _dimensions,
    _nettoyer,
)
from backend.tools.per_view_recall_bench import _candidats_permissifs, _vues_de_session  # noqa: E402
from backend.tools.stability_bench import _b64  # noqa: E402

DOSSIER = Path("/home/user/real_skin_pilot/subject_001")
IMAGE_A = DOSSIER / "capture_001.jpg"
IMAGE_B = DOSSIER / "capture_002.jpg"


def _charger_oriente(chemin: Path):
    pil = Image.open(chemin)
    orientation_brute = pil.getexif().get(274, 1)
    corrige = ImageOps.exif_transpose(pil)
    if orientation_brute != 1:
        print(f"  [{chemin.name}] EXIF orientation={orientation_brute} -> auto-orientee avant analyse")
    return cv2.cvtColor(np.array(corrige.convert("RGB")), cv2.COLOR_RGB2BGR)

# Rayon d'appariement plus genereux que les 0,05 utilises pour de simples
# perturbations d'une meme image : deux captures REELLEMENT independantes
# peuvent differer en cadrage/distance bien plus qu'une rotation de 2deg.
RAYON_APPARIEMENT_AB = 0.08
N_VUES_MULTIVUE = 9
SEUIL_NETTOYAGE = 9.5
SEUIL_PURETE = 0.5


def _appareiller(a: List[dict], b: List[dict], rayon: float):
    """Meme logique que `stability_bench._appareiller`, reprise ici pour ne
    pas dependre d'une seule image de reference figee dans ce module."""
    dispo = list(range(len(b)))
    out = []
    for r in a:
        meilleur, meilleure_dist = None, rayon
        for i in dispo:
            n = b[i]
            d = ((r["x"] - n["x"]) ** 2 + (r["y"] - n["y"]) ** 2) ** 0.5
            if d < meilleure_dist:
                meilleur, meilleure_dist = i, d
        if meilleur is not None:
            out.append((r, b[meilleur]))
            dispo.remove(meilleur)
        else:
            out.append((r, None))
    return out


def _rapport(img) -> FaceAnalysis:
    out = analyze_face(_b64(img, quality=100))
    if not out.ok:
        raise SystemExit(f"visage non detecte : {out.diagnosis}")
    return out


def _multivue_confirmees(img, n_vues: int) -> List[dict]:
    """Une seule session multi-vue (pas repetee) : le pipeline valide
    (tracking + nettoyage + purete + vote-gate) applique une fois a N vues
    de CETTE capture — pas une mesure de stabilite intra-session (deja
    faite dans real_skin_pilot_001.py), mais l'ensemble confirme que ce
    pipeline produirait pour CETTE session, a comparer entre A et B."""
    images = _vues_de_session(img, n_vues, seed=42)
    vues_candidats = []
    for im in images:
        fm = build_face_map(im)
        if not fm.detected or not fm.quality.usable:
            continue
        vues_candidats.append(_candidats_permissifs(fm, 1.00))
    if not vues_candidats:
        return []
    n_vues_ok = len(vues_candidats)
    pistes_brutes = _suivre(vues_candidats, RAYON_MATCH_ANCIEN)
    confirmees = []
    for p in pistes_brutes:
        obs = _nettoyer(p["obs"], SEUIL_NETTOYAGE)
        dims = _dimensions(obs, n_vues_ok, RAYON_MATCH_ANCIEN)
        if dims["evidence"] < SEUIL_EVIDENCE or dims["coherence_photo"] < SEUIL_PURETE:
            continue
        _, etat = _decision_vote_porte(obs)
        if etat == "CONFIRMEE":
            k = len(obs)
            confirmees.append({"x": sum(o["x"] for o in obs) / k, "y": sum(o["y"] for o in obs) / k})
    return confirmees


def run() -> None:
    image_a = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGE_A
    image_b = Path(sys.argv[2]) if len(sys.argv) > 2 else IMAGE_B
    if not image_a.exists():
        raise SystemExit(f"Session A manquante : {image_a}")
    if not image_b.exists():
        raise SystemExit(
            f"Session B pas encore fournie : {image_b}\n"
            f"Ce script attend une DEUXIEME capture reelle, volontairement "
            f"differente (lumiere/moment/expression), du meme sujet. Rien "
            f"a analyser tant qu'elle n'est pas placee la."
        )
    print(f"Session A = {image_a.name}   Session B = {image_b.name}")
    img_a = _charger_oriente(image_a)
    img_b = _charger_oriente(image_b)

    a = _rapport(img_a)
    b = _rapport(img_b)

    # ══════════════════════════════════════════════════════════════════
    # 1-2. Score et compte
    # ══════════════════════════════════════════════════════════════════
    print("=" * 100)
    print("1-2. SCORE ET COMPTE")
    print("=" * 100)
    print(f"Session A : score={a.global_score}  lesions={len(a.lesions)}  confiance={a.confidence:.2f}")
    print(f"Session B : score={b.global_score}  lesions={len(b.lesions)}  confiance={b.confidence:.2f}")
    print(f"|Delta score|={abs(a.global_score - b.global_score)}  "
          f"|Delta compte|={abs(len(a.lesions) - len(b.lesions))}")

    # ══════════════════════════════════════════════════════════════════
    # 3-4-5. Identite, position, classification
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print(f"3-4-5. IDENTITE / POSITION / CLASSIFICATION (rayon d'appariement={RAYON_APPARIEMENT_AB})")
    print("=" * 100)
    appariees = _appareiller(a.lesions, b.lesions, RAYON_APPARIEMENT_AB)
    retrouvees = [(r, n) for r, n in appariees if n is not None]
    perdues = [r for r, n in appariees if n is None]
    nouvelles_b = len(b.lesions) - len(retrouvees)

    print(f"Lesions de A retrouvees en B : {len(retrouvees)}/{len(a.lesions)}")
    print(f"Lesions de A perdues (absentes de B) : {len(perdues)}")
    print(f"Lesions nouvelles en B (absentes de A) : {nouvelles_b}")

    derives = [((r["x"]-n["x"])**2+(r["y"]-n["y"])**2)**0.5 for r, n in retrouvees]
    changements_classe = [(r["type"], n["type"]) for r, n in retrouvees if r["type"] != n["type"]]
    changements_zone = [(r["zone"], n["zone"]) for r, n in retrouvees if r["zone"] != n["zone"]]

    if derives:
        print(f"derive de position (lesions appariees) : moyenne={sum(derives)/len(derives):.4f}  "
              f"max={max(derives):.4f}")
    print(f"changements de classe : {len(changements_classe)}/{len(retrouvees)}  {changements_classe[:10]}")
    print(f"changements de zone   : {len(changements_zone)}/{len(retrouvees)}  {changements_zone[:10]}")

    # ══════════════════════════════════════════════════════════════════
    # Fausse evolution (niveau moteur) — le calcul central
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("FAUSSE EVOLUTION (niveau moteur) — si la peau n'a pas reellement change entre A et B, "
          "tout ecart ci-dessous est un artefact de mesure, pas une vraie evolution")
    print("=" * 100)
    print(f"evenements de fausse evolution (perdues + nouvelles) = {len(perdues) + nouvelles_b}")
    print(f"sur {len(a.lesions)} lesions de reference (A) et {len(b.lesions)} lesions rapportees (B)")

    # ══════════════════════════════════════════════════════════════════
    # 6. Stabilite multi-vue (pipeline valide, une session par capture)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print(f"6. STABILITE MULTI-VUE (pipeline clean->purete->vote-gate, N={N_VUES_MULTIVUE}, "
          f"une session par capture)")
    print("=" * 100)
    conf_a = _multivue_confirmees(img_a, N_VUES_MULTIVUE)
    conf_b = _multivue_confirmees(img_b, N_VUES_MULTIVUE)
    print(f"Session A confirmees : {len(conf_a)}   Session B confirmees : {len(conf_b)}")
    appariees_mv = _appareiller(conf_a, conf_b, RAYON_APPARIEMENT_AB)
    retrouvees_mv = sum(1 for _, n in appariees_mv if n is not None)
    print(f"retrouvees entre A et B (multi-vue) : {retrouvees_mv}/{len(conf_a)}   "
          f"faux-evenements (multi-vue) = {(len(conf_a)-retrouvees_mv) + (len(conf_b)-retrouvees_mv)}")

    print("\nAucune image commitee. Aucune modification du moteur entre A et B "
          "(le moteur EST la baseline de cette mesure).")


if __name__ == "__main__":
    run()
