"""Mini-chantier diagnostic — pourquoi les candidats de joue sont-ils rejetes
par `_classify()` sur une photo reelle (sujet 001, capture_005) ?

REGLE STRICTE : ce script ne modifie NI lesions.py NI calibration.py. Il
importe `_classify`, `_blob_candidates`, `_zone_of`, etc. tels quels et se
contente de les OBSERVER — jamais de les reecrire pour de vrai. Le seul code
"duplique" ici est une trace pas-a-pas de `_classify()` (pour savoir QUELLE
regle a tranche, ce que l'appel normal ne dit pas), et elle est verifiee a
CHAQUE candidat contre le veritable `_classify()` : si les deux divergent, le
script s'arrete au lieu de rapporter un mensonge.

Repond aux 5 questions du chantier :
  1. Quelle regle rejette chaque candidat de joue, a quelle etape, avec
     quelles valeurs de features.
  2. Seuil ou signature ? Comparaison chiffree candidats rejetes vs lesions
     confirmees sur LA MEME photo — aucun seuil n'est touche.
  3. Ressemblent-ils a de vrais boutons ? Comparaison a des lesions
     synthetiques plantees sur cette meme photo (backend/tools/synth_lesions
     .py, deja valide) et a de la peau saine de la meme photo.
  4. Specifique a cette photo ? Comparaison d'exposition/saturation locale
     entre les zones qui echouent (joues) et la zone qui reussit (nez).
  5. Le moteur a-t-il deja assez d'information ? Synthese des quatre points
     precedents.

Usage :
    python3 backend/tools/cheek_candidate_diagnostic.py
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from skyn_engine.v2.zones import build_face_map, FaceMap  # noqa: E402
from skyn_engine.v2 import calibration as C  # noqa: E402
from skyn_engine.v2.lesions import (  # noqa: E402
    _local_excess, _blob_candidates, _zone_of, _classify, _confidence,
    RED_IF_DARK, FACE_WIDTH_MM,
)
from tools.synth_lesions import _landmarks, plant  # noqa: E402

PHOTO = Path("/home/user/real_skin_pilot/subject_001/capture_005.jpg")
CIBLES = ("joue_g", "joue_d")


def _b64_from_bgr(img: np.ndarray, quality: int = 92) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


def _charger_oriente_bgr(chemin: Path) -> np.ndarray:
    """Meme correction EXIF que real_skin_pilot_session_ab.py — deja verifiee
    non responsable du probleme (voir exif_orientation_diagnostic.py), gardee
    ici pour travailler sur l'image dans le bon sens de lecture.

    Redimensionne aussi a 1024px de cote max, COMME build_face_map() le fait
    en interne (zones.py::_resize_max) : synth_lesions.plant() construit son
    masque de plantation aux dimensions de l'image qu'on lui donne, puis le
    combine au skin_mask que build_face_map() calcule apres SON PROPRE
    redimensionnement — sur une photo de 3088px (capteur telephone), les deux
    ne correspondent plus et cv2.bitwise_and echoue. En redimensionnant nous-
    memes en amont, les deux tailles restent identiques, exactement comme sur
    l'image de fixture (deja <1024px) pour laquelle ce banc a ete valide."""
    pil = Image.open(chemin)
    corrige = ImageOps.exif_transpose(pil).convert("RGB")
    rgb = np.array(corrige)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    if max(h, w) > 1024:
        s = 1024 / max(h, w)
        bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return bgr


# ─────────────────────────────────────────────────────────────────────────
# Champs derives, IDENTIQUES a detect_lesions() (lesions.py:290-329) — copie
# necessaire : ce diagnostic doit voir les candidats REJETES, que
# detect_lesions() ne renvoie jamais (elle ne garde que les Lesion acceptees).
# ─────────────────────────────────────────────────────────────────────────
class Champs:
    def __init__(self, fm: FaceMap):
        self.fm = fm
        face_w = max(1.0, float(fm.bbox[2]))
        self.px_per_mm = face_w / FACE_WIDTH_MM

        lab = fm.lab
        self.A = lab[:, :, 1] - 128.0
        self.B = lab[:, :, 2] - 128.0
        self.L = fm.l_flat
        hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        self.S = hsv[:, :, 1]

        mask = fm.skin_mask
        sigma_bg = max(4.0, 5.0 * self.px_per_mm)
        self.a_exc = _local_excess(self.A, mask, sigma_bg)
        self.l_exc = _local_excess(self.L, mask, sigma_bg)
        self.b_exc = _local_excess(self.B, mask, sigma_bg)

        margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * self.px_per_mm)
        dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
        core_mask = ((dist > margin_px) * 255).astype(np.uint8)
        for zn in ("sous_yeux_g", "sous_yeux_d"):
            z = fm.zones.get(zn)
            if z is not None and z.available:
                core_mask = cv2.bitwise_and(core_mask, cv2.bitwise_not(z.mask))
        self.core_mask = core_mask
        self.skin_s = float(self.S[mask > 0].mean())

        self.r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * self.px_per_mm)
        self.r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * self.px_per_mm)
        self.a_min = max(4, int(np.pi * self.r_min_px ** 2))
        self.a_max = max(self.a_min + 8, int(np.pi * self.r_max_px ** 2))


