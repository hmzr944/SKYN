"""Step 2 — Classical computer-vision analysis.

Texture: Laplacian variance (high-frequency content) and Sobel gradient density
on the U-zone (cheeks) → a "roughness" score we invert into a 0-100 texture
score where 100 = smooth.

Radiance & oiliness: convert to LAB and HSV, look at the L (lightness) channel
on the whole skin area. Dull skin = low L mean. Sebaceous shine = isolated
peaks of high L on the T-zone.

Sebum by zone: fraction of near-specular highlight pixels (very high L, low
saturation) on T-zone vs U-zone — a T-zone-only shine signature is the classic
dermatological marker of combination skin, independent of the ViT classifier.

Pores: morphological black-hat transform (small dark structures against a
locally bright background) on the T-zone — the standard classical-CV proxy for
visible/dilated pores, distinct from general roughness.

Fine lines: forehead-only edge-orientation analysis. Horizontal edges that
dominate over vertical ones at moderate-to-high gradient magnitude are the
signature of expression lines — far more specific to wrinkles than overall
texture roughness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import cv2
import numpy as np

from .preprocessing import Preprocessed


def _stat_on_mask(arr: np.ndarray, mask: np.ndarray) -> Dict[str, float]:
    if mask.sum() == 0:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    sel = arr[mask > 0]
    return {"mean": float(sel.mean()), "std": float(sel.std()), "n": int(sel.size)}


def _clamp(v: float, lo: float = 30.0, hi: float = 98.0) -> int:
    return int(round(max(lo, min(hi, v))))


@dataclass
class CVMetrics:
    texture: int          # 0..100 (higher = smoother)
    radiance: int         # 0..100
    imperfections_pre: int  # 0..100 from contrast-based pre-score (refined later)
    luminance: float
    redness: float
    raw: Dict[str, float]


def analyze(pre: Preprocessed) -> CVMetrics:
    if not pre.detected:
        return CVMetrics(
            texture=60, radiance=55, imperfections_pre=60,
            luminance=pre.luminance_mean, redness=0.0,
            raw={"detected": 0.0},
        )

    gray = cv2.cvtColor(pre.rgb, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(pre.rgb, cv2.COLOR_RGB2LAB)
    L = lab[:, :, 0]
    a = lab[:, :, 1]

    # Laplacian variance — high freq energy (the higher, the rougher)
    lap = cv2.Laplacian(gray, cv2.CV_64F, ksize=3)
    lap_abs = np.abs(lap).astype(np.float32)

    # Sobel gradient magnitude
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)

    # Texture is computed on U-zone (cheeks) — that's where pores/fine lines matter
    u_lap = _stat_on_mask(lap_abs, pre.u_zone_mask)
    u_grad = _stat_on_mask(grad, pre.u_zone_mask)

    # Empirically: typical face has lap_mean ~ 4-12. Map [3..16] -> [98..40].
    lap_mean = u_lap["mean"] if u_lap["n"] > 0 else 7.0
    grad_mean = u_grad["mean"] if u_grad["n"] > 0 else 12.0
    texture_raw = 100.0 - ((lap_mean - 3.0) / 13.0) * 58.0 - ((grad_mean - 8.0) / 16.0) * 6.0
    texture_score = _clamp(texture_raw)

    # Radiance — L channel mean & uniformity on full skin
    skin_L = _stat_on_mask(L.astype(np.float32), pre.skin_mask)
    L_mean = skin_L["mean"] if skin_L["n"] > 0 else 140.0
    L_std = skin_L["std"] if skin_L["n"] > 0 else 14.0
    # Bright + uniform = radiant
    radiance_raw = 30.0 + ((L_mean - 90.0) / 90.0) * 60.0 - max(0.0, (L_std - 14.0)) * 1.5
    radiance_score = _clamp(radiance_raw, lo=30, hi=98)

    # Pre-score for imperfections based on dark-spot prevalence in skin area
    # Threshold L below adaptive mean - 1*std → candidate dark pixels
    if skin_L["n"] > 0:
        thr = max(0.0, L_mean - L_std)
        dark_ratio = float(((L < thr) & (pre.skin_mask > 0)).sum()) / max(1.0, skin_L["n"])
    else:
        dark_ratio = 0.05
    # 5% dark pixels ~ neutral 80. 15% dark ~ 45.
    imperf_pre = _clamp(95.0 - (dark_ratio - 0.04) * 450.0)

    # Redness — LAB a-channel mean over skin (a~128 neutral; higher = redder)
    skin_a = _stat_on_mask(a.astype(np.float32), pre.skin_mask)
    redness = max(0.0, (skin_a["mean"] - 128.0)) if skin_a["n"] > 0 else 0.0

    # Sébum — reflets spéculaires (pixels très clairs) zone T vs joues.
    # Une zone T brillante avec des joues mates signe une peau mixte ;
    # brillance partout = peau grasse.
    Lf = L.astype(np.float32)
    shine_thr = min(252.0, L_mean + 2.0 * max(8.0, L_std))
    def _shine_ratio(mask: np.ndarray) -> float:
        n = int((mask > 0).sum())
        if n == 0:
            return 0.0
        return float(((Lf > shine_thr) & (mask > 0)).sum()) / n
    shine_t = _shine_ratio(pre.t_zone_mask)
    shine_u = _shine_ratio(pre.u_zone_mask)

    # Pores — black-hat morphologique (petites structures sombres sur fond
    # localement clair) sur la zone T, où les pores dilatés sont les plus
    # visibles. Standard en vision par ordinateur dermatologique.
    pore_density = 0.0
    if pre.t_zone_mask.sum() > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
        t_n = int((pre.t_zone_mask > 0).sum())
        bh_t = blackhat[pre.t_zone_mask > 0]
        bh_thr = max(6.0, float(bh_t.mean()) + float(bh_t.std()))
        pore_density = float((bh_t > bh_thr).sum()) / max(1.0, t_n)

    # Rides fines — sur le front, les lignes d'expression sont des arêtes à
    # dominante horizontale. On compare l'énergie de gradient horizontale à la
    # verticale : un excès d'horizontal à forte magnitude = rides marquées.
    fine_lines = 0.0
    if pre.forehead_mask.sum() > 0:
        fh = pre.forehead_mask > 0
        gx_f = gx[fh]
        gy_f = gy[fh]
        h_energy = float(np.mean(np.abs(gy_f)))   # gradient vertical = arête horizontale
        v_energy = float(np.mean(np.abs(gx_f))) + 1e-3
        line_ratio = h_energy / v_energy
        # Normalisé : ratio ~1 (isotrope) -> 0 ride ; ratio >1.6 -> rides nettes
        fine_lines = max(0.0, min(1.0, (line_ratio - 1.0) / 0.9))

    # Les pores dilatés sont un défaut de texture à part entière : on affine
    # le score texture déjà calculé (Laplacian/Sobel) avec ce signal dédié.
    texture_score = _clamp(texture_score - pore_density * 35.0)

    return CVMetrics(
        texture=texture_score,
        radiance=radiance_score,
        imperfections_pre=imperf_pre,
        luminance=pre.luminance_mean,
        redness=redness,
        raw={
            "u_lap_mean": lap_mean,
            "u_grad_mean": grad_mean,
            "L_mean": L_mean,
            "L_std": L_std,
            "dark_ratio": dark_ratio,
            "shine_t": shine_t,
            "shine_u": shine_u,
            "pore_density": pore_density,
            "fine_lines": fine_lines,
        },
    )
