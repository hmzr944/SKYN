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
    angles_analyzed: int = 1                      # 1 (face) à 3 (face + profils)
    source: str = "skyn_engine_v1"
    debug: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

def _clamp_score(v: float) -> int:
    return int(round(max(30, min(98, v))))


def analyze_skin_multi(
    images_b64: List[str], profile_dict: Optional[dict] = None,
) -> AnalysisOutput:
    """Analyse multi-angles : la première image (face) porte l'analyse complète ;
    les profils (droite/gauche) passent dans le détecteur de lésions pour couvrir
    les joues et les tempes, invisibles de face. Le score imperfections intègre
    les lésions latérales ; les détections affichées restent celles de face
    (cohérence avec l'overlay)."""
    images_b64 = [i for i in images_b64 if i]
    if not images_b64:
        return analyze_skin("", profile_dict)

    out = analyze_skin(images_b64[0], profile_dict)
    if not out.detected or len(images_b64) == 1:
        return out

    side_lesions = 0
    angles = 1
    for side_b64 in images_b64[1:3]:
        try:
            pre = preprocess(side_b64)
            if not pre.detected:
                continue
            side_lesions += len(detect(pre, max_n=5))
            angles += 1
        except Exception:
            continue

    if angles > 1:
        out.angles_analyzed = angles
        if side_lesions:
            # Pénalité douce : les lésions latérales comptent moitié moins
            # (recouvrement partiel possible avec la vue de face)
            out.imperfections = _clamp_score(out.imperfections - side_lesions * 2)
            out.global_score = _clamp_score(
                out.texture * 0.34 + out.radiance * 0.33 + out.imperfections * 0.33
            )
            out.debug["side_lesions"] = float(side_lesions)
    return out


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

        # Peau mixte : le ViT ne connaît que sèche/normale/grasse. Une zone T
        # brillante avec des joues mates est la signature d'une peau mixte —
        # elle prime sur un verdict "normale/sèche" peu differencié.
        shine_t = float(metrics.raw.get("shine_t", 0.0))
        shine_u = float(metrics.raw.get("shine_u", 0.0))
        if shine_t >= 0.05 and (shine_t - shine_u) >= 0.03:
            if skin_type_detected in (None, "Normale", "Sèche") or skin_type_conf < 0.38:
                skin_type_detected = "Mixte"
                skin_type_conf = max(skin_type_conf, 0.55)
                ml_used = True

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
        "shine_t": float(metrics.raw.get("shine_t", 0.0)),
        "pore_density": float(metrics.raw.get("pore_density", 0.0)),
        "fine_lines": float(metrics.raw.get("fine_lines", 0.0)),
    }
    # Type de peau effectif : déclaré par l'utilisateur, sinon détecté sur la
    # photo (si confiance suffisante) — alimente les règles du système expert.
    profile.skin_type = (profile_dict or {}).get("skin_type") or (
        skin_type_detected if skin_type_conf >= 0.38 else None
    )

    diag = diagnose(metrics_d, profile)
    # Clinical grading overrides the heuristic diagnosis when acne is confirmed
    if severity_level is not None and severity_level >= 2:
        diag = "Imperfections actives"
    recs = recommend(metrics_d, profile, diag)

    # Personalisation: the detected skin type completes the questionnaire when
    # the user hasn't declared one (photo evidence > missing data).
    product_profile = dict(profile_dict or {})
    if not product_profile.get("skin_type") and skin_type_detected and skin_type_conf >= 0.38:
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