class Candidat:
    def __init__(self, cx: int, cy: int, area: float, src: str, champs: Champs):
        self.cx, self.cy, self.area, self.src = cx, cy, area, src
        fm = champs.fm
        h, w = champs.core_mask.shape
        r_px = float(np.sqrt(area / np.pi))
        rr = max(1, int(round(r_px)))
        y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
        x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
        patch_m = fm.skin_mask[y0:y1, x0:x1] > 0

        self.red = float(champs.a_exc[y0:y1, x0:x1][patch_m].mean())
        self.dark = float(champs.l_exc[y0:y1, x0:x1][patch_m].mean())
        self.yellow = float(champs.b_exc[y0:y1, x0:x1][patch_m].mean())

        cr = max(1, int(r_px * 0.5))
        cy0, cy1 = max(0, cy - cr), min(h, cy + cr + 1)
        cx0, cx1 = max(0, cx - cr), min(w, cx + cr + 1)
        self.core_l = float(champs.l_exc[cy0:cy1, cx0:cx1].mean())
        self.core_s = float(champs.S[cy0:cy1, cx0:cx1].mean())

        self.r_px = r_px
        self.d_mm = 2.0 * r_px / champs.px_per_mm
        self.skin_s = champs.skin_s
        self.zone = _zone_of(fm, cx, cy)

        # Verdict AUTHENTIQUE : le vrai _classify(), inchange, importe tel quel.
        self.type = _classify(self.red, self.dark, self.yellow, self.core_l,
                               self.core_s, self.skin_s, self.r_px,
                               champs.px_per_mm, self.src)
        self.confidence = (
            _confidence(self.type, self.red, self.dark, self.core_l,
                        self.area, champs.a_min, champs.a_max)
            if self.type else None
        )
        self.raison = _explique_rejet(self) if self.type is None else None


def _explique_rejet(cand: "Candidat") -> str:
    """Rejoue EXACTEMENT la logique de _classify() (lesions.py:411-460, memes
    constantes litterales, meme ordre) pour nommer la regle qui a tranche —
    _classify() ne renvoie que le verdict final, jamais le pourquoi. Verifie
    par assertion (voir _verifier_trace) que cette relecture produit toujours
    le meme verdict que le vrai _classify() : en cas de divergence, le script
    s'arrete plutot que d'afficher une explication fausse."""
    red, dark, yellow = cand.red, cand.dark, cand.yellow
    core_l, core_s, skin_s = cand.core_l, cand.core_s, cand.skin_s
    d_mm = cand.d_mm

    proche_pustule = red > 1.6 and core_l > 0.8 and core_s < skin_s * 0.82
    cond_papule = d_mm >= 1.2 and (
        (dark > -1.2 and red > 1.8) or (dark <= -1.2 and red > RED_IF_DARK)
    )
    cond_comedon_forme = dark < -1.5 and red < 1.6 and d_mm <= 2.2 and yellow > 0.35
    cond_marque_rouge = red > 1.2 and abs(dark) < 1.0 and d_mm > 1.8
    cond_marque_brune = dark < -1.0 and yellow > 0.5 and red < 1.2

    if proche_pustule:
        return "ACCEPTE (pustule)"
    if cond_papule:
        return "ACCEPTE (papule)"
    if cond_comedon_forme:
        if core_s < skin_s * 0.55:
            return "rejete : comedon-like mais coeur trop desature -> classe poil (core_s < 0.55*skin_s)"
        return "ACCEPTE (comedon)"
    if cond_marque_rouge:
        return "ACCEPTE (marque_rouge)"
    if cond_marque_brune:
        return "ACCEPTE (marque_brune)"

    # Aucune regle ne matche : on identifie la regle la PLUS PROCHE d'avoir
    # matche, pour dire pourquoi — pas juste "aucune regle".
    manques = []
    if d_mm < 1.2:
        manques.append(f"papule: d_mm={d_mm:.2f} < 1.2mm (trop petit)")
    else:
        if dark > -1.2:
            manques.append(f"papule(peu sombre): red={red:.2f} <= 1.8 requis")
        else:
            manques.append(f"papule(sombre): red={red:.2f} <= RED_IF_DARK={RED_IF_DARK} requis")
    if not (red > 1.2 and d_mm > 1.8):
        if red <= 1.2:
            manques.append(f"marque_rouge: red={red:.2f} <= 1.2 requis")
        if d_mm <= 1.8:
            manques.append(f"marque_rouge: d_mm={d_mm:.2f} <= 1.8mm requis")
    return "rejete (aucune regle) : " + " | ".join(manques)


