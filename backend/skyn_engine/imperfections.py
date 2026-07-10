"""Step 3 — Imperfection detection.

Primary path: YOLOv8 acne detector (skyn_engine/models/acne_yolo/acne.pt, see
ml_models.py). Falls back to the classical DoG blob detector when the model or
its dependencies are unavailable, keeping the exact same output contract.

To improve the model, fine-tune with backend/training/ and drop the new
weights at the same path — no code change needed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Tuple

import cv2
import numpy as np

from .preprocessing import Preprocessed


@dataclass
class Detection:
    type: str          # "pore" | "spot" | "redness"
    x: float           # normalized 0..1 (relative to face bbox)
    y: float           # normalized 0..1
    confidence: float  # 0..1
    radius: float      # normalized to bbox max dim


def _normalize_xy(x_px: float, y_px: float, bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    bx, by, bw, bh = bbox
    bw = max(1, bw)
    bh = max(1, bh)
    return (x_px - bx) / bw, (y_px - by) / bh


def _detect_dark_blobs(gray: np.ndarray, mask: np.ndarray, bbox, max_n: int = 6) -> List[Detection]:
    """Find dark micro-zones (proxy for spots/imperfections)."""
    if mask.sum() == 0:
        return []
    h, w = gray.shape[:2]
    # Blur, then look at residual against a wider blur (DoG-like, isotropic)
    blur_small = cv2.GaussianBlur(gray, (5, 5), 0)
    blur_big = cv2.GaussianBlur(gray, (35, 35), 0)
    dog = blur_big.astype(np.float32) - blur_small.astype(np.float32)
    dog[mask == 0] = 0
    # Strong dark spots have high positive DoG
    if dog.max() <= 0:
        return []
    # Adaptive threshold relative to the skin's mean DoG response
    mean_resp = float(dog[mask > 0].mean())
    std_resp = float(dog[mask > 0].std()) or 1.0
    thr = mean_resp + 2.5 * std_resp
    binary = (dog > thr).astype(np.uint8) * 255
    # Clean small noise
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    candidates: List[Detection] = []
    bx, by, bw, bh = bbox
    norm_dim = max(1, max(bw, bh))
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 4 or area > 200:
            continue
        cx, cy = float(centroids[i, 0]), float(centroids[i, 1])
        nx, ny = _normalize_xy(cx, cy, bbox)
        if not (0.05 < nx < 0.95 and 0.05 < ny < 0.95):
            continue
        radius_px = max(2.0, (area / 3.14) ** 0.5 * 1.6)
        conf = min(0.98, 0.55 + (area / 200.0) * 0.4)
        candidates.append(
            Detection(
                type="spot",
                x=float(nx),
                y=float(ny),
                confidence=float(conf),
                radius=float(radius_px / norm_dim),
            )
        )
    # Keep top max_n by confidence
    candidates.sort(key=lambda d: d.confidence, reverse=True)
    return candidates[:max_n]


def detect(pre: Preprocessed, max_n: int = 5) -> List[Detection]:
    """Public API. YOLOv8 model first, classical CV fallback.

    When the trained model runs successfully its verdict is final — zero
    detection means clear skin, NOT a reason to fall back to the (noisier)
    classical detector. CV only covers model-unavailable/error cases.
    """
    if not pre.detected:
        return []

    from .ml_models import get_acne_detector
    detector = get_acne_detector()
    if detector is not None:
        try:
            ml_dets = detector.detect(pre.rgb, pre.face_bbox, max_n=max_n)
            return [Detection(**d) for d in ml_dets]
        except Exception:
            pass  # fall back to classical CV below

    gray = cv2.cvtColor(pre.rgb, cv2.COLOR_RGB2GRAY)
    return _detect_dark_blobs(gray, pre.skin_mask, pre.face_bbox, max_n=max_n)


def to_dict_list(dets: List[Detection]) -> List[dict]:
    return [asdict(d) for d in dets]
