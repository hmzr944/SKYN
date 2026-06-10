"""SKYN Engine — modular 3-step skin analysis pipeline.

Steps:
1. Preprocessing — MediaPipe Face Mesh isolates the face, computes pose, ROI zones.
2. CV analysis — Sobel/Laplacian for texture, LAB for radiance.
3. Imperfection detection — classical CV blob detection (placeholder for future
   YOLOv8 dermatology model — drop a .tflite/.onnx into ./models and swap the
   `imperfections.detect()` implementation).

All coordinates returned are normalized to the face bounding box in [0, 1] so the
frontend can render SVG overlays at any size without re-computing.
"""
from .pipeline import analyze_skin, AnalysisOutput  # noqa: F401