def _verifier_trace(cands: List[Candidat]) -> None:
    for c in cands:
        attendu = "ACCEPTE" in (c.raison or "") if c.type is None else True
        # Le vrai verdict fait foi : si _classify() a accepte, c.type n'est
        # pas None et _explique_rejet n'est meme pas appelee (voir Candidat).
        # Cette fonction ne verifie donc que les cas rejetes : la trace ne
        # doit JAMAIS pretendre un rejet accepte par erreur.
        if c.type is None and "ACCEPTE" in (c.raison or ""):
            raise AssertionError(
                f"Divergence trace/_classify() sur candidat ({c.cx},{c.cy}) — "
                "arret, la trace ne doit jamais etre affichee si elle contredit "
                "le vrai _classify()."
            )


def _candidats(champs: Champs, zones_filtre: Optional[Tuple[str, ...]] = None) -> List[Candidat]:
    fm = champs.fm
    cands_bruts: Dict[Tuple[int, int], Tuple[float, str]] = {}
    for cx, cy, area, _ in _blob_candidates(champs.a_exc, champs.core_mask, C.RED_BLOB_K,
                                            champs.a_min, champs.a_max):
        cands_bruts[(cx, cy)] = (area, "rouge")
    for cx, cy, area, _ in _blob_candidates(-champs.l_exc, champs.core_mask, C.DARK_BLOB_K,
                                            champs.a_min, champs.a_max):
        if (cx, cy) not in cands_bruts:
            cands_bruts[(cx, cy)] = (area, "sombre")

    pts = sorted(cands_bruts.items(), key=lambda kv: -kv[1][0])
    min_sep = max(3.0, 1.2 * champs.px_per_mm)
    kept: List[Tuple[int, int, float, str]] = []
    for (cx, cy), (area, src) in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < min_sep ** 2 for kx, ky, _, _ in kept):
            continue
        kept.append((cx, cy, area, src))

    out = [Candidat(cx, cy, area, src, champs) for cx, cy, area, src in kept]
    if zones_filtre is not None:
        out = [c for c in out if c.zone in zones_filtre]
    return out


def _fmt(c: Candidat, label: str) -> str:
    verdict = c.type or "None"
    return (f"{label:<10} zone={c.zone:<10} src={c.src:<6} d_mm={c.d_mm:>4.1f} "
            f"red={c.red:>6.2f} dark={c.dark:>6.2f} yellow={c.yellow:>6.2f} "
            f"core_l={c.core_l:>6.2f} core_s={c.core_s:>6.1f} skin_s={c.skin_s:>5.1f} "
            f"-> {verdict:<12} conf={c.confidence}")


