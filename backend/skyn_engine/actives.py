"""Familles d'actifs, incompatibilités et charge irritante.

Pourquoi ce module existe
-------------------------
`recommend_products()` choisissait le meilleur produit de CHAQUE étape
indépendamment, sans jamais regarder ce qui avait déjà été retenu aux autres
étapes. Résultat mesuré sur 4 000 profils simulés :

  * 22,3 % des routines empilaient deux actifs forts de la même famille ;
  * 17,6 % associaient deux rétinoïdes — la routine la plus fréquente donnait
    un sérum Rétinol 0,3 % ET un traitement Rétinol 1 % forte dose le même
    jour, soit 1,3 % de rétinol cumulé.

Ce n'est pas un défaut de scoring : rien dans le catalogue ne décrit
l'incompatibilité entre deux produits, donc rien ne pouvait l'empêcher. Les
champs existants (`avoid_if_reactive`, `min_age`) protègent le produit pris
isolément, jamais la combinaison.

Approche retenue
----------------
Plutôt que d'ajouter deux champs à la main sur 101 produits — fastidieux et
vite désynchronisé — on dérive la famille et le potentiel irritant depuis les
`key_ingredients` déjà déclarés, avec une table de correction pour les cas que
le texte ne permet pas de trancher.

Limite assumée : la dérivation lit du texte libre. Un libellé mal orthographié
ou un actif nouveau passera dans la famille `None`. `audit_catalog()` liste les
produits non classés pour que l'écart se voie plutôt que de se deviner.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Familles
# --------------------------------------------------------------------------
# Familles dont l'empilement provoque réellement une irritation cumulative.
# Doubler un rétinoïde ou un exfoliant expose à la brûlure ; doubler de la
# niacinamide ou des céramides, non.
POTENT = frozenset({"retinoide", "bha", "aha", "peroxyde_benzoyle",
                    "azelaique", "vitamine_c"})

# Motifs cherchés dans les ingrédients déclarés (texte accentué ou non).
_PATTERNS: List[Tuple[str, str]] = [
    ("retinoide", r"retino(l|ide|ique)|retinal|retinaldehyde|adapalene|tretinoine|trifarotene"),
    ("peroxyde_benzoyle", r"peroxyde de benzoyle|benzoyl"),
    ("azelaique", r"azelaique|azelaic"),
    ("bha", r"salicyl|\bbha\b|\blha\b|capryloyl salicyl|betaine salicylate"),
    ("aha", r"glycolique|lactique|mandelique|\baha\b|acide citrique"),
    ("pha", r"gluconique|gluconolactone|lactobionique"),
    ("vitamine_c", r"vitamine c|ascorb|acide l-ascorbique"),
    ("niacinamide", r"niacinamide|vitamine b3"),
    ("zinc", r"\bzinc\b|zinc pca|zinc pidolate|gluconate de zinc"),
    ("soufre", r"soufre|sulfur"),
    ("ceramide", r"ceramide"),
    ("hyaluronique", r"hyaluron"),
    ("apaisant", r"madecassoside|centella|panthenol|allantoine|bisabolol|"
                 r"eau thermale|avoine|sucralfate|neurosensine|d-sensinose|"
                 r"beurre de karite|aloe"),
    ("spf", r"\bspf\b|filtres?|mexoryl|tinosorb|uvmune|photoderm"),
    ("depigmentant", r"arbutine|acide tranexamique|acide kojique|thiamidol"),
    ("peptide", r"peptide|matrixyl"),
]

# Corrections ponctuelles : noms commerciaux dont l'ingrédient réel n'est pas
# devinable depuis le libellé.
_ID_OVERRIDES: Dict[str, Set[str]] = {
    # « Sebulyse » et « Comedoclastin » sont des noms de marque : ce sont des
    # régulateurs séborégulateurs doux, pas des exfoliants chimiques.
    # Rien à forcer ici pour l'instant ; la table reste le point d'entrée
    # quand un cas se présente.
}


def _norm(s: str) -> str:
    """Minuscules sans accents, pour que 'Azélaïque' et 'azelaique' matchent."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def families(product: dict) -> Set[str]:
    """Familles d'actifs présentes dans un produit."""
    pid = product.get("id", "")
    if pid in _ID_OVERRIDES:
        return set(_ID_OVERRIDES[pid])

    blob = " ".join(_norm(x) for x in (product.get("key_ingredients") or []))
    blob += " " + _norm(product.get("name", ""))

    found: Set[str] = set()
    for fam, pattern in _PATTERNS:
        if re.search(pattern, blob):
            found.add(fam)
    return found


def potent_families(product: dict) -> Set[str]:
    return families(product) & POTENT


# --------------------------------------------------------------------------
# Concentration et potentiel irritant
# --------------------------------------------------------------------------
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

