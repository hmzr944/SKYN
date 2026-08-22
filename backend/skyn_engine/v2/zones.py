"""SKYN Engine v2 — Etape 1 : segmentation faciale multi-zones.

Ce module remplace `preprocessing.py` (v1) et corrige trois defauts majeurs :

1. v1 construisait un `skin_mask` = ovale du visage rempli. Les sourcils, cils,
   levres et narines etaient donc comptes comme de la PEAU. Comme le detecteur
   d'imperfections cherche des pixels sombres, une personne aux sourcils epais
   obtenait mecaniquement un moins bon score. On construit ici un masque
   d'exclusion explicite.

2. v1 ne detectait pas la pilosite. Une barbe est un ensemble de pixels sombres
   a haute frequence : elle etait comptee comme des dizaines d'imperfections.
   On detecte les zones pileuses et on les retire de l'analyse lesionnelle.

3. v1 calculait un `t_zone_mask` puis ne s'en servait JAMAIS (cf. cv_analysis.py
   qui ne lit que `u_zone_mask` et `skin_mask`). Sans differentiel zone T / zone U
   il est impossible de determiner un type de peau. On expose ici 13 zones.

Toutes les mesures sont faites apres correction de balance des blancs, pour que
la temperature de la lumiere ambiante ne soit pas lue comme une rougeur.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Cartographie des zones (indices MediaPipe Face Mesh, 468 landmarks)
# --------------------------------------------------------------------------
# Chaque zone est definie par un nuage de points dont on prend l'enveloppe
# convexe : l'ordre des indices n'a donc pas d'importance et le polygone ne
# peut pas s'auto-intersecter.

ZONE_LANDMARKS: Dict[str, List[int]] = {
    "front": [10, 109, 67, 103, 104, 105, 66, 107, 9, 336, 296, 334, 333, 332,
              297, 338, 151, 108, 69, 299, 337],
    "glabelle": [9, 107, 336, 8, 168, 6, 55, 285],
    "tempe_g": [21, 54, 103, 67, 162, 127, 234],
    "tempe_d": [251, 284, 332, 297, 389, 356, 454],
    "nez": [168, 6, 197, 195, 5, 4, 1, 19, 94, 45, 275, 220, 440, 115, 344],
    "joue_g": [116, 117, 118, 119, 120, 100, 142, 36, 205, 187, 123, 50, 101, 206],
    "joue_d": [345, 346, 347, 348, 349, 329, 371, 266, 425, 411, 352, 280, 330, 426],
    "sous_yeux_g": [226, 31, 228, 229, 230, 231, 232, 233, 244, 112, 110, 24, 23, 22, 26],
    "sous_yeux_d": [446, 261, 448, 449, 450, 451, 452, 453, 464, 341, 339, 254, 253, 252, 256],
    "peri_oral": [164, 165, 391, 393, 267, 269, 270, 409, 37, 39, 40, 185, 92, 322,
                  61, 291, 186, 410],
    "menton": [152, 175, 199, 200, 18, 83, 313, 421, 201, 208, 428, 32, 262, 396, 171],
    "machoire_g": [172, 136, 150, 149, 176, 148, 152, 58, 132, 93, 234],
    "machoire_d": [397, 365, 379, 378, 400, 377, 152, 288, 361, 323, 454],
}

# Poids cliniques inspires du Global Acne Grading System (GAGS), qui pondere
# les regions selon leur surface et leur densite en glandes sebacees.
# GAGS : front x2, chaque joue x2, nez x1, menton x1.
# On etend aux zones supplementaires ; la machoire porte un poids eleve car une
# acne majoritairement mandibulaire est un signe d'origine hormonale.
ZONE_WEIGHT: Dict[str, float] = {
    "front": 2.0,
    "glabelle": 1.0,
    "tempe_g": 1.0,
    "tempe_d": 1.0,
    "nez": 1.0,
    "joue_g": 2.0,
    "joue_d": 2.0,
    "sous_yeux_g": 0.5,
    "sous_yeux_d": 0.5,
    "peri_oral": 1.0,
    "menton": 1.0,
    "machoire_g": 1.5,
    "machoire_d": 1.5,
}

T_ZONE = ("front", "glabelle", "nez", "menton")
U_ZONE = ("joue_g", "joue_d", "machoire_g", "machoire_d")
# Zones ou la pilosite masculine se concentre : on y attend de la barbe.
HAIR_PRONE = ("peri_oral", "menton", "machoire_g", "machoire_d", "joue_g", "joue_d")

# Regions a EXCLURE du masque peau -----------------------------------------
EXCLUDE_LANDMARKS: Dict[str, List[int]] = {
    "oeil_g": [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
    "oeil_d": [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466],
    "sourcil_g": [70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
    "sourcil_d": [300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
    "levres": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269,
               267, 0, 37, 39, 40, 185, 78, 308],
    "narines": [98, 97, 2, 326, 327, 94],
}

FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
]


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------
@dataclass
class ZoneData:
    """Une region faciale et ses masques associes."""
    name: str
    mask: np.ndarray           # uint8 0/255, peau exploitable uniquement
    area_px: int               # nombre de pixels exploitables
    hair_ratio: float          # part de la zone occupee par de la pilosite
    available: bool            # surface suffisante pour mesurer ?
    weight: float              # poids clinique GAGS-like


@dataclass
class Quality:
    """Controle qualite de la prise de vue."""
    blur: float                # nettete normalisee (plus haut = plus net)
    exposure: float            # luminance moyenne 0..255 sur la peau
    clipped: float             # part de pixels satures (0..1)
    face_ratio: float          # taille du visage / image
    roll_deg: float            # rotation dans le plan
    yaw_proxy: float           # -1 (profil gauche) .. 0 (face) .. 1 (profil droit)
    usable: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class FaceMap:
    rgb: np.ndarray            # image corrigee en balance des blancs
    l_flat: np.ndarray         # luminance a eclairage aplani (float32)
    lab: np.ndarray            # LAB de l'image corrigee (float32)
    skin_mask: np.ndarray      # peau nette, exclusions retirees
    hair_mask: np.ndarray      # pilosite detectee
    zones: Dict[str, ZoneData]
    bbox: Tuple[int, int, int, int]
    quality: Quality
    detected: bool

    def zone(self, name: str) -> Optional[ZoneData]:
        z = self.zones.get(name)
        return z if (z and z.available) else None

    def group_mask(self, names) -> np.ndarray:
        """Masque combine de plusieurs zones disponibles."""
        out = None
        for n in names:
            z = self.zone(n)
            if z is None:
                continue
            out = z.mask.copy() if out is None else cv2.max(out, z.mask)
        if out is None:
            return np.zeros(self.skin_mask.shape, dtype=np.uint8)
        return out


# --------------------------------------------------------------------------
# Pretraitement image
# --------------------------------------------------------------------------
def _decode(image_b64: str) -> Optional[np.ndarray]:
    try:
        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[-1]
        raw = base64.b64decode(image_b64, validate=False)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _resize_max(img: np.ndarray, max_side: int = 1024) -> np.ndarray:
    """1024px (contre 720 en v1) : les comedons font quelques pixels de large,
    sous-echantillonner les efface purement et simplement."""
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    s = max_side / m
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def white_balance(bgr: np.ndarray, p: float = 6.0) -> np.ndarray:
    """Correction "shades of grey" (norme de Minkowski).

    Sans cela, une lumiere chaude (ampoule a incandescence, coucher de soleil)
    augmente le canal rouge et l'algorithme conclut a une rougeur cutanee. C'est
    une source d'erreur systematique en v1, qui lisait le canal a* de LAB brut.
    """
    img = bgr.astype(np.float32)
    out = np.empty_like(img)
    for c in range(3):
        ch = img[:, :, c]
        norm = float(np.power(np.mean(np.power(ch, p)), 1.0 / p))
        out[:, :, c] = ch / max(norm, 1e-6)
    # Reechelonne sur la moyenne des canaux pour conserver l'exposition globale
    scale = float(img.mean()) / max(float(out.mean()), 1e-6)
    return np.clip(out * scale, 0, 255).astype(np.uint8)


def _flatten_illumination(l_chan: np.ndarray, face_w: int) -> np.ndarray:
    """Retire l'ombrage a grande echelle en conservant le detail local.

    Le modele du visage est courbe : le nez et les pommettes recoivent plus de
    lumiere que les tempes. Sans aplanissement, ce gradient est lu comme un
    manque d'uniformite du teint chez tout le monde.
    """
    sigma = max(6.0, face_w / 6.0)
    low = cv2.GaussianBlur(l_chan, (0, 0), sigma)
    flat = l_chan - low + float(np.mean(low))
    return flat.astype(np.float32)


def _poly_mask(shape, pts: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if len(pts) < 3:
        return mask
    hull = cv2.convexHull(pts.astype(np.int32))
    cv2.fillConvexPoly(mask, hull, 255)
    return mask


def _detect_hair(rgb: np.ndarray, l_flat: np.ndarray, skin: np.ndarray,
                 face_w: int) -> np.ndarray:
    """Detecte barbe, moustache et cheveux empietant sur le visage.

    Signature de la pilosite : structure sombre, fine et directionnelle. On
    combine un seuil sur la luminance aplanie (le poil est nettement plus sombre
    que la peau voisine) et une forte densite de gradient, puis on ferme
    morphologiquement pour obtenir des plaques et non des pixels isoles.
    """
    if skin.sum() == 0:
        return np.zeros(skin.shape, dtype=np.uint8)

    sel = l_flat[skin > 0]
    med = float(np.median(sel))
    mad = float(np.median(np.abs(sel - med))) or 1.0

    # Poil = nettement plus sombre que la peau environnante
    dark = ((l_flat < med - 3.0 * mad) & (skin > 0)).astype(np.uint8) * 255

    # ... et texture dense (le poil cree beaucoup de contours rapproches)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    k = max(3, int(face_w / 40) | 1)
    grad_density = cv2.blur(grad, (k, k))
    gsel = grad_density[skin > 0]
    gthr = float(np.percentile(gsel, 80)) if gsel.size else 0.0
    textured = ((grad_density > gthr) & (skin > 0)).astype(np.uint8) * 255

    hair = cv2.bitwise_and(dark, textured)
    # Regroupe en plaques : un poil isole n'est pas une barbe
    kk = max(3, int(face_w / 60) | 1)
    hair = cv2.morphologyEx(hair, cv2.MORPH_CLOSE, np.ones((kk, kk), np.uint8))
    hair = cv2.morphologyEx(hair, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return hair


def _assess_quality(gray: np.ndarray, skin: np.ndarray, bbox, img_shape,
                    roll: float, yaw: float) -> Quality:
    bx, by, bw, bh = bbox
    h, w = img_shape[:2]
    face_ratio = (bw * bh) / float(max(1, w * h))

    issues: List[str] = []
    if skin.sum() > 0:
        sel = gray[skin > 0].astype(np.float32)
        exposure = float(sel.mean())
        clipped = float(((sel >= 250) | (sel <= 5)).sum()) / float(sel.size)
    else:
        exposure, clipped = 0.0, 1.0

    # Nettete : variance du laplacien normalisee par la taille du visage, sinon
    # une photo de loin parait floue et une photo de pres parait nette.
    lap = cv2.Laplacian(gray, cv2.CV_64F, ksize=3)
    face_reg = lap[max(0, by):by + bh, max(0, bx):bx + bw]
    blur = float(face_reg.var()) if face_reg.size else 0.0
    blur_norm = blur / max(1.0, (bw / 200.0) ** 2)

    if blur_norm < 40:
        issues.append("flou")
    if exposure < 70:
        issues.append("sous_expose")
    elif exposure > 205:
        issues.append("sur_expose")
    if clipped > 0.12:
        issues.append("contre_jour")
    if face_ratio < 0.05:
        issues.append("visage_trop_loin")
    if abs(roll) > 20:
        issues.append("tete_inclinee")
    if abs(yaw) > 0.45:
        issues.append("visage_de_profil")

    usable = not any(i in issues for i in
                     ("flou", "sous_expose", "sur_expose", "visage_trop_loin",
                      "visage_de_profil"))
    return Quality(blur=blur_norm, exposure=exposure, clipped=clipped,
                   face_ratio=face_ratio, roll_deg=roll, yaw_proxy=yaw,
                   usable=usable, issues=issues)


def _empty_map(rgb: np.ndarray, issues: List[str]) -> FaceMap:
    h, w = rgb.shape[:2] if rgb.size else (10, 10)
    empty = np.zeros((h, w), dtype=np.uint8)
    return FaceMap(
        rgb=rgb if rgb.size else np.zeros((10, 10, 3), np.uint8),
        l_flat=np.zeros((h, w), np.float32),
        lab=np.zeros((h, w, 3), np.float32),
        skin_mask=empty, hair_mask=empty, zones={},
        bbox=(0, 0, w, h),
        quality=Quality(0, 0, 1, 0, 0, 0, False, issues),
        detected=False,
    )


# --------------------------------------------------------------------------
# API publique
# --------------------------------------------------------------------------
def build_face_map(image_b64: str) -> FaceMap:
    """Decode une image et en extrait la carte faciale complete."""
    bgr = _decode(image_b64)
    if bgr is None or bgr.size == 0:
        return _empty_map(np.zeros((10, 10, 3), np.uint8), ["image_illisible"])

    bgr = _resize_max(bgr, 1024)
    bgr = white_balance(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    landmarks = _landmarks(rgb)
    if landmarks is None:
        return _empty_map(rgb, ["visage_non_detecte"])

    pts = np.array([[lm.x * w, lm.y * h] for lm in landmarks], dtype=np.float32)

    x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
    x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
    bbox = (int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    face_w = max(1, bbox[2])

    # Pose
    le, re = pts[33], pts[263]
    roll = math.degrees(math.atan2(re[1] - le[1], re[0] - le[0]))
    # Lacet : ecart du nez au milieu des deux oreilles, normalise
    nose_x = float(pts[1][0])
    ear_l, ear_r = float(pts[234][0]), float(pts[454][0])
    mid = (ear_l + ear_r) / 2.0
    half = max(1.0, abs(ear_r - ear_l) / 2.0)
    yaw = float((nose_x - mid) / half)

    # Masque peau = ovale du visage MOINS les exclusions
    oval = _poly_mask((h, w), pts[FACE_OVAL])
    exclusion = np.zeros((h, w), dtype=np.uint8)
    for name, idx in EXCLUDE_LANDMARKS.items():
        m = _poly_mask((h, w), pts[idx])
        # Dilate : les cils et le contour des levres debordent du polygone
        pad = max(3, int(face_w / 55) | 1)
        m = cv2.dilate(m, np.ones((pad, pad), np.uint8))
        exclusion = cv2.max(exclusion, m)

    # Sillons nasogeniens : le pli qui descend de l'aile du nez a la commissure
    # des levres est une OMBRE lineaire, pas une lesion. Sans exclusion il
    # ressort comme un chapelet de comedons chez toute personne qui sourit.
    fold_w = max(3, int(face_w / 22))
    for ala, corner in ((129, 61), (358, 291)):
        p0 = tuple(np.round(pts[ala]).astype(int))
        p1 = tuple(np.round(pts[corner]).astype(int))
        cv2.line(exclusion, p0, p1, 255, fold_w)

    skin = cv2.bitwise_and(oval, cv2.bitwise_not(exclusion))
    # Erode : les bords de l'ovale attrapent cheveux, duvet et arriere-plan
    er = max(3, int(face_w / 32) | 1)
    skin = cv2.erode(skin, np.ones((er, er), np.uint8))

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    l_chan = lab[:, :, 0]
    l_flat = _flatten_illumination(l_chan, face_w)

    hair = _detect_hair(rgb, l_flat, skin, face_w)
    skin_clean = cv2.bitwise_and(skin, cv2.bitwise_not(hair))

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    quality = _assess_quality(gray, skin, bbox, rgb.shape, roll, yaw)

    # Construction des zones
    min_area = max(60, int((face_w ** 2) * 0.0012))
    zones: Dict[str, ZoneData] = {}
    for name, idx in ZONE_LANDMARKS.items():
        raw = _poly_mask((h, w), pts[idx])
        raw = cv2.bitwise_and(raw, skin)                 # peau, exclusions retirees
        usable_m = cv2.bitwise_and(raw, cv2.bitwise_not(hair))
        area_raw = int((raw > 0).sum())
        area_use = int((usable_m > 0).sum())
        hair_ratio = 1.0 - (area_use / area_raw) if area_raw > 0 else 0.0
        zones[name] = ZoneData(
            name=name,
            mask=usable_m,
            area_px=area_use,
            hair_ratio=float(hair_ratio),
            available=area_use >= min_area,
            weight=ZONE_WEIGHT.get(name, 1.0),
        )

    return FaceMap(
        rgb=rgb, l_flat=l_flat, lab=lab,
        skin_mask=skin_clean, hair_mask=hair, zones=zones,
        bbox=bbox, quality=quality, detected=True,
    )


_FACE_MESH = None


def _landmarks(rgb: np.ndarray):
    """Landmarks MediaPipe. Retourne None si aucun visage."""
    global _FACE_MESH
    try:
        import mediapipe as mp
    except Exception:
        return None

    try:
        if _FACE_MESH is None:
            _FACE_MESH = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.3,
            )
        res = _FACE_MESH.process(rgb)
    except Exception:
        return None

    if not res or not res.multi_face_landmarks:
        return None
    return res.multi_face_landmarks[0].landmark