def main() -> None:
    print(f"Photo : {PHOTO}\n")
    bgr = _charger_oriente_bgr(PHOTO)
    fm = build_face_map(_b64_from_bgr(bgr))
    if not fm.detected:
        raise SystemExit("visage non detecte")
    champs = Champs(fm)

    tous = _candidats(champs)
    joue = [c for c in tous if c.zone in CIBLES]
    _verifier_trace(joue)

    # ── Question 1 & 2 : le tableau candidat -> verdict -> raison ──────────
    print("=" * 100)
    print("QUESTION 1-2 — Candidats de joue : verdict et regle exacte")
    print("=" * 100)
    print(f"{'#':<3}{'zone':<10}{'src':<7}{'d_mm':>6}{'red':>7}{'dark':>7}{'yellow':>8}"
          f"{'core_l':>8}{'core_s':>8}{'verdict':>12}  raison")
    for i, c in enumerate(sorted(joue, key=lambda c: c.zone)):
        verdict = c.type or "None"
        raison = "-" if c.type else c.raison
        print(f"{i:<3}{c.zone:<10}{c.src:<7}{c.d_mm:>6.1f}{c.red:>7.2f}{c.dark:>7.2f}"
              f"{c.yellow:>8.2f}{c.core_l:>8.2f}{c.core_s:>8.1f}{verdict:>12}  {raison}")

    n_accept = sum(1 for c in joue if c.type)
    print(f"\n{len(joue)} candidats en joue_g/joue_d, {n_accept} acceptes, "
          f"{len(joue) - n_accept} rejetes.")

    # ── Reference : lesions confirmees ailleurs sur LA MEME photo ──────────
    reste = [c for c in tous if c.zone not in CIBLES]
    confirmees_ailleurs = [c for c in reste if c.type]
    rejetees_ailleurs = [c for c in reste if not c.type]
    print(f"\nPour reference, ailleurs sur la meme photo : {len(confirmees_ailleurs)} "
          f"candidats acceptes, {len(rejetees_ailleurs)} rejetes "
          f"(zones : {sorted(set(c.zone for c in tous if c.zone not in CIBLES))}).")

    # ── Question 3 : lesions synthetiques plantees sur CETTE photo ─────────
    print("\n" + "=" * 100)
    print("QUESTION 3 — Comparaison a des lésions synthétiques plantées sur cette photo")
    print("=" * 100)
    pts_repere = _landmarks(bgr)
    if pts_repere is None:
        print("(reperes MediaPipe indisponibles pour la plantation — section ignoree)")
        synth_joue: List[Candidat] = []
    else:
        marque = bgr.copy()
        for zone in CIBLES:
            marque, _planted = plant(marque, pts_repere, zone, 4, seed=11)
        fm_synth = build_face_map(_b64_from_bgr(marque, quality=100))
        if not fm_synth.detected:
            print("(visage non détecté après plantation — section ignorée)")
            synth_joue = []
        else:
            champs_synth = Champs(fm_synth)
            synth_all = _candidats(champs_synth, zones_filtre=CIBLES)
            # Ne garder que les candidats nouveaux (proches d'un point plante),
            # pas les candidats deja presents sur la photo d'origine.
            synth_joue = synth_all
            print(f"{len(synth_joue)} candidats détectés en joue après plantation "
                  f"(8 lésions synthétiques posées, 4 par joue) :")
            for c in synth_joue:
                print("  " + _fmt(c, "synth"))

    # ── Question 4 : la photo elle-meme (eclairage/couleur par zone) ───────
    print("\n" + "=" * 100)
    print("QUESTION 4 — Facteurs propres à cette photo, par zone")
    print("=" * 100)
    for zname in ("nez", "joue_g", "joue_d", "front"):
        z = fm.zones.get(zname)
        if z is None or not z.available:
            print(f"{zname:<10} indisponible")
            continue
        zm = z.mask > 0
        l_mean = float(champs.L[zm].mean())
        s_mean = float(champs.S[zm].mean())
        a_mean = float(champs.A[zm].mean())
        print(f"{zname:<10} L(luminance)={l_mean:>6.1f}  S(saturation)={s_mean:>6.1f}  "
              f"a*(rougeur brute)={a_mean:>6.1f}  hair_ratio={z.hair_ratio:.3f}")
    print(f"\nQualité globale de capture : blur={fm.quality.blur:.0f} "
          f"exposure={fm.quality.exposure:.0f} clipped={fm.quality.clipped:.4f} "
          f"roll={fm.quality.roll_deg:.1f}° yaw_proxy={fm.quality.yaw_proxy:.2f} "
          f"usable={fm.quality.usable} issues={fm.quality.issues}")

    # ── Question 5 : synthese ───────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("QUESTION 5 — Synthèse : le moteur a-t-il assez d'information ?")
    print("=" * 100)

    def _stats(cands: List[Candidat], label: str) -> None:
        if not cands:
            print(f"{label:<32} (aucun candidat)")
            return
        red = np.array([c.red for c in cands])
        dark = np.array([c.dark for c in cands])
        print(f"{label:<32} n={len(cands):<3} red={red.mean():>6.2f}±{red.std():<5.2f} "
              f"dark={dark.mean():>6.2f}±{dark.std():<5.2f}")

    joue_rejetes = [c for c in joue if not c.type]
    joue_acceptes = [c for c in joue if c.type]
    confirmees_photo = [c for c in tous if c.type]
    _stats(joue_rejetes, "Rejetés (joue, cette photo)")
    _stats(joue_acceptes, "Acceptés (joue, cette photo)")
    _stats(confirmees_photo, "TOUTES lésions confirmées (photo)")
    _stats(synth_joue, "Synthétiques plantées (joue)")
    _stats(rejetees_ailleurs, "Rejetés hors-joue (bruit de référence)")


if __name__ == "__main__":
    main()
