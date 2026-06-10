"""SKYN Engine pipeline orchestrator.

Single public entry point: analyze_skin(image_b64, profile_dict) -> AnalysisOutput.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .preprocessing import preprocess
from .cv_analysis import analyze as cv_analyze
from .imperfections import detect, to_dict_list
from .expert_system import ProfileCtx, diagnose, recommend


@dataclass
class AnalysisOutput:
    detected: bool
    luminance: float
    low_light: bool
    roll_deg: float
    global_score: int
    texture: int
    radiance: int
    imperfections: int
    detections: List[dict] = field(default_factory=list)
    diagnosis: str = ""
    recommendations: List[str] = field(default_factory=list)
    source: str = "skyn_engine_v1"
    debug: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp_score(v: float) -> int:
    return int(round(max(30, min(98, v))))


def analyze_skin(image_b64: str, profile_dict: Optional[dict] = None) -> AnalysisOutput:
    profile = ProfileCtx(
        age_range=(profile_dict or {}).get("age_range"),
        environment=(profile_dict or {}).get("environment"),
        priority=(profile_dict or {}).get("priority"),
    )

    pre = preprocess(image_b64)
    metrics = cv_analyze(pre)
    dets = detect(pre, max_n=5)

    # Refine imperfections score by penalising for #detections
    n_det = len(dets)
    imperf_score = _clamp_score(metrics.imperfections_pre - n_det * 4)

    # Soft-bias scores by profile priority — the area the user cares about is
    # always shown as slightly more demanding (so recos focus on it).
    priority = (profile.priority or "").lower()
    texture = metrics.texture
    radiance = metrics.radiance
    if "éclat" in priority or "eclat" in priority:
        radiance = _clamp_score(radiance - 4)
    if "ridule" in priority:
        texture = _clamp_score(texture - 4)
    if "imperfection" in priority:
        imperf_score = _clamp_score(imperf_score - 4)
    if "sensib" in priority and metrics.redness > 4.0:
        texture = _clamp_score(texture - 3)

    global_score = _clamp_score(texture * 0.34 + radiance * 0.33 + imperf_score * 0.33)

    metrics_d = {
        "texture": texture,
        "radiance": radiance,
        "imperfections": imperf_score,
        "redness": metrics.redness,
    }
    diag = diagnose(metrics_d, profile)
    recs = recommend(metrics_d, profile, diag)

    return AnalysisOutput(
        detected=pre.detected,
        luminance=metrics.luminance,
        low_light=metrics.luminance < 70.0,
        roll_deg=pre.roll_deg,
        global_score=global_score,
        texture=texture,
        radiance=radiance,
        imperfections=imperf_score,
        detections=to_dict_list(dets),
        diagnosis=diag,
        recommendations=recs,
        source="skyn_engine_v1",
        debug=metrics.raw,
    )
