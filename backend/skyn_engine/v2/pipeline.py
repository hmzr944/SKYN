"""SKYN Engine v2 — orchestrateur.

Point d'entree public : `analyze_face(image_b64, profile)` et
`analyze_multi(images, profile)` pour combiner plusieurs angles de prise de vue.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .zones import build_face_map, FaceMap
from .phenotype import analyze_phenotype, Phenotype
from .lesions import detect_lesions, LesionReport
from .concerns import build_fingerprint, SkinFingerprint, CONCERN_KEYS
from .matching import build_routine, Routine

ENGINE_VERSION = "skyn_engine_v2"


@dataclass
class FaceAnalysis:
    ok: bool
    engine: str
    global_score: int
    confidence: float
    skin_type: str
    skin_type_confidence: float
    phototype: str
    phototype_label: str
    ita_deg: float
    severity_level: int
    severity_label: str
    gags_score: float
    diagnosis: str
    summary: str
    concerns: Dict[str, float] = field(default_factory=dict)
    top_concerns: List[str] = field(default_factory=list)
    drivers: Dict[str, str] = field(default_factory=dict)
    lesion_counts: Dict[str, int] = field(default_factory=dict)
    lesions: List[dict] = field(default_factory=list)
    per_zone: Dict[str, dict] = field(default_factory=dict)
    zone_scores: Dict[str, int] = field(default_factory=dict)
    hormonal_pattern: bool = False
    routine: Dict = field(default_factory=dict)
    cautions: List[str] = field(default_factory=list)
    quality: Dict = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
CONCERN_FR = {
    "acne_active": "lesions inflammatoires actives",
    "comedons": "comedons",
    "post_acne_marks": "marques post-acne",
    "sebum": "production de sebum",
    "pores": "pores dilates",
    "redness": "rougeurs diffuses",
    "sensitivity": "reactivite",
    "dehydration": "deshydratation",
    "dullness": "teint terne",
    "pigmentation": "irregularites pigmentaires",
    "texture": "grain de peau irregulier",
    "barrier_damage": "barriere cutanee alteree",
    "aging": "signes de vieillissement",
}

ZONE_FR = {
    "front": "le front", "glabelle": "l'entre-sourcils", "nez": "le nez",
    "joue_g": "la joue gauche", "joue_d": "la joue droite",
    "menton": "le menton", "machoire_g": "la machoire gauche",
    "machoire_d": "la machoire droite", "peri_oral": "le pourtour de la bouche",
    "tempe_g": "la tempe gauche", "tempe_d": "la tempe droite",
    "sous_yeux_g": "le dessous de l'oeil gauche",
    "sous_yeux_d": "le dessous de l'oeil droit",
}


def _diagnosis(fp: SkinFingerprint, ph: Phenotype, lr: LesionReport) -> str:
    """Intitule clinique court, construit a partir des axes dominants.

    v1 choisissait parmi sept intitules figes, dont un seul revenait dans 48 %
    des cas. Ici l'intitule est compose : type de peau mesure + preoccupation
    dominante, ce qui multiplie mecaniquement les combinaisons.
    """
    if not fp.top_concerns:
        return f"Peau {ph.skin_type} equilibree"

    first = fp.top_concerns[0]
    if first == "acne_active":
        label = {
            0: "sans lesion active", 1: "acne legere", 2: "acne moderee",
            3: "acne severe", 4: "acne tres severe",
        }.get(lr.severity_level, "acne")
        base = f"Peau {ph.skin_type} — {label}"
        if lr.hormonal_pattern:
            base += ", repartition mandibulaire"
        return base

    return f"Peau {ph.skin_type} — {CONCERN_FR.get(first, first)}"


def _summary(fp: SkinFingerprint, ph: Phenotype, lr: LesionReport,
             fm: FaceMap) -> str:
    """Deux a trois phrases expliquant ce qui a ete mesure, et ou."""
    bits: List[str] = []

    tot = len(lr.lesions)
    if tot:
        infl = lr.counts.get("papule", 0) + lr.counts.get("pustule", 0)
        where = ", ".join(ZONE_FR.get(z, z) for z in lr.dominant_zones[:2])
        s = f"{tot} lesions reperees"
        if infl:
            s += f", dont {infl} inflammatoires"
        if where:
            s += f", concentrees sur {where}"
        bits.append(s + ".")
    else:
        bits.append("Aucune lesion active reperee sur les zones analysees.")

    if ph.skin_type == "mixte":
        bits.append(
            f"La zone T brille nettement plus que les joues "
            f"(ecart {ph.shine_delta:+.2f}), signature d'une peau mixte."
        )
    elif ph.skin_type == "grasse":
        bits.append("Brillance homogene sur l'ensemble du visage, y compris les joues.")
    elif ph.skin_type == "seche":
        bits.append("Peu de reflexion speculaire et grain marque : peau seche.")

    second = [c for c in fp.top_concerns[1:3]]
    if second:
        bits.append(
            "Autres points releves : "
            + ", ".join(CONCERN_FR.get(c, c) for c in second) + "."
        )

    if fm.quality.issues:
        bits.append(
            "Qualite de prise de vue perfectible ("
            + ", ".join(i.replace("_", " ") for i in fm.quality.issues)
            + ") : le resultat gagnerait a etre confirme par un nouveau scan."
        )
    return " ".join(bits)


def _zone_scores(fp: SkinFingerprint, lr: LesionReport, fm: FaceMap) -> Dict[str, int]:
    """Note 0-100 par zone, pour la cartographie affichee dans l'application."""
    out: Dict[str, int] = {}
    for name, z in fm.zones.items():
        if not z.available:
            continue
        d = lr.density.get(name, 0.0)
        per = lr.per_zone.get(name, {})
        infl = per.get("papule", 0) + per.get("pustule", 0)
        burden = min(1.0, d / 3.0) * 0.6 + min(1.0, infl / 6.0) * 0.4
        out[name] = int(round(100 * (1.0 - burden)))
    return out


