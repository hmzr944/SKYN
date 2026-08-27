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
    # La boite du visage dans l'image, en pixels, avec les dimensions de
    # l'image. Les coordonnees des lesions sont normalisees SUR CETTE BOITE :
    # sans elle, le client ne peut pas les replacer sur la photo, et il les
    # dessinait jusqu'ici sur l'image entiere — d'ou des reperes a cote du
    # visage, parfois hors du visage.
    face_box: Dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
CONCERN_FR = {
    "acne_active": "lésions inflammatoires actives",
    "comedons": "comédons",
    "post_acne_marks": "marques post-acné",
    "sebum": "production de sébum",
    "pores": "pores dilatés",
    "redness": "rougeurs diffuses",
    "sensitivity": "réactivité",
    "dehydration": "déshydratation",
    "dullness": "teint terne",
    "pigmentation": "irrégularités pigmentaires",
    "texture": "grain de peau irrégulier",
    "barrier_damage": "barrière cutanée altérée",
    "aging": "signes de vieillissement",
}

ZONE_FR = {
    "front": "le front", "glabelle": "l'entre-sourcils", "nez": "le nez",
    "joue_g": "la joue gauche", "joue_d": "la joue droite",
    "menton": "le menton", "machoire_g": "la mâchoire gauche",
    "machoire_d": "la mâchoire droite", "peri_oral": "le pourtour de la bouche",
    "tempe_g": "la tempe gauche", "tempe_d": "la tempe droite",
    "sous_yeux_g": "le dessous de l'œil gauche",
    "sous_yeux_d": "le dessous de l'œil droit",
}


# Les types de peau circulent en interne comme identifiants ASCII ; ils ne
# doivent jamais etre affiches tels quels a l'utilisateur.
SKIN_TYPE_FR = {
    "grasse": "grasse", "mixte": "mixte", "normale": "normale",
    "seche": "sèche", "indetermine": "indéterminée",
}


def _diagnosis(fp: SkinFingerprint, ph: Phenotype, lr: LesionReport) -> str:
    """Intitule clinique court, construit a partir des axes dominants.

    v1 choisissait parmi sept intitules figes, dont un seul revenait dans 48 %
    des cas. Ici l'intitule est compose : type de peau mesure + preoccupation
    dominante, ce qui multiplie mecaniquement les combinaisons.
    """
    if not fp.top_concerns:
        return f"Peau {SKIN_TYPE_FR.get(ph.skin_type, ph.skin_type)} équilibrée"

    first = fp.top_concerns[0]
    if first == "acne_active":
        label = {
            0: "sans lésion active", 1: "acné légère", 2: "acné modérée",
            3: "acné sévère", 4: "acné très sévère",
        }.get(lr.severity_level, "acné")
        base = f"Peau {SKIN_TYPE_FR.get(ph.skin_type, ph.skin_type)} — {label}"
        if lr.hormonal_pattern:
            base += ", répartition mandibulaire"
        return base

    return f"Peau {SKIN_TYPE_FR.get(ph.skin_type, ph.skin_type)} — {CONCERN_FR.get(first, first)}"


def _summary(fp: SkinFingerprint, ph: Phenotype, lr: LesionReport,
             fm: FaceMap) -> str:
    """Deux a trois phrases expliquant ce qui a ete mesure, et ou."""
    bits: List[str] = []

    tot = len(lr.lesions)
    if tot:
        infl = lr.counts.get("papule", 0) + lr.counts.get("pustule", 0)
        where = ", ".join(ZONE_FR.get(z, z) for z in lr.dominant_zones[:2])
        s = f"{tot} lésions repérées"
        if infl:
            s += f", dont {infl} inflammatoires"
        if where:
            s += f", concentrées sur {where}"
        bits.append(s + ".")
    else:
        bits.append("Aucune lésion active repérée sur les zones analysées.")

    if ph.skin_type == "mixte":
        bits.append(
            f"La zone T brille nettement plus que les joues "
            f"(écart {ph.shine_delta:+.2f}), signature d'une peau mixte."
        )
    elif ph.skin_type == "grasse":
        bits.append("Brillance homogène sur l'ensemble du visage, y compris les joues.")
    elif ph.skin_type == "seche":
        bits.append("Peu de réflexion spéculaire et grain marqué : peau sèche.")

    second = [c for c in fp.top_concerns[1:3]]
    if second:
        bits.append(
            "Autres points relevés : "
            + ", ".join(CONCERN_FR.get(c, c) for c in second) + "."
        )

    if fm.quality.issues:
        bits.append(
            "Qualité de prise de vue perfectible ("
            + ", ".join(i.replace("_", " ") for i in fm.quality.issues)
            + ") : le résultat gagnerait à être confirmé par un nouveau scan."
        )
    return " ".join(bits)


