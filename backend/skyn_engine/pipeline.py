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
from .products import recommend_products

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
    products: List[dict] = field(default_factory=list)
    skin_type_detected: Optional[str] = None      # "Sèche" | "Normale" | "Grasse"
    skin_type_confidence: float = 0.0
    acne_severity_level: Optional[int] = None     # -1 (nette) .. 3 (sévère)
    acne_severity_label: Optional[str] = None
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

    # --- Trained models (SKYN Engine v2) — each one optional, CV fallback kept ---
    ml_used = False
    skin_type_detected: Optional[str] = None
    skin_type_conf = 0.0
    severity_level: Optional[int] = None
    severity_label: Optional[str] = None

    if pre.detected:
        from .ml_models import get_skin_type_classifier, get_severity_classifier

        clf_type = get_skin_type_classifier()
        if clf_type is not None:
            try:
                skin_type_detected, skin_type_conf = clf_type.skin_type(pre.rgb, pre.face_bbox)
                ml_used = skin_type_detected is not None
            except Exception:
                pass

        clf_sev = get_severity_classifier()
        if clf_sev is not None:
            try:
                severity_level, severity_label, _ = clf_sev.severity(pre.rgb, pre.face_bbox)
                ml_used = True
            except Exception:
                pass

    # Refine imperfections score by penalising for #detections
    n_det = len(dets)
    imperf_score = _clamp_score(metrics.imperfections_pre - n_det * 4)

    # Clinical severity grading (ViT) dominates the heuristic penalty when present:
    # a confirmed clear skin lifts the score, confirmed acne lowers it per grade.
    if severity_level is not None:
        if severity_level <= -1:
            imperf_score = max(imperf_score, 80)
        elif severity_level == 0:
            imperf_score = max(imperf_score, 68)
        else:
            imperf_score = _clamp_score(imperf_score - severity_level * 7)

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
    # Type de peau effectif : déclaré par l'utilisateur, sinon détecté sur la
    # photo (si confiance suffisante) — alimente les règles du système expert.
    profile.skin_type = (profile_dict or {}).get("skin_type") or (
        skin_type_detected if skin_type_conf >= 0.5 else None
    )

    diag = diagnose(metrics_d, profile)
    # Clinical grading overrides the heuristic diagnosis when acne is confirmed
    if severity_level is not None and severity_level >= 2:
        diag = "Imperfections actives"
    recs = recommend(metrics_d, profile, diag)

    # Personalisation: the detected skin type completes the questionnaire when
    # the user hasn't declared one (photo evidence > missing data).
    product_profile = dict(profile_dict or {})
    if not product_profile.get("skin_type") and skin_type_detected and skin_type_conf >= 0.5:
        product_profile["skin_type"] = skin_type_detected
    products = recommend_products(metrics_d, product_profile)

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
        products=products,
        skin_type_detected=skin_type_detected,
        skin_type_confidence=round(skin_type_conf, 3),
        acne_severity_level=severity_level,
        acne_severity_label=severity_label,
        source="skyn_engine_v2" if ml_used else "skyn_engine_v1",
        debug=metrics.raw,
    )
