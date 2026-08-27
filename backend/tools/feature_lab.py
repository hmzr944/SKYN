"""Laboratoire de features : separabilite et invariance mesurees separement,
AVANT tout choix de representation.

────────────────────────────────────────────────────────────────────────
CE QUE CE BANC REPOND, ET POURQUOI DEUX MESURES DISTINCTES.

`invariance_matrix.py` a teste deux representations completes (candidat +
seuil) de bout en bout, et les deux ont echoue. Ce banc descend d'un cran :
avant de choisir COMMENT seuiller un signal, il faut savoir SI ce signal est
le bon. Une feature n'est utile que si elle reunit deux proprietes
independantes :

  SEPARABILITE — distingue-t-elle une lesion d'une peau saine ?
  INVARIANCE   — reste-t-elle stable quand seule l'IMAGE change ?

Une feature separable mais instable (le rouge LAB absolu actuel : separe
bien, mais bouge avec le contraste) et une feature stable mais non separable
(un z-score local trop lisse : stable, mais ne distingue plus rien) sont
toutes les deux inutilisables — pour des raisons opposees. Les mesurer
ensemble les confond ; les mesurer separement dit LAQUELLE des deux proprietes
manque a chaque candidate.

Methode : une lesion synthetique connue (verite terrain, comme dans
`synth_lesions.py`) contre une centaine de patchs de peau saine tires au
hasard — mesures UNE FOIS sur l'image de reference (separabilite), puis
RE-MESUREES aux memes positions apres chaque transformation PUREMENT
photometrique de l'image entiere (invariance). Les positions ne bougent
jamais : une perturbation photometrique ne deplace aucun pixel, seule sa
valeur change — ce qui isole la reponse de la feature au changement d'image,
sans le bruit d'une nouvelle detection de reperes a chaque fois.

Quatre familles, choisies pour representer des principes differents, pas des
variantes du meme geste :

  A. exces_absolu        — ce que le moteur utilise aujourd'hui : chan - fond
                            local, en unites LAB absolues.
  B. contraste_relatif    — (chan - fond local) / |fond local| : le meme
                            ecart, mais rapporte au NIVEAU DE PEAU local
                            plutot qu'a une echelle absolue. Sous un
                            etirement de contraste `chan' = a*chan + b`,
                            l'exces absolu est multiplie par `a` ; ce rapport
                            l'est beaucoup moins des que `b` reste petit
                            devant le niveau de peau — c'est l'hypothese
                            testee, pas un fait suppose.
  C. gradient             — magnitude du gradient local (Sobel) : teste si
                            une lesion se distingue par sa STRUCTURE
                            spatiale plutot que par sa couleur.
  D. texture_locale       — variance locale de la luminance : proxy de
                            texture. Sciemment risque — le test CLAHE a deja
                            montre que la texture cutanee normale est un
                            signal fort en soi, donc potentiellement peu
                            discriminant seul.

Aucun seuil ni aucune regle de production n'est modifie ici.

Usage :
    python3 backend/tools/feature_lab.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.synth_lesions import _landmarks, plant  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")
N_SKIN = 150
RAYON_PATCH = 6  # px, a l'echelle de l'image redimensionnee par le moteur (1024 max)
SEED = 5


def _b64(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


# --------------------------------------------------------------------------
# Perturbations photometriques PURES — aucune ne deplace un seul pixel.
# --------------------------------------------------------------------------
def _contraste(img: np.ndarray, facteur: float) -> np.ndarray:
    moy = img.astype(np.float32).mean()
    return np.clip((img.astype(np.float32) - moy) * facteur + moy, 0, 255).astype(np.uint8)


def _luminosite(img: np.ndarray, delta: int) -> np.ndarray:
    return np.clip(img.astype(np.int16) + delta, 0, 255).astype(np.uint8)


def _gamma(img: np.ndarray, g: float) -> np.ndarray:
    lut = np.array([((i / 255.0) ** g) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, lut)


def _jpeg(img: np.ndarray, quality: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


PERTURBATIONS: List[Tuple[str, Callable[[np.ndarray], np.ndarray]]] = [
    ("original", lambda im: im),
    ("contraste_+5%", lambda im: _contraste(im, 1.05)),
    ("contraste_+10%", lambda im: _contraste(im, 1.10)),
    ("contraste_+15%", lambda im: _contraste(im, 1.15)),
    ("luminosite_+10%", lambda im: _luminosite(im, int(255 * 0.10))),
    ("gamma_0.85", lambda im: _gamma(im, 0.85)),
    ("gamma_1.15", lambda im: _gamma(im, 1.15)),
    ("jpeg_95", lambda im: _jpeg(im, 95)),
    ("jpeg_85", lambda im: _jpeg(im, 85)),
]


# --------------------------------------------------------------------------
# Calcul des features. Chacune prend les CANAUX DE L'IMAGE PERTURBEE, DEJA
# CONVERTIS, et une position — elle ne sait rien du reste du pipeline.
# --------------------------------------------------------------------------
class Champs:
    """Les canaux derives d'une image, calcules une fois par perturbation."""

    def __init__(self, bgr: np.ndarray, skin_mask: np.ndarray, sigma_bg: float):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)

        self.A = lab[:, :, 1] - 128.0
        self.mask = skin_mask
        m = (skin_mask > 0).astype(np.float32)
        den = cv2.GaussianBlur(m, (0, 0), sigma_bg)
        num = cv2.GaussianBlur(self.A * m, (0, 0), sigma_bg)
        self.fond_local = num / np.maximum(den, 1e-3)
        self.exces = (self.A - self.fond_local) * m

        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        self.gradient = np.sqrt(gx * gx + gy * gy)

        # Variance locale de la luminance : moyenne du carre moins carre de
        # la moyenne, sur une petite fenetre — proxy de texture standard.
        k = 5
        mean = cv2.blur(gray, (k, k))
        mean_sq = cv2.blur(gray * gray, (k, k))
        self.texture = np.maximum(mean_sq - mean * mean, 0.0)


