"""SKYN Expert System.

Deterministic decision tree + modular paragraph templates. No LLM.
Inputs: extracted metrics + user profile. Output: a clinical diagnosis label
and 3 personalised recommendation paragraphs in French.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ProfileCtx:
    age_range: Optional[str] = None       # "<25" | "25-40" | "40-60" | "60+"
    environment: Optional[str] = None     # "Urbain" | "Sec" | "Humide" | "Variable"
    priority: Optional[str] = None        # "Éclat" | "Ridules" | "Imperfections" | "Sensibilité"


# Diagnosis catalogue ----------------------------------------------------------
DIAGNOSES = {
    "dehydration_severe": "Déshydratation sévère",
    "oily_tzone": "Excès de sébum sur la zone T",
    "reactive_skin": "Peau réactive — micro-rougeurs diffuses",
    "uneven_radiance": "Manque d'uniformité du teint",
    "early_aging": "Premiers signes de relâchement",
    "imperfections_active": "Imperfections actives",
    "balanced": "Équilibre cutané préservé",
}


def diagnose(metrics: Dict[str, float], profile: ProfileCtx) -> str:
    """Strict, rule-based clinical reading of the metrics."""
    tx = int(metrics.get("texture", 80))
    rd = int(metrics.get("radiance", 80))
    im = int(metrics.get("imperfections", 80))
    redness = float(metrics.get("redness", 0.0))
    age = profile.age_range or "25-40"

    if im < 55 and tx < 65:
        return DIAGNOSES["imperfections_active"]
    if redness > 6.0 and tx < 80:
        return DIAGNOSES["reactive_skin"]
    if rd < 55 and tx < 70:
        return DIAGNOSES["dehydration_severe"]
    if rd > 80 and tx < 70 and age in ("<25", "25-40"):
        return DIAGNOSES["oily_tzone"]
    if age in ("40-60", "60+") and tx < 75:
        return DIAGNOSES["early_aging"]
    if rd < 70:
        return DIAGNOSES["uneven_radiance"]
    return DIAGNOSES["balanced"]


# Modular template recommendations ---------------------------------------------
# Each entry: (priority_score_key, condition_fn, template). The condition_fn
# decides whether the entry is eligible. The top 3 by deficit score are kept.

def _w(score: int) -> int:
    """Weight: lower score = higher weight (more important to address)."""
    return max(0, 100 - int(score))


def _format(tpl: str, **kwargs) -> str:
    return tpl.format(**{k: v for k, v in kwargs.items()})


def recommend(metrics: Dict[str, float], profile: ProfileCtx, diagnosis: str) -> List[str]:
    tx = int(metrics.get("texture", 80))
    rd = int(metrics.get("radiance", 80))
    im = int(metrics.get("imperfections", 80))
    redness = float(metrics.get("redness", 0.0))
    env = profile.environment or "Variable"
    age = profile.age_range or "25-40"

    # Library of templated recommendations, each with eligibility and priority
    candidates: List[tuple] = []

    # Hydration / dehydration
    if rd < 75 or "Déshydratation" in diagnosis:
        candidates.append((
            _w(rd) + 8,
            _format(
                "Renforcez la barrière hydrolipidique avec un sérum à l'acide hyaluronique appliqué matin et soir, suivi d'une crème occlusive pour sceller l'hydratation."
            ),
        ))

    # Radiance / vitamine C
    if rd < 80:
        urban = "et neutralise les agressions urbaines liées à la pollution" if env == "Urbain" else "et révèle la luminosité naturelle du teint"
        candidates.append((
            _w(rd),
            _format(
                "Introduisez un sérum à la vitamine C ({pct}%) le matin, qui ravive l'uniformité {urban}.",
                pct=10 if age in ("<25", "25-40") else 8,
                urban=urban,
            ),
        ))

    # Texture / exfoliation
    if tx < 75:
        molecule = "AHA glycolique 5%" if age in ("<25", "25-40") else "PHA gluconolactone"
        candidates.append((
            _w(tx) + 4,
            _format(
                "Affinez le grain de peau avec une exfoliation douce ({molecule}) deux soirs par semaine, à intégrer après le nettoyage et avant l'hydratant.",
                molecule=molecule,
            ),
        ))

    # Imperfections / niacinamide
    if im < 75:
        candidates.append((
            _w(im) + 6,
            "Régulez la production sébacée et apaisez les imperfections avec une sérum à la niacinamide 10% en couche unique le soir, sans superposition d'actifs irritants.",
        ))

    # Reactive skin / centella
    if redness > 5.0:
        candidates.append((
            int(redness * 6) + 20,
            "Calmez les micro-rougeurs avec une routine apaisante centrée sur la centella asiatica et le panthénol, en évitant les actifs exfoliants tant que les rougeurs persistent.",
        ))

    # Anti-aging / retinol
    if age in ("40-60", "60+") or tx < 65:
        candidates.append((
            _w(tx) + (20 if age == "60+" else 10),
            "Initiez un rétinol faible dosage (0,3%) deux soirs par semaine pour stimuler le renouvellement cellulaire, en commençant progressivement pour préserver la tolérance.",
        ))

    # SPF — always relevant
    candidates.append((
        16,
        "Maintenez une protection solaire SPF 50 quotidienne, geste fondamental contre le photovieillissement et la persistance des taches pigmentaires.",
    ))

    # Sleep / lifestyle if multiple low scores
    if rd < 65 and tx < 70:
        candidates.append((
            18,
            "Consolidez la régénération nocturne par un rituel de sommeil régulier (sept à huit heures) et une hydratation orale soutenue tout au long de la journée.",
        ))

    # Sort by priority weight desc, keep top 3, ensure unique
    seen = set()
    ordered = sorted(candidates, key=lambda x: x[0], reverse=True)
    recs: List[str] = []
    for _, txt in ordered:
        if txt in seen:
            continue
        seen.add(txt)
        recs.append(txt)
        if len(recs) == 3:
            break

    # Safety: always return 3 entries
    while len(recs) < 3:
        recs.append(
            "Maintenez une protection solaire SPF 50 quotidienne, geste fondamental contre le photovieillissement.",
        )
    return recs[:3]
