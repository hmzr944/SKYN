"""Step 1 — Preprocessing.

MediaPipe Face Mesh provides 468 facial landmarks. From them we derive:
- a square face bounding box (used for cropping + normalising coords)
- pose correction (in-plane roll angle, applied before downstream analysis)
- ROI masks for T-zone (forehead, nose, chin) and U-zone (cheeks)
- a global luminance estimate used to detect low-light conditions
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
import mediapipe as mp


# Indices coming from the canonical MediaPipe Face Mesh (468 landmarks).
# Reference: https://github.com/google/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model_uv_visualization.png
LANDMARK_FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
]
LANDMARK_FOREHEAD = [10, 109, 67, 103, 54, 21, 162, 127, 234, 132, 93]
LANDMARK_NOSE = [1, 2, 98, 327, 168]
LANDMARK_CHIN = [152, 175, 199, 200]
LANDMARK_LEFT_CHEEK = [50, 101, 36, 205, 187]
LANDMARK_RIGHT_CHEEK = [280, 330, 266, 425, 411]


@dataclass
class Preprocessed:
    rgb: np.ndarray            # full image RGB (uint8)
    face_bbox: Tuple[int, int, int, int]  # (x, y, w, h) in original image pixels
    skin_mask: np.ndarray      # uint8 [0..255] over full image (only skin pixels)
    t_zone_mask: np.ndarray    # uint8
    u_zone_mask: np.ndarray    # uint8
    luminance_mean: float      # 0..255
    detected: bool             # face found?
    roll_deg: float            # in-plane rotation in degrees


def _decode_b64_to_bgr(image_b64: str) -> Optional[np.ndarray]:
    import base64
    try:
        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[-1]
        raw = base64.b64decode(image_b64, validate=False)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _resize_max(img: np.ndarray, max_side: int = 720) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    scale = max_side / m
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _build_mask(shape: Tuple[int, int], pts: np.ndarray, kernel: int = 0) -> np.ndarray:
    """Fill the polygon defined by pts on a single-channel mask."""
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [pts.astype(np.int32)], 255)
    if kernel > 0:
        mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    return mask


def preprocess(image_b64: str) -> Preprocessed:
    bgr = _decode_b64_to_bgr(image_b64)
    if bgr is None or bgr.size == 0:
        empty = np.zeros((1, 1), dtype=np.uint8)
        return Preprocessed(
            rgb=np.zeros((10, 10, 3), dtype=np.uint8),
            face_bbox=(0, 0, 10, 10),
            skin_mask=empty,
            t_zone_mask=empty,
            u_zone_mask=empty,
            luminance_mean=0.0,
            detected=False,
            roll_deg=0.0,
        )

    bgr = _resize_max(bgr, 720)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    luminance_mean = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).mean())

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.4,
    )
    try:
        result = face_mesh.process(rgb)
    finally:
        face_mesh.close()

    empty = np.zeros((h, w), dtype=np.uint8)
    if not result.multi_face_landmarks:
        return Preprocessed(
            rgb=rgb,
            face_bbox=(0, 0, w, h),
            skin_mask=empty,
            t_zone_mask=empty,
            u_zone_mask=empty,
            luminance_mean=luminance_mean,
            detected=False,
            roll_deg=0.0,
        )

    lms = result.multi_face_landmarks[0].landmark
    pts_all = np.array([[lm.x * w, lm.y * h] for lm in lms], dtype=np.float32)

    # Bounding box of the face
    x_min = float(pts_all[:, 0].min())
    y_min = float(pts_all[:, 1].min())
    x_max = float(pts_all[:, 0].max())
    y_max = float(pts_all[:, 1].max())
    bbox = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

    # Roll: vector between left eye outer corner (33) and right eye outer corner (263)
    left_eye = pts_all[33]
    right_eye = pts_all[263]
    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    roll_deg = math.degrees(math.atan2(dy, dx))

    # Build masks
    face_pts = pts_all[LANDMARK_FACE_OVAL]
    skin_mask = _build_mask((h, w), face_pts)

    forehead = _build_mask((h, w), pts_all[LANDMARK_FOREHEAD], kernel=15)
    nose = _build_mask((h, w), pts_all[LANDMARK_NOSE + LANDMARK_CHIN], kernel=15)
    t_zone_mask = cv2.max(forehead, nose)

    left_cheek = _build_mask((h, w), pts_all[LANDMARK_LEFT_CHEEK], kernel=15)
    right_cheek = _build_mask((h, w), pts_all[LANDMARK_RIGHT_CHEEK], kernel=15)
    u_zone_mask = cv2.max(left_cheek, right_cheek)

    # Restrict ROIs to skin area
    t_zone_mask = cv2.bitwise_and(t_zone_mask, skin_mask)
    u_zone_mask = cv2.bitwise_and(u_zone_mask, skin_mask)

    return Preprocessed(
        rgb=rgb,
        face_bbox=bbox,
        skin_mask=skin_mask,
        t_zone_mask=t_zone_mask,
        u_zone_mask=u_zone_mask,
        luminance_mean=luminance_mean,
        detected=True,
        roll_deg=roll_deg,
    )