def _zone_burden(density: float, infl: int) -> float:
    """Charge d'une zone, sur 0..1.

    Isolee pour que le score d'une seule prise et celui d'une fusion
    multi-angles passent par le MEME calcul : deux formules qui divergent,
    meme legerement, feraient dependre la carte affichee du nombre de photos
    envoyees plutot que de l'etat de la peau.
    """
    return min(1.0, density / 3.0) * 0.6 + min(1.0, infl / 6.0) * 0.4


def _zone_scores(fp: SkinFingerprint, lr: LesionReport, fm: FaceMap) -> Dict[str, int]:
    """Note 0-100 par zone, pour la cartographie affichee dans l'application."""
    out: Dict[str, int] = {}
    for name, z in fm.zones.items():
        if not z.available:
            continue
        d = lr.density.get(name, 0.0)
        per = lr.per_zone.get(name, {})
        infl = per.get("papule", 0) + per.get("pustule", 0)
        out[name] = int(round(100 * (1.0 - _zone_burden(d, infl))))
    return out


def _zone_scores_from_merged(per_zone: Dict[str, dict]) -> Dict[str, int]:
    """La meme note, a partir d'un `per_zone` deja fusionne entre plusieurs angles.

    `analyze_multi` fusionne les comptages par zone de chaque prise, mais
    renvoyait jusqu'ici le `zone_scores` de la SEULE vue de face — celle prise
    comme reference. Sur un scan reel a trois angles, la vue de face n'avait
    reussi a cartographier qu'une zone (le front) ; la carte affichee etait
    donc vide partout ailleurs, et sa legende presentait cette zone unique
    comme « la plus chargee » alors qu'elle etait simplement la seule mesuree.

    Le `per_zone` fusionne porte deja `density_cm2` et les comptages par type
    pour chaque zone vue par au moins une des trois prises — y compris les
    tempes et la machoire, que les profils exposent et que la vue de face
    aplatit. Il suffit d'y repasser la meme formule.
    """
    out: Dict[str, int] = {}
    for name, data in per_zone.items():
        d = data.get("density_cm2", 0.0)
        lesions = data.get("lesions") or {}
        infl = lesions.get("papule", 0) + lesions.get("pustule", 0)
        out[name] = int(round(100 * (1.0 - _zone_burden(d, infl))))
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
            diagnosis="Visage non détecté",
            summary=("Aucun visage exploitable sur cette image. Cadrez le visage "
                     "de face, en lumière naturelle, sans lunettes ni masque."),
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
        face_box=_face_box(fm),
        elapsed_ms=int((time.time() - t0) * 1000),
    )


def _face_box(fm) -> Dict[str, int]:
    """La boite du visage et la taille de l'image, en pixels."""
    bx, by, bw, bh = fm.bbox
    h, w = fm.rgb.shape[:2]
    return {"x": int(bx), "y": int(by), "w": int(bw), "h": int(bh),
            "image_w": int(w), "image_h": int(h)}


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
    base.zone_scores = _zone_scores_from_merged(merged_zone)
    base.lesion_counts = total_counts or base.lesion_counts
    base.summary += f" Analyse consolidée sur {len(usable)} prises de vue."
    base.confidence = min(0.95, base.confidence + 0.06 * (len(usable) - 1))
    return base
