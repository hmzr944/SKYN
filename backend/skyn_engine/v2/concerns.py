"""SKYN Engine v2 — Etape 4 : empreinte cutanee.

v1 resumait une peau a trois nombres : texture, eclat, imperfections. Trois
nombres, chacun ecrase dans une plage de 30 a 98 et fortement correles entre
eux, ne peuvent pas differencier des millions d'utilisateurs. La simulation sur
20 000 profils le confirme : 48 % recevaient le meme diagnostic, et 80 % un
score global compris entre 61 et 79.

On construit ici un VECTEUR de treize axes independants, chacun mesure sur une
grandeur physique distincte, puis module par le profil declare. Deux personnes
ayant le meme score global peuvent avoir des vecteurs tres differents — et
recevoir des produits differents. C'est le point exact ou la personnalisation
se joue.

Les cles de ce vecteur sont le vocabulaire commun avec le catalogue produits :
chaque produit declare ce qu'il traite avec les memes intitules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .lesions import LesionReport
from .phenotype import Phenotype

CONCERN_KEYS = (
    "acne_active",      # lesions inflammatoires en cours
    "comedons",         # comedons ouverts et fermes
    "post_acne_marks",  # marques rouges ou brunes laissees par l'acne
    "sebum",            # production sebacee
    "pores",            # dilatation des pores
    "redness",          # rougeurs diffuses
    "sensitivity",      # reactivite cutanee
    "dehydration",      # manque d'eau, desquamation
    "dullness",         # teint terne
    "pigmentation",     # heterogeneite pigmentaire
    "texture",          # grain de peau irregulier
    "barrier_damage",   # barriere cutanee alteree
    "aging",            # signes de vieillissement
)


@dataclass
class SkinFingerprint:
    """Vecteur de preoccupations, chaque axe dans 0..1 (1 = tres marque)."""
    vector: Dict[str, float]
    top_concerns: List[str]
    global_score: int
    confidence: float
    drivers: Dict[str, str] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)

    def get(self, key: str) -> float:
        return float(self.vector.get(key, 0.0))


def _sat(v: float) -> float:
    return float(max(0.0, min(1.0, v)))


def _density_sum(lr: LesionReport, types) -> float:
    """Densite lesionnelle globale, en lesions par cm2, pour certains types."""
    total = 0.0
    for zone, per_type in lr.per_zone.items():
        n = sum(per_type.get(t, 0) for t in types)
        if n and zone in lr.density:
            share = n / max(1, sum(per_type.values()))
            total += lr.density[zone] * share
    return total


def build_fingerprint(ph: Phenotype, lr: LesionReport,
                      profile: Optional[dict] = None) -> SkinFingerprint:
    profile = profile or {}
    v: Dict[str, float] = {k: 0.0 for k in CONCERN_KEYS}
    drivers: Dict[str, str] = {}
    flags: List[str] = []

    # --- Axes mesures ------------------------------------------------------
    infl_density = _density_sum(lr, ("papule", "pustule"))
    com_density = _density_sum(lr, ("comedon",))
    mark_density = _density_sum(lr, ("marque_rouge", "marque_brune"))

    # La severite GAGS porte l'essentiel du signal, la densite affine
    v["acne_active"] = _sat(lr.severity_level / 4.0 * 0.7 + infl_density / 3.0 * 0.3)
    v["comedons"] = _sat(com_density / 2.5)
    v["post_acne_marks"] = _sat(mark_density / 2.0)
    v["sebum"] = _sat(0.65 * ph.sebum_t + 0.35 * ph.sebum_u)
    v["pores"] = _sat(ph.pore_load)
    v["redness"] = _sat(ph.redness_global)
    v["sensitivity"] = _sat((0.6 if ph.sensitive else 0.0) + 0.4 * ph.redness_global)
    v["dehydration"] = _sat(ph.dryness)
    v["texture"] = _sat(0.6 * ph.pore_load + 0.4 * ph.unevenness)
    v["pigmentation"] = _sat(0.55 * ph.unevenness + 0.45 * _sat(mark_density / 2.0))
    v["dullness"] = _sat(0.7 * ph.unevenness + 0.3 * (1.0 - ph.sebum_t))

    # Barriere alteree : rougeur ET secheresse simultanees. Le produit des deux
    # evite de la declencher sur une peau seche mais calme, ou grasse et rouge.
    v["barrier_damage"] = _sat(1.6 * ph.redness_global * ph.dryness
                               + (0.25 if ph.sensitive else 0.0))

    if v["acne_active"] > 0:
        drivers["acne_active"] = (
            f"{lr.counts['papule']} papules et {lr.counts['pustule']} pustules "
            f"repérées, sévérité {lr.severity_label.replace('_', ' ')}"
        )
    if v["sebum"] > 0.4:
        drivers["sebum"] = (
            f"zone T nettement plus brillante que les joues "
            f"(écart {ph.shine_delta:+.2f})"
        )
    if v["post_acne_marks"] > 0.2:
        drivers["post_acne_marks"] = (
            f"{lr.counts['marque_rouge']} marques rouges et "
            f"{lr.counts['marque_brune']} marques brunes"
        )

    # --- Vieillissement : non mesure optiquement pour l'instant -------------
    # On ne detecte pas encore les rides. Plutot que d'inventer une mesure, on
    # derive cet axe de l'age declare et de l'irregularite du grain, et on le
    # signale comme estime.
    age = str(profile.get("age_range") or "")
    age_base = {"<25": 0.05, "25-40": 0.25, "40-60": 0.55, "60+": 0.75}.get(age, 0.2)
    v["aging"] = _sat(age_base * 0.75 + ph.unevenness * 0.25)
    flags.append("aging_estime_non_mesure")

    # --- Modulation par le phototype ---------------------------------------
    # Une peau foncee reagit a l'inflammation par une hyperpigmentation post-
    # inflammatoire durable, la ou une peau claire garde une marque rouge qui
    # s'estompe seule. A lesions egales, l'enjeu "marques" n'est pas le meme.
    if ph.phototype in ("IV", "V", "VI") and v["acne_active"] > 0.2:
        v["post_acne_marks"] = _sat(v["post_acne_marks"] + 0.18)
        v["pigmentation"] = _sat(v["pigmentation"] + 0.15)
        flags.append("risque_hyperpigmentation_post_inflammatoire")
    if ph.phototype in ("I", "II") and v["acne_active"] > 0.2:
        v["redness"] = _sat(v["redness"] + 0.10)

    # --- Modulation par le profil declare ----------------------------------
    # v1 acceptait une priorite utilisateur puis ne s'en servait que pour
    # retrancher 4 points a un score. Ici elle deplace reellement le vecteur.
    priority = str(profile.get("priority") or "").lower()
    PRIORITY_MAP = {
        "imperfection": ("acne_active", "comedons", "post_acne_marks"),
        "eclat": ("dullness", "pigmentation"),
        "éclat": ("dullness", "pigmentation"),
        "ridule": ("aging", "texture"),
        "sensib": ("sensitivity", "redness", "barrier_damage"),
        "pore": ("pores", "sebum"),
        "marque": ("post_acne_marks", "pigmentation"),
        "brillance": ("sebum", "pores"),
    }
    for key, targets in PRIORITY_MAP.items():
        if key in priority:
            for t in targets:
                v[t] = _sat(v[t] + 0.15)
            drivers["priorite"] = f"priorité déclarée : {priority}"
            break

    env = str(profile.get("environment") or "").lower()
    if "urbain" in env:
        v["dullness"] = _sat(v["dullness"] + 0.08)
        v["pigmentation"] = _sat(v["pigmentation"] + 0.05)
    if "sec" in env:
        v["dehydration"] = _sat(v["dehydration"] + 0.12)
        v["barrier_damage"] = _sat(v["barrier_damage"] + 0.06)
    if "humide" in env:
        v["sebum"] = _sat(v["sebum"] + 0.06)

    if profile.get("pregnant"):
        flags.append("grossesse")
    if profile.get("on_isotretinoin"):
        flags.append("isotretinoine")
        v["dehydration"] = _sat(v["dehydration"] + 0.3)
        v["barrier_damage"] = _sat(v["barrier_damage"] + 0.3)

    # --- Score global ------------------------------------------------------
    # Moyenne ponderee des axes, transformee en score "sante cutanee" 0..100.
    # Contrairement a v1 on n'ecrase PAS dans 30..98 : la bande complete est
    # utilisee, sinon tout le monde se retrouve autour de 70.
    WEIGHTS = {
        "acne_active": 2.4, "comedons": 1.1, "post_acne_marks": 1.2,
        "sebum": 0.7, "pores": 0.7, "redness": 1.0, "sensitivity": 0.9,
        "dehydration": 1.0, "dullness": 0.8, "pigmentation": 0.9,
        "texture": 0.9, "barrier_damage": 1.3, "aging": 0.6,
    }
    num = sum(v[k] * w for k, w in WEIGHTS.items())
    den = sum(WEIGHTS.values())
    burden = num / den
    global_score = int(round(100.0 * (1.0 - burden) ** 1.15))
    global_score = max(1, min(100, global_score))

    top = sorted(
        (k for k in CONCERN_KEYS if v[k] > 0.15),
        key=lambda k: -(v[k] * WEIGHTS.get(k, 1.0)),
    )[:4]

    # --- Confiance ---------------------------------------------------------
    conf = 0.85
    if not ph.zones:
        conf -= 0.4
    if ph.notes:
        conf -= 0.1 * len(ph.notes)
    conf = float(max(0.2, min(0.95, conf)))

    return SkinFingerprint(vector=v, top_concerns=top, global_score=global_score,
                           confidence=conf, drivers=drivers, flags=flags)
