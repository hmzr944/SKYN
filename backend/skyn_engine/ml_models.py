"""SKYN Engine v2 — trained ML models (lazy singletons, graceful fallback).

Three models, all loaded from skyn_engine/models/ (see scripts/download_models.py):

1. Acne detector      — YOLOv8 fine-tuned on acne imagery (Tinny-Robot/acne).
                        Object detection: returns typed, localised lesions.
2. Acne severity      — ViT-base fine-tuned (imfarzanansari/skintelligent-acne).
                        5 clinical levels: -1 (clear) .. 3 (severe).
3. Skin type          — ViT-base fine-tuned (dima806/skin_types_image_detection).
                        dry / normal / oily, mapped to the app's French labels.

Every accessor returns None when weights or dependencies are missing, so the
pipeline transparently falls back to the classical CV v1 path. A re-trained
model dropped into models/acne_yolo/acne.pt is picked up without code change
(see backend/training/ for the fine-tuning pipeline).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# SKYN_MODELS_DIR permet de stocker les poids hors du code (ex: /models en cloud)
MODELS_DIR = Path(os.environ.get("SKYN_MODELS_DIR", Path(__file__).parent / "models"))
ACNE_YOLO_WEIGHTS = MODELS_DIR / "acne_yolo" / "acne.pt"
ACNE_SEVERITY_DIR = MODELS_DIR / "acne_severity"
SKIN_TYPE_DIR = MODELS_DIR / "skin_type"

_lock = threading.Lock()
_cache: dict = {}

SKIN_TYPE_FR = {"dry": "Sèche", "normal": "Normale", "oily": "Grasse"}

SEVERITY_FR = {
    -1: "Peau nette",
    0: "Acné très légère",
    1: "Acné légère",
    2: "Acné modérée",
    3: "Acné sévère",
}


def _face_crop(rgb: np.ndarray, bbox: Tuple[int, int, int, int], margin: float = 0.15) -> np.ndarray:
    """Crop the face bbox with a safety margin, clamped to image bounds."""
    h, w = rgb.shape[:2]
    x, y, bw, bh = bbox
    mx, my = int(bw * margin), int(bh * margin)
    x0 = max(0, x - mx)
    y0 = max(0, y - my)
    x1 = min(w, x + bw + mx)
    y1 = min(h, y + bh + my)
    crop = rgb[y0:y1, x0:x1]
    return crop if crop.size else rgb


class AcneDetector:
    """YOLOv8 lesion detector. Coordinates are returned normalised to the face bbox."""

    def __init__(self, weights: Path):
        from ultralytics import YOLO
        self.model = YOLO(str(weights))

    def detect(
        self,
        rgb: np.ndarray,
        bbox: Tuple[int, int, int, int],
        max_n: int = 5,
        conf_threshold: float = 0.25,
    ) -> List[dict]:
        # augment=True : test-time augmentation (flip/échelles) — meilleur rappel
        results = self.model.predict(rgb, conf=conf_threshold, augment=True, verbose=False)
        bx, by, bw, bh = bbox
        bw = max(1, bw)
        bh = max(1, bh)
        norm_dim = max(bw, bh)

        dets: List[dict] = []
        for r in results:
            if r.boxes is None:
                continue
            names = r.names or {}
            for b in r.boxes:
                x0, y0, x1, y1 = [float(v) for v in b.xyxy[0].tolist()]
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                nx, ny = (cx - bx) / bw, (cy - by) / bh
                # Keep only lesions inside the face area
                if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
                    continue
                radius_px = max(2.0, max(x1 - x0, y1 - y0) / 2.0)
                cls_name = str(names.get(int(b.cls[0]), "acne")).lower()
                dets.append({
                    "type": cls_name if cls_name else "acne",
                    "x": float(min(1.0, max(0.0, nx))),
                    "y": float(min(1.0, max(0.0, ny))),
                    "confidence": float(b.conf[0]),
                    "radius": float(radius_px / norm_dim),
                })
        dets.sort(key=lambda d: d["confidence"], reverse=True)
        return dets[:max_n]


class _VitClassifier:
    """Shared ViT image-classification wrapper (transformers, CPU)."""

    def __init__(self, model_dir: Path):
        import torch  # noqa: F401 — ensures torch is importable before transformers
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        self.processor = AutoImageProcessor.from_pretrained(str(model_dir))
        self.model = AutoModelForImageClassification.from_pretrained(str(model_dir))
        self.model.eval()

    def classify(self, rgb: np.ndarray) -> Tuple[str, float]:
        """Prédiction moyennée image + miroir : plus stable qu'une passe unique."""
        import torch
        from PIL import Image
        img = Image.fromarray(rgb)
        inputs = self.processor(
            images=[img, img.transpose(Image.FLIP_LEFT_RIGHT)], return_tensors="pt",
        )
        with torch.no_grad():
            logits = self.model(**inputs).logits
        probs = torch.softmax(logits, dim=-1).mean(dim=0)
        idx = int(probs.argmax())
        label = self.model.config.id2label[idx]
        return label, float(probs[idx])


class AcneSeverityClassifier(_VitClassifier):
    def severity(self, rgb: np.ndarray, bbox) -> Tuple[int, str, float]:
        label, conf = self.classify(_face_crop(rgb, bbox))
        # Model labels: "level -1" .. "level 3"
        try:
            level = int(label.replace("level", "").strip())
        except ValueError:
            level = 0
        return level, SEVERITY_FR.get(level, "Acné légère"), conf


class SkinTypeClassifier(_VitClassifier):
    def skin_type(self, rgb: np.ndarray, bbox) -> Tuple[Optional[str], float]:
        label, conf = self.classify(_face_crop(rgb, bbox))
        return SKIN_TYPE_FR.get(label.lower()), conf


def _get(key: str, builder):
    """Thread-safe lazy singleton; a failed load is cached as None (no retry storm)."""
    if key in _cache:
        return _cache[key]
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            _cache[key] = builder()
            logger.info(f"SKYN ML model loaded: {key}")
        except Exception as e:
            logger.warning(f"SKYN ML model '{key}' unavailable ({e}); using CV fallback.")
            _cache[key] = None
    return _cache[key]


def get_acne_detector() -> Optional[AcneDetector]:
    if not ACNE_YOLO_WEIGHTS.exists():
        return None
    return _get("acne_yolo", lambda: AcneDetector(ACNE_YOLO_WEIGHTS))


def get_severity_classifier() -> Optional[AcneSeverityClassifier]:
    if not (ACNE_SEVERITY_DIR / "model.safetensors").exists():
        return None
    return _get("acne_severity", lambda: AcneSeverityClassifier(ACNE_SEVERITY_DIR))


def get_skin_type_classifier() -> Optional[SkinTypeClassifier]:
    if not (SKIN_TYPE_DIR / "model.safetensors").exists():
        return None
    return _get("skin_type", lambda: SkinTypeClassifier(SKIN_TYPE_DIR))