def analyze_face(image_b64: str, profile: Optional[dict] = None) -> FaceAnalysis:
    t0 = time.time()
    profile = profile or {}

    fm = build_face_map(image_b64)
    if not fm.detected:
        return FaceAnalysis(
            ok=False, engine=ENGINE_VERSION, global_score=0, confidence=0.0,
            skin_type="indetermine", skin_type_confidence=0.0,
            phototype="?", phototype_label="Indeterminee", ita_deg=0.0,
            severity_level=0, severity_label="indetermine", gags_score=0.0,
            diagnosis="Visage non detecte",
            summary=("Aucun visage exploitable sur cette image. Cadrez le visage "
                     "de face, en lumiere naturelle, sans lunettes ni masque."),
            quality=asdict(fm.quality),
            flags=fm.quality.issues,
            elapsed_ms=int((time.time() - t0) * 1000),
        )

    ph = analyze_phenotype(fm)
    lr = detect_lesions(fm)
    fp = build_fingerprint(ph, lr, profile)
    routine = build_routine(fp, ph, profile)

    per_zone: Dict[str, dict] = {}
    for name, z in fm.zones.items():
        if not z.available:
            continue
        st = ph.zones.get(name)
        per_zone[name] = {
            "lesions": lr.per_zone.get(name, {}),
            "density_cm2": round(lr.density.get(name, 0.0), 3),
            "shine": round(st.shine, 3) if st else None,
            "redness": round(st.redness, 2) if st else None,
            "hair_ratio": round(z.hair_ratio, 3),
        }

    return FaceAnalysis(
        ok=True, engine=ENGINE_VERSION,
        global_score=fp.global_score, confidence=fp.confidence,
        skin_type=ph.skin_type, skin_type_confidence=ph.skin_type_confidence,
        phototype=ph.phototype, phototype_label=ph.phototype_label,
        ita_deg=round(ph.ita_deg, 1),
        severity_level=lr.severity_level, severity_label=lr.severity_label,
        gags_score=round(lr.gags_score, 1),
        diagnosis=_diagnosis(fp, ph, lr),
        summary=_summary(fp, ph, lr, fm),
        concerns={k: round(v, 3) for k, v in fp.vector.items()},
        top_concerns=fp.top_concerns,
        drivers=fp.drivers,
        lesion_counts=lr.counts,
        lesions=[asdict(l) for l in lr.lesions],
        per_zone=per_zone,
        zone_scores=_zone_scores(fp, lr, fm),
        hormonal_pattern=lr.hormonal_pattern,
        routine=routine.to_dict(),
        cautions=routine.cautions,
        quality=asdict(fm.quality),
        flags=fp.flags + ph.notes,
        elapsed_ms=int((time.time() - t0) * 1000),
    )


def analyze_multi(images: List[str], profile: Optional[dict] = None) -> FaceAnalysis:
    """Combine plusieurs angles (face, profil gauche, profil droit).

    Les vues laterales exposent des zones que la vue de face aplatit ou occulte.
    On garde la vue de face comme reference — c'est la seule ou la geometrie du
    maillage est fiable — et on complete son inventaire lesionnel par les zones
    que les profils voient mieux.
    """
    profile = profile or {}
    results = [analyze_face(im, profile) for im in images if im]
    usable = [r for r in results if r.ok]
    if not usable:
        return results[0] if results else analyze_face("", profile)

    # Vue la plus frontale = celle dont le lacet est le plus proche de zero
    def yaw_of(r: FaceAnalysis) -> float:
        return abs(float(r.quality.get("yaw_proxy", 1.0)))

    usable.sort(key=yaw_of)
    base = usable[0]

    if len(usable) == 1:
        return base

    # Fusion des comptages par zone : on retient, pour chaque zone, la vue qui
    # en a vu le plus (une lesion vue de profil existe meme si la vue de face
    # l'a manquee).
    merged_zone = dict(base.per_zone)
    for r in usable[1:]:
        for zone, data in r.per_zone.items():
            cur = merged_zone.get(zone)
            if cur is None or sum(data.get("lesions", {}).values()) > sum(
                    cur.get("lesions", {}).values()):
                merged_zone[zone] = data

    total_counts: Dict[str, int] = {}
    for zone, data in merged_zone.items():
        for t, n in (data.get("lesions") or {}).items():
            total_counts[t] = total_counts.get(t, 0) + n

    base.per_zone = merged_zone
    base.lesion_counts = total_counts or base.lesion_counts
    base.summary += f" Analyse consolidee sur {len(usable)} prises de vue."
    base.confidence = min(0.95, base.confidence + 0.06 * (len(usable) - 1))
    return base
