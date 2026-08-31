"""SKYN — Persistent Skin Memory (chantier 4).

Couche produit/persistance pour la boucle validee au chantier 2/3 :

    Scan --> Period --> SkinChange (calcule, jamais stocke)

Ce module NE TOUCHE PAS au moteur de vision (`skyn_engine/`). Il consomme
la sortie deja produite par `/api/analyze/v2` ou `/api/analyze/guided`
(le client l'envoie telle quelle) et decide seulement : a quelle Period ce
scan appartient, quel etat de Phase en resulte, et quels changements sont
mesurables avec une confiance suffisante.

Regle qui gouverne tout ce fichier, heritee du chantier moteur : jamais de
fausse precision. `capture_quality` et `confidence` sont des paliers
discrets (low/medium/high), jamais un pourcentage — un scan ou une
tendance ne sont jamais "surs a 87 %".
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from skyn_engine.v2.multiview import ScanConfig

# Sources de scan acceptees dans la memoire persistante. Le v1 (/api/analyze)
# n'a ni per_zone ni concerns ni vote-gate : rien d'assez riche pour comparer
# dans le temps, donc volontairement hors modele plutot que mal modelise.
VALID_SOURCES = ("v2", "guided")

STRUCTURAL_ROUTINE_EVENT_TYPES = {"step_added", "step_removed", "step_changed"}

# Zone neutre autour de zero en dessous de laquelle un delta de concern
# (echelle 0..1) est affiche comme "stable" plutot que comme un mouvement —
# le bruit de mesure normal ne doit jamais se lire comme une tendance.
CONCERN_EPSILON = 0.03

UNDERSTANDING_MIN_SCANS = 3
UNDERSTANDING_MIN_SPAN_DAYS = 14

_GUIDED_DEFAULTS = ScanConfig()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============ Modeles stockes ============

class ScanRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    period_id: str
    created_at: datetime = Field(default_factory=_now)
    source: str                                    # "v2" | "guided"
    is_baseline: bool = False
    global_score: Optional[int] = None
    concerns: Dict[str, float] = Field(default_factory=dict)
    zone_scores: Dict[str, int] = Field(default_factory=dict)
    lesion_counts: Dict[str, int] = Field(default_factory=dict)
    lesions: List[dict] = Field(default_factory=list)
    capture_quality: str = "low"                   # "low" | "medium" | "high"


class Period(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    starts_at: datetime = Field(default_factory=_now)
    ends_at: Optional[datetime] = None
    opened_by: str                                  # "baseline" | RoutineEvent.id
    baseline_scan_id: str
    latest_scan_id: str


class RoutineEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    period_id: str
    at: datetime = Field(default_factory=_now)
    type: str                                       # created|step_added|step_removed|step_changed
    diff: Dict[str, List[str]] = Field(default_factory=dict)


class ProductEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    period_id: str
    at: datetime = Field(default_factory=_now)
    type: str                                       # "introduced" | "stopped"
    product_id: str
    moment: str                                      # "am" | "pm"


# ============ Requetes API ============

class ScanIngestRequest(BaseModel):
    source: str
    analysis: Dict[str, Any]


class RoutineEventRequest(BaseModel):
    type: str
    diff: Dict[str, List[str]] = Field(default_factory=dict)


class ProductEventRequest(BaseModel):
    type: str
    product_id: str
    moment: str


class SkinChangeItem(BaseModel):
    metric: str
    kind: str                                        # "concern" | "zone"
    baseline_value: float
    latest_value: float
    direction: str                                    # "up" | "down" | "stable"
    confidence: str                                    # "low" | "medium" | "high"
    attribution: Optional[List[str]] = None


# ============ Qualite de capture ============

def compute_capture_quality(source: str, analysis: Dict[str, Any]) -> str:
    """A quel point CETTE capture est exploitable pour comparer la peau
    dans le temps — jamais un score de confiance du moteur."""
    if source == "v2":
        quality = analysis.get("quality") or {}
        if not quality.get("usable", True):
            return "low"
        return "medium" if quality.get("issues") else "high"

    if source == "guided":
        status = analysis.get("status")
        usable_views = analysis.get("usable_views", 0) or 0
        if usable_views < _GUIDED_DEFAULTS.min_vues_utiles:
            return "low"
        if status == "TARGET_REACHED":
            return "high"
        return "medium"

    return "low"


def _extract_scan_fields(source: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    if source == "v2":
        return {
            "global_score": analysis.get("global_score"),
            "concerns": analysis.get("concerns") or {},
            "zone_scores": analysis.get("zone_scores") or {},
            "lesion_counts": analysis.get("lesion_counts") or {},
            "lesions": analysis.get("lesions") or [],
        }
    # source == "guided" — pas de per_zone/concerns cote moteur multi-vue
    # aujourd'hui (voir server.py, endpoint /api/analyze/guided) : seules les
    # lesions confirmees et leurs comptes par type sont disponibles.
    lesions = analysis.get("lesions") or []
    counts: Dict[str, int] = {}
    for lesion in lesions:
        t = lesion.get("type") or "inconnu"
        counts[t] = counts.get(t, 0) + 1
    return {
        "global_score": None,
        "concerns": {},
        "zone_scores": {},
        "lesion_counts": counts,
        "lesions": lesions,
    }


# ============ Acces periode active ============

async def _get_active_period(db, user_id: str) -> Optional[dict]:
    return await db.periods.find_one(
        {"user_id": user_id, "ends_at": None}, {"_id": 0}, sort=[("starts_at", -1)]
    )


# ============ Ingestion d'un scan ============

async def ingest_scan(db, user_id: str, source: str, analysis: Dict[str, Any]) -> ScanRecord:
    if source not in VALID_SOURCES:
        raise ValueError(f"unsupported scan source: {source!r}")

    fields = _extract_scan_fields(source, analysis)
    capture_quality = compute_capture_quality(source, analysis)
    active = await _get_active_period(db, user_id)

    scan = ScanRecord(
        user_id=user_id,
        period_id="",
        source=source,
        capture_quality=capture_quality,
        **fields,
    )

    if active is None:
        scan.is_baseline = True
        period = Period(
            user_id=user_id,
            opened_by="baseline",
            baseline_scan_id=scan.id,
            latest_scan_id=scan.id,
        )
        scan.period_id = period.id
        await db.periods.insert_one(period.model_dump())
    else:
        scan.period_id = active["id"]
        await db.periods.update_one(
            {"id": active["id"]}, {"$set": {"latest_scan_id": scan.id}}
        )

    await db.scans.insert_one(scan.model_dump())
    return scan


# ============ Evenements routine / produit ============

async def log_routine_event(
    db, user_id: str, type_: str, diff: Optional[Dict[str, List[str]]] = None
) -> RoutineEvent:
    active = await _get_active_period(db, user_id)
    if active is None:
        raise ValueError("no active period — user must complete a first scan first")

    if type_ in STRUCTURAL_ROUTINE_EVENT_TYPES:
        # Un changement structurant de routine cloture la Phase en cours et
        # en ouvre une nouvelle, ancree sur le dernier scan connu — c'est ce
        # qui garantit, par construction, qu'une Phase ne peut jamais
        # chevaucher deux changements de routine a la fois (voir la regle
        # d'attribution dans _skin_changes).
        now = _now()
        await db.periods.update_one({"id": active["id"]}, {"$set": {"ends_at": now}})
        event = RoutineEvent(
            user_id=user_id, period_id="", type=type_, diff=diff or {}, at=now
        )
        new_period = Period(
            user_id=user_id,
            opened_by=event.id,
            baseline_scan_id=active["latest_scan_id"],
            latest_scan_id=active["latest_scan_id"],
            starts_at=now,
        )
        event.period_id = new_period.id
        await db.periods.insert_one(new_period.model_dump())
        await db.routine_events.insert_one(event.model_dump())
        return event

    event = RoutineEvent(user_id=user_id, period_id=active["id"], type=type_, diff=diff or {})
    await db.routine_events.insert_one(event.model_dump())
    return event


async def log_product_event(
    db, user_id: str, type_: str, product_id: str, moment: str
) -> ProductEvent:
    active = await _get_active_period(db, user_id)
    if active is None:
        raise ValueError("no active period — user must complete a first scan first")
    # Si ce produit accompagne un changement structurant de routine, logger
    # d'abord le RoutineEvent (l'appelant s'en charge) : ainsi la Phase
    # active a ce moment est deja la nouvelle, et ce ProductEvent s'y
    # rattache — c'est ce qui rend l'attribution possible plus tard.
    event = ProductEvent(
        user_id=user_id, period_id=active["id"], type=type_, product_id=product_id, moment=moment
    )
    await db.product_events.insert_one(event.model_dump())
    return event


# ============ Etat de phase + changements ============

def _phase_state(scans: List[dict]) -> str:
    n = len(scans)
    if n <= 1:
        return "baseline"
    if n == 2:
        return "tracking"
    if _span_days(scans) >= UNDERSTANDING_MIN_SPAN_DAYS and all(
        s.get("capture_quality") != "low" for s in scans
    ):
        return "understanding"
    return "tracking"


def _span_days(scans: List[dict]) -> float:
    if len(scans) < 2:
        return 0.0
    first, last = scans[0]["created_at"], scans[-1]["created_at"]
    if isinstance(first, str):
        first = datetime.fromisoformat(first)
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    return (last - first).total_seconds() / 86400.0


def _confidence_for_series(values: List[float], scans: List[dict], epsilon: float) -> str:
    if len(values) < 2:
        return "low"
    quality_ok = all(s.get("capture_quality") != "low" for s in scans)
    signs = []
    for a, b in zip(values, values[1:]):
        delta = b - a
        if abs(delta) >= epsilon:
            signs.append(1 if delta > 0 else -1)
    consistent = len(set(signs)) <= 1
    if len(values) >= UNDERSTANDING_MIN_SCANS and quality_ok and consistent and (
        _span_days(scans) >= UNDERSTANDING_MIN_SPAN_DAYS
    ):
        return "high"
    if quality_ok and consistent:
        return "medium"
    return "low"


def _direction(delta: float, epsilon: float) -> str:
    if abs(delta) < epsilon:
        return "stable"
    return "up" if delta > 0 else "down"


# (kind, field storing the metric, epsilon below which a delta reads as
# "stable", sparse). lesion_counts est un compte entier (0..N) : le scan
# multi-vue guide (source="guided") ne produit ni concerns ni zone_scores
# (voir _extract_scan_fields) — sans ce troisieme champ, une Phase
# construite uniquement a partir de scans guides n'aurait jamais rien a
# montrer sur What Changed?, meme apres plusieurs vraies observations.
#
# `sparse` distingue deux semantiques d'absence : un concern/zone absent
# d'un scan signifie "non mesure cette fois" (on ne devine pas — on saute) ;
# un type de lesion absent de `lesion_counts` signifie "zero occurrence"
# (une valeur reelle, pas un trou) — le traiter comme un simple "non
# mesure" ferait disparaitre le cas le plus important : un type de lesion
# qui s'efface completement entre deux scans.
_METRIC_FIELDS = (
    ("concern", "concerns", CONCERN_EPSILON, False),
    ("zone", "zone_scores", CONCERN_EPSILON, False),
    ("lesion_type", "lesion_counts", 0.5, True),
)


def _skin_changes(
    scans: List[dict], product_events: List[dict]
) -> List[SkinChangeItem]:
    if len(scans) < 2:
        return []

    baseline, latest = scans[0], scans[-1]
    introduced = [pe["product_id"] for pe in product_events if pe["type"] == "introduced"]

    items: List[SkinChangeItem] = []
    for kind, field_name, epsilon, sparse in _METRIC_FIELDS:
        if sparse:
            # Union : un type absent d'un scan vaut 0, pas "non mesure".
            keys = set(baseline.get(field_name) or {}) | set(latest.get(field_name) or {})
        else:
            keys = set(baseline.get(field_name) or {}) & set(latest.get(field_name) or {})
        for key in sorted(keys):
            values = []
            for s in scans:
                v = (s.get(field_name) or {}).get(key)
                if v is None and sparse:
                    v = 0
                if v is not None:
                    values.append(float(v))
            if len(values) < 2:
                continue
            delta = values[-1] - values[0]
            confidence = _confidence_for_series(values, scans, epsilon)
            attribution = introduced if confidence in ("medium", "high") and introduced else None
            items.append(
                SkinChangeItem(
                    metric=key,
                    kind=kind,
                    baseline_value=values[0],
                    latest_value=values[-1],
                    direction=_direction(delta, epsilon),
                    confidence=confidence,
                    attribution=attribution,
                )
            )
    return items


async def get_active_period_view(db, user_id: str) -> Optional[dict]:
    """Tout ce dont le frontend a besoin pour afficher la Phase active :
    son etat, ses scans, sa routine, et les changements deja calculables —
    rien de stocke au-dela de Scan/Period/RoutineEvent/ProductEvent."""
    active = await _get_active_period(db, user_id)
    if active is None:
        return None

    scans = await db.scans.find(
        {"period_id": active["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(length=1000)
    routine_events = await db.routine_events.find(
        {"period_id": active["id"]}, {"_id": 0}
    ).sort("at", 1).to_list(length=1000)
    product_events = await db.product_events.find(
        {"period_id": active["id"]}, {"_id": 0}
    ).sort("at", 1).to_list(length=1000)

    state = _phase_state(scans)
    changes = _skin_changes(scans, product_events) if state != "baseline" else []

    return {
        "period": active,
        "state": state,
        "scans": scans,
        "routine_events": routine_events,
        "product_events": product_events,
        "changes": [c.model_dump() for c in changes],
    }


async def list_periods(db, user_id: str, limit: int = 50) -> List[dict]:
    periods = await db.periods.find({"user_id": user_id}, {"_id": 0}).to_list(length=1000)
    # Tri en Python plutot que via le curseur : deux Periods peuvent partager
    # le meme starts_at a la microseconde pres (rollover immediat apres un
    # scan), et la seule chose garantie est qu'il existe au plus UNE Period
    # active — elle doit toujours arriver en tete, jamais dependre d'un
    # ordre de tri instable sur une egalite de timestamp.
    def _ts(p: dict) -> float:
        v = p["starts_at"]
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        return v.timestamp()

    periods.sort(key=lambda p: (p["ends_at"] is not None, -_ts(p)))
    return periods[:limit]