# Potentiel irritant de base par famille, pour un dosage courant.
_BASE_IRRITATION = {
    "retinoide": 0.60,
    "peroxyde_benzoyle": 0.70,
    "aha": 0.45,
    "bha": 0.35,
    "azelaique": 0.30,
    "vitamine_c": 0.30,
    "pha": 0.15,
    "soufre": 0.25,
    "depigmentant": 0.20,
    "niacinamide": 0.10,
    "zinc": 0.08,
    "peptide": 0.05,
    "ceramide": 0.03,
    "hyaluronique": 0.03,
    "apaisant": 0.02,
    "spf": 0.05,
}


def _max_pct(product: dict) -> Optional[float]:
    """Plus forte concentration annoncée, quand elle est déclarée."""
    vals: List[float] = []
    for ing in product.get("key_ingredients") or []:
        for m in _PCT.finditer(str(ing)):
            try:
                vals.append(float(m.group(1).replace(",", ".")))
            except ValueError:
                continue
    # Un « 89 % » d'eau volcanique n'est pas une concentration d'actif :
    # au-delà de 30 % on parle d'un excipient, pas d'un principe actif.
    vals = [v for v in vals if v <= 30.0]
    return max(vals) if vals else None


def irritation(product: dict) -> float:
    """Potentiel irritant estimé, 0..1.

    Un nettoyant est rincé après quelques secondes : sa charge est fortement
    minorée par rapport au même actif laissé en place toute la nuit.
    """
    fams = families(product)
    if not fams:
        return 0.05

    base = max((_BASE_IRRITATION.get(f, 0.05) for f in fams), default=0.05)

    pct = _max_pct(product)
    if pct is not None:
        if "retinoide" in fams:
            # 0,3 % est un dosage d'initiation ; 1 % est une forte dose.
            base += 0.22 if pct >= 1.0 else (0.08 if pct >= 0.5 else 0.0)
        elif "peroxyde_benzoyle" in fams:
            base += 0.15 if pct >= 5.0 else 0.0
        elif "aha" in fams:
            base += 0.12 if pct >= 8.0 else 0.0
        elif "bha" in fams:
            base += 0.08 if pct >= 2.0 else 0.0

    # Encapsulation et formes retard : tolérance nettement meilleure.
    blob = _norm(" ".join(product.get("key_ingredients") or []) + " " + product.get("name", ""))
    if "encapsul" in blob or "retard" in blob or "\bdoux\b" in blob:
        base -= 0.15

    if product.get("step") == "nettoyant":
        base *= 0.40

    return float(max(0.02, min(1.0, base)))


# --------------------------------------------------------------------------
# Incompatibilités
# --------------------------------------------------------------------------
# Paires à proscrire dans une même routine, au-delà de la règle « pas deux fois
# la même famille forte ».
_INCOMPATIBLE_PAIRS = frozenset({
    frozenset({"retinoide", "peroxyde_benzoyle"}),   # dégradation + irritation
    frozenset({"retinoide", "aha"}),                 # irritation cumulative
    frozenset({"retinoide", "bha"}),
    frozenset({"vitamine_c", "peroxyde_benzoyle"}),  # oxydation de la vitamine C
    frozenset({"aha", "peroxyde_benzoyle"}),
})


def _moments_overlap(a: dict, b: dict) -> bool:
    """Les deux produits s'appliquent-ils au même moment de la journée ?

    Un BHA le matin et un rétinoïde le soir est une association courante et
    bien tolérée : ce qui brûle, c'est de les superposer sur la même peau au
    même moment. Interdire la combinaison en toutes circonstances priverait
    l'utilisateur d'une routine parfaitement valable.
    """
    ma = a.get("moment", "matin_soir")
    mb = b.get("moment", "matin_soir")
    if "matin_soir" in (ma, mb):
        return True
    return ma == mb


def conflicts(product: dict, chosen: Iterable[dict]) -> Optional[str]:
    """Motif d'incompatibilité avec les produits déjà retenus, sinon None."""
    fams = families(product)
    pot = fams & POTENT
    rinse_new = product.get("step") == "nettoyant"

    for other in chosen:
        if other.get("id") == product.get("id"):
            continue
        # Un nettoyant reste quelques secondes sur la peau : il ne cumule pas
        # ses actifs avec ceux des soins laissés en place.
        if rinse_new or other.get("step") == "nettoyant":
            continue

        o_pot = families(other) & POTENT

        # Doublon de famille : interdit quel que soit le moment. Deux
        # rétinoïdes matin et soir, c'est la dose cumulée sur la journée qui
        # pose problème, pas leur simultanéité.
        both = pot & o_pot
        if both:
            fam = sorted(both)[0]
            return f"deux produits {_LABEL.get(fam, fam)} dans la même routine"

        # Paires antagonistes : seulement si elles se retrouvent sur la peau
        # au même moment.
        if not _moments_overlap(product, other):
            continue
        for a in pot:
            for b in o_pot:
                if frozenset({a, b}) in _INCOMPATIBLE_PAIRS:
                    return (f"{_LABEL.get(a, a)} et {_LABEL.get(b, b)} "
                            f"ne s'associent pas dans la même application")
    return None


_LABEL = {
    "retinoide": "à base de rétinoïde",
    "bha": "exfoliants BHA",
    "aha": "exfoliants AHA",
    "peroxyde_benzoyle": "au peroxyde de benzoyle",
    "azelaique": "à l'acide azélaïque",
    "vitamine_c": "à la vitamine C",
}