def _mesure(champs: Champs, x: int, y: int, r: int) -> Dict[str, float]:
    h, w = champs.mask.shape
    y0, y1 = max(0, y - r), min(h, y + r + 1)
    x0, x1 = max(0, x - r), min(w, x + r + 1)
    m = champs.mask[y0:y1, x0:x1] > 0
    if m.sum() < 3:
        return {}
    exces = float(champs.exces[y0:y1, x0:x1][m].mean())
    fond = float(champs.fond_local[y0:y1, x0:x1][m].mean())
    return {
        "A_exces_absolu": exces,
        "B_contraste_relatif": exces / max(abs(fond), 3.0),
        "C_gradient": float(champs.gradient[y0:y1, x0:x1][m].mean()),
        "D_texture_locale": float(champs.texture[y0:y1, x0:x1][m].mean()),
    }


# --------------------------------------------------------------------------
def _points_peau_saine(mask: np.ndarray, lesions_xy: List[Tuple[int, int]],
                       n: int, r: int, seed: int) -> List[Tuple[int, int]]:
    """N points tires au hasard dans la peau exploitable, loin du bord et des
    lesions plantees — pour ne pas mesurer accidentellement une lesion comme
    si c'etait de la peau saine."""
    core = cv2.erode(mask, np.ones((r * 2 + 1, r * 2 + 1), np.uint8))
    ys, xs = np.nonzero(core)
    rng = np.random.default_rng(seed)
    ordre = rng.permutation(len(xs))
    out: List[Tuple[int, int]] = []
    for i in ordre:
        cx, cy = int(xs[i]), int(ys[i])
        if any((cx - lx) ** 2 + (cy - ly) ** 2 < (r * 3) ** 2 for lx, ly in lesions_xy):
            continue
        if any((cx - ox) ** 2 + (cy - oy) ** 2 < (r * 2) ** 2 for ox, oy in out):
            continue
        out.append((cx, cy))
        if len(out) >= n:
            break
    return out


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    pts = _landmarks(img)
    if pts is None:
        raise SystemExit("aucun visage detecte")

    # Lesions synthetiques plantees UNE FOIS, sur plusieurs zones — la verite
    # terrain de la "separabilite". `plant()` peint des la peinture LAB
    # RELATIVE deja corrigee (cf. audit anterieur) : valable quelle que soit
    # la carnation locale.
    marque = img.copy()
    lesions_xy: List[Tuple[int, int]] = []
    for zone in ("joue_g", "joue_d", "front", "menton"):
        marque, planted = plant(marque, pts, zone, 3, seed=SEED)
        lesions_xy.extend((p.x, p.y) for p in planted)

    fm = build_face_map(_b64(marque, quality=100))
    if not fm.detected:
        raise SystemExit("visage non detecte sur l'image marquee")

    face_w = max(1.0, float(fm.bbox[2]))
    px_per_mm = face_w / 140.0
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    r_patch = max(RAYON_PATCH, int(round(1.5 * px_per_mm)))

    skin_xy = _points_peau_saine(fm.skin_mask, lesions_xy, N_SKIN, r_patch, seed=SEED)
    print(f"{len(lesions_xy)} lesions plantees, {len(skin_xy)} patchs de peau saine\n")

    # --- Reference : mesure des deux populations sur l'image NON perturbee.
    champs_ref = Champs(marque, fm.skin_mask, sigma_bg)
    mesures_lesions = [_mesure(champs_ref, x, y, r_patch) for x, y in lesions_xy]
    mesures_skin = [_mesure(champs_ref, x, y, r_patch) for x, y in skin_xy]
    mesures_lesions = [m for m in mesures_lesions if m]
    mesures_skin = [m for m in mesures_skin if m]

    features = ["A_exces_absolu", "B_contraste_relatif", "C_gradient", "D_texture_locale"]

    print(f"{'feature':<22} {'lesion (moy±ecart)':<22} {'peau (moy±ecart)':<22} {'d de Cohen':>11}")
    separabilite: Dict[str, float] = {}
    ecart_lesion_peau: Dict[str, float] = {}
    for f in features:
        vl = np.array([m[f] for m in mesures_lesions])
        vs = np.array([m[f] for m in mesures_skin])
        pooled = np.sqrt((vl.var(ddof=1) + vs.var(ddof=1)) / 2) or 1e-6
        d = float((vl.mean() - vs.mean()) / pooled)
        separabilite[f] = d
        # L'ecart lesion/peau, PAS la valeur absolue d'un point, sert de
        # regle pour juger une derive. Diviser par la valeur de reference
        # d'un point aurait gonfle artificiellement la derive des patchs de
        # peau saine, dont la reference tourne autour de zero — un mouvement
        # minuscule y donne un pourcentage enorme sans rien dire d'utile.
        ecart_lesion_peau[f] = max(abs(vl.mean() - vs.mean()), 1e-3)
        print(f"{f:<22} {vl.mean():>8.2f} ± {vl.std():<9.2f} "
              f"{vs.mean():>8.2f} ± {vs.std():<9.2f} {d:>11.2f}")

    # --- Invariance : meme mesure, aux memes positions, sous chaque
    # perturbation photometrique. La derive de chaque point est rapportee a
    # L'ECART LESION/PEAU DE CETTE FEATURE : "quelle fraction du signal
    # discriminant cette perturbation efface-t-elle ?" — la question qui
    # compte reellement pour decider si une feature reste utilisable.
    print(f"\n{'perturbation':<18}", end="")
    for f in features:
        print(f"{f:>22}", end="")
    print()

    derive_totale: Dict[str, List[float]] = {f: [] for f in features}
    for nom, transforme in PERTURBATIONS:
        if nom == "original":
            continue
        bgr = transforme(marque)
        champs = Champs(bgr, fm.skin_mask, sigma_bg)
        print(f"{nom:<18}", end="")
        for f in features:
            drifts = []
            for (x, y), ref_m in zip(lesions_xy + skin_xy, mesures_lesions + mesures_skin):
                m = _mesure(champs, x, y, r_patch)
                if not m or f not in ref_m:
                    continue
                drifts.append(abs(m[f] - ref_m[f]) / ecart_lesion_peau[f])
            d_moy = float(np.mean(drifts)) if drifts else float("nan")
            derive_totale[f].append(d_moy)
            print(f"{d_moy:>21.1%} ", end="")
        print()

    print(f"\n{'feature':<22} {'d de Cohen (separe)':>20} {'derive / ecart discri.':>23}")
    for f in features:
        d_moy_globale = float(np.mean(derive_totale[f]))
        print(f"{f:<22} {separabilite[f]:>20.2f} {d_moy_globale:>22.1%}")

    # --- Ce qui compte reellement en production n'est pas la derive
    # continue, mais le NOMBRE DE PATCHS DE PEAU SAINE QUI FRANCHISSENT UN
    # SEUIL DE DECISION. Une derive moyenne minuscule peut quand meme faire
    # basculer beaucoup de points si leur population est dense pres de la
    # frontiere — c'est exactement ce que la moyenne de la section
    # precedente ne peut pas montrer. Seuil calibre UNE FOIS sur l'image de
    # reference (meme construction que le seuil robuste actuel), puis
    # applique tel quel a chaque perturbation.
    print(f"\n=== Faux positifs sur peau saine, a seuil fixe ===")
    print("(seuil calibre sur la reference, puis fige — pas re-calibre a chaque perturbation)\n")
    seuils: Dict[str, float] = {}
    for f in ("A_exces_absolu", "B_contraste_relatif"):
        vs = np.array([m[f] for m in mesures_skin])
        med = float(np.median(vs))
        mad = float(np.median(np.abs(vs - med))) or 1e-3
        seuils[f] = med + 2.2 * 1.4826 * mad  # meme k que RED_BLOB_K

    ref_fp = {f: sum(1 for m in mesures_skin if m[f] > seuils[f]) for f in seuils}
    print(f"{'perturbation':<18}" + "".join(f"{f:>22}" for f in seuils))
    print(f"{'(reference)':<18}" + "".join(f"{ref_fp[f]:>22}" for f in seuils))
    for nom, transforme in PERTURBATIONS:
        if nom == "original":
            continue
        bgr = transforme(marque)
        champs = Champs(bgr, fm.skin_mask, sigma_bg)
        ligne = []
        for f in seuils:
            fp = 0
            for x, y in skin_xy:
                m = _mesure(champs, x, y, r_patch)
                if m and m[f] > seuils[f]:
                    fp += 1
            ligne.append(fp)
        print(f"{nom:<18}" + "".join(f"{v:>22}" for v in ligne))


if __name__ == "__main__":
    run()