# --------------------------------------------------------------------------
# Contre-indications
# --------------------------------------------------------------------------
# Familles à écarter pendant la grossesse. Les rétinoïdes topiques sont
# déconseillés par principe de précaution ; l'acide salicylique reste admis
# aux concentrations cosmétiques usuelles mais pas en forte dose sur de
# grandes surfaces.
_PREGNANCY_FORBIDDEN = frozenset({"retinoide"})
_PREGNANCY_MAX_BHA_PCT = 2.0


def contraindicated(product: dict, profile: Optional[dict] = None) -> Optional[str]:
    """Motif de contre-indication absolue, sinon None.

    Distinct de `conflicts()` : ici le produit est écarté pour ce qu'il est,
    indépendamment du reste de la routine. Le catalogue ne portait aucune
    information de ce type — un sérum au rétinol pouvait donc être recommandé
    pendant une grossesse.
    """
    profile = profile or {}
    fams = families(product)

    if profile.get("pregnant"):
        forbidden = fams & _PREGNANCY_FORBIDDEN
        if forbidden:
            return "rétinoïde déconseillé pendant la grossesse"
        if "bha" in fams:
            pct = _max_pct(product)
            if pct is not None and pct > _PREGNANCY_MAX_BHA_PCT:
                return "acide salicylique fortement dosé pendant la grossesse"

    if profile.get("on_isotretinoin"):
        # Sous isotrétinoïne orale, la peau est déjà au maximum de sa
        # tolérance : tout exfoliant ou rétinoïde topique s'y ajoute mal.
        if fams & {"retinoide", "aha", "bha", "peroxyde_benzoyle"}:
            return "incompatible avec un traitement par isotrétinoïne"

    return None


# --------------------------------------------------------------------------
# Budget d'irritation
# --------------------------------------------------------------------------
def irritation_budget(needs: Dict[str, float], profile: Optional[dict] = None) -> float:
    """Charge irritante tolérable sur l'ensemble de la routine.

    Une peau réactive, une barrière fragilisée ou un débutant en actifs
    imposent un budget serré. C'est ce budget qui évite l'écueil classique des
    routines anti-acné trop agressives, qui aggravent l'inflammation au lieu de
    la calmer et font abandonner au bout de deux semaines.
    """
    profile = profile or {}
    budget = 1.30
    budget -= 0.60 * float(needs.get("redness", 0.0))

    skin = _norm(profile.get("skin_type") or "")
    if "seche" in skin:
        budget -= 0.20
    elif "grasse" in skin:
        budget += 0.20

    exp = _norm(profile.get("experience") or "")
    if "debut" in exp or "aucun" in exp:
        budget -= 0.30
    elif "avance" in exp or "experiment" in exp:
        budget += 0.25

    if profile.get("pregnant"):
        budget = min(budget, 0.55)
    if profile.get("on_isotretinoin"):
        budget = min(budget, 0.30)

    return float(max(0.25, min(2.0, budget)))


# --------------------------------------------------------------------------
# Introduction progressive
# --------------------------------------------------------------------------
def introduction_schedule(routine: List[dict],
                          needs: Optional[Dict[str, float]] = None) -> List[dict]:
    """Répartit l'arrivée des actifs dans le temps.

    Tout introduire le même jour est la première cause d'abandon d'une routine
    anti-acné : la peau réagit, l'utilisateur attribue l'irritation au
    traitement et arrête. On installe d'abord le socle non irritant, puis un
    actif toutes les deux semaines, du plus doux au plus fort.
    """
    needs = needs or {}
    base = [p for p in routine if irritation(p) < 0.30]
    actives = sorted((p for p in routine if irritation(p) >= 0.30),
                     key=irritation)

    gap = 3 if float(needs.get("redness", 0.0)) > 0.45 else 2
    steps: List[dict] = []

    if base:
        steps.append({
            "week": 1,
            "title": "Socle : nettoyer, hydrater, protéger",
            "detail": ("Deux semaines sans actif fort, le temps d'installer "
                       "l'habitude et de vérifier la tolérance de base."),
            "products": [p["id"] for p in base],
        })

    week = 1 + gap
    for p in actives:
        act = ", ".join(p.get("key_ingredients") or []) or "actif"
        steps.append({
            "week": week,
            "title": f"Introduction : {p['name']}",
            "detail": (f"{act}. Commencer un soir sur deux, puis tous les soirs "
                       f"si la peau le supporte bien."),
            "products": [p["id"]],
        })
        week += gap

    return steps


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
def audit_catalog(catalog: List[dict]) -> Dict[str, List[str]]:
    """Produits dont la famille n'a pas pu être dérivée, par étape.

    Sert à voir l'angle mort plutôt qu'à le supposer : un produit non classé
    n'est jamais bloqué par les règles d'incompatibilité.
    """
    out: Dict[str, List[str]] = {}
    for p in catalog:
        if not families(p):
            out.setdefault(p.get("step", "?"), []).append(p.get("id", "?"))
    return out
