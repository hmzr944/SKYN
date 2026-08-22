"""SKYN Engine v2 — Etape 5 : correspondance produits et construction de routine.

C'est ici que se resout le defaut principal signale sur l'application actuelle :
tout le monde recevait les memes produits.

Cause en v1 : `expert_system.recommend()` piochait trois paragraphes dans une
bibliotheque de huit modeles. Cinq seulement etaient realistement eligibles, et
la protection solaire etait TOUJOURS candidate avec un poids fixe. Le nombre de
sorties possibles etait donc de l'ordre de la dizaine, quelle que soit la peau
analysee. Ce n'etait pas un reglage a ajuster : la structure meme du selecteur
plafonnait la personnalisation.

Principe retenu ici : on ne choisit plus dans une liste de textes, on evalue
CHAQUE produit du catalogue contre le vecteur de preoccupations mesure. Le score
est continu, donc deux vecteurs voisins donnent des routines voisines et deux
vecteurs eloignes donnent des routines franchement differentes.

S'ajoutent quatre regles de securite qui sont, elles aussi, personnalisantes :

* compatibilite avec le type de peau mesure ;
* contre-indications (grossesse, peau tres reactive, phototype) ;
* incompatibilites d'actifs au sein d'un meme moment de la journee — associer
  peroxyde de benzoyle et retinoide le meme soir, c'est la brulure assuree ;
* budget d'irritation, calcule d'apres la sensibilite mesuree et l'experience
  declaree, qui conditionne aussi l'introduction progressive des actifs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .concerns import SkinFingerprint, CONCERN_KEYS
from .phenotype import Phenotype

STEP_ORDER = ("nettoyant", "serum", "traitement", "hydratant", "protection")

# Etapes de socle : elles ne portent pas d'actif fort et ne doivent JAMAIS etre
# ecartees faute de budget d'irritation. Retirer la creme solaire d'une routine
# anti-acne serait un contresens : les actifs keratolytiques photosensibilisent,
# et l'exposition aggrave les marques post-inflammatoires. Quand le budget est
# serre, on ne supprime pas l'etape : on prend l'option la plus douce.
ESSENTIAL_STEPS = ("nettoyant", "hydratant", "protection")
# Etapes portant les actifs : ce sont elles que le budget d'irritation regule.
ACTIVE_STEPS = ("traitement", "serum")
STEP_LABEL = {
    "nettoyant": "Nettoyage",
    "serum": "Serum",
    "traitement": "Traitement cible",
    "hydratant": "Hydratation",
    "protection": "Protection solaire",
    "masque": "Masque",
}

# Etapes attendues dans chaque routine. La protection solaire n'a de sens que
# le matin ; les traitements keratolytiques et retinoides, que le soir.
AM_STEPS = ("nettoyant", "serum", "hydratant", "protection")
PM_STEPS = ("nettoyant", "traitement", "serum", "hydratant")


@dataclass
class Pick:
    product: dict
    score: float
    step: str
    moment: str
    why: List[str] = field(default_factory=list)
    introduce_week: int = 1

    def to_dict(self) -> dict:
        p = self.product
        return {
            "id": p["id"], "name": p["name"], "brand": p["brand"],
            "step": self.step, "moment": self.moment,
            "price_eur": p.get("price_eur"),
            "actives": p.get("actives", []),
            "family": p.get("family"),
            "evidence": p.get("evidence", {}),
            "url": p.get("url"),
            "irritation": p.get("irritation", 0.0),
            "match": round(self.score * 100),
            "why": self.why,
            "introduce_week": self.introduce_week,
        }


@dataclass
class Routine:
    am: List[Pick]
    pm: List[Pick]
    weekly: List[Pick]
    total_price: float
    irritation_load: float
    cautions: List[str] = field(default_factory=list)
    schedule: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "am": [p.to_dict() for p in self.am],
            "pm": [p.to_dict() for p in self.pm],
            "weekly": [p.to_dict() for p in self.weekly],
            "total_price": round(self.total_price, 2),
            "irritation_load": round(self.irritation_load, 2),
            "cautions": self.cautions,
            "schedule": self.schedule,
        }


# --------------------------------------------------------------------------
def _load_catalog() -> List[dict]:
    from .. import catalog_data
    return list(catalog_data.PRODUCTS)


def _fit_score(product: dict, fp: SkinFingerprint) -> Tuple[float, List[str]]:
    """Adequation d'un produit au vecteur mesure.

    On somme, pour chaque preoccupation que le produit revendique traiter,
    l'intensite mesuree de cette preoccupation ponderee par l'efficacite
    declaree. Un produit anti-acne obtient donc un score eleve chez une peau
    acneique et un score bas chez une peau seche et calme — ce qui est
    exactement le comportement qui manquait.
    """
    targets = product.get("targets", {}) or {}
    if not targets:
        return 0.0, []

    num = 0.0
    contributions: List[Tuple[float, str]] = []
    for concern, weight in targets.items():
        if concern not in CONCERN_KEYS:
            continue
        measured = fp.get(concern)
        c = measured * float(weight)
        num += c
        if c > 0.12:
            contributions.append((c, concern))

    # Normalisation par la puissance totale revendiquee : un produit qui cible
    # dix choses ne doit pas battre mecaniquement un produit tres cible.
    denom = sum(float(w) for w in targets.values()) or 1.0
    score = num / denom

    contributions.sort(reverse=True)
    why = [_why_text(c, name) for c, name in contributions[:3]]
    return float(max(0.0, min(1.0, score))), why


CONCERN_FR = {
    "acne_active": "lesions inflammatoires actives",
    "comedons": "comedons",
    "post_acne_marks": "marques post-acne",
    "sebum": "exces de sebum",
    "pores": "pores dilates",
    "redness": "rougeurs",
    "sensitivity": "reactivite cutanee",
    "dehydration": "deshydratation",
    "dullness": "teint terne",
    "pigmentation": "heterogeneite pigmentaire",
    "texture": "grain irregulier",
    "barrier_damage": "barriere alteree",
    "aging": "signes de vieillissement",
}


def _why_text(contribution: float, concern: str) -> str:
    lvl = "fortement" if contribution > 0.45 else "notablement" if contribution > 0.25 else "legerement"
    return f"cible {lvl} : {CONCERN_FR.get(concern, concern)}"


def _is_allowed(product: dict, ph: Phenotype, fp: SkinFingerprint,
                profile: dict) -> Tuple[bool, Optional[str]]:
    """Filtres durs. Retourne (autorise, motif de rejet)."""
    avoid = set(product.get("avoid_if", []) or [])

    if "grossesse" in avoid and (profile.get("pregnant") or "grossesse" in fp.flags):
        return False, "deconseille pendant la grossesse"

    very_sensitive = fp.get("sensitivity") > 0.6 or fp.get("barrier_damage") > 0.6
    if very_sensitive and "peau_tres_sensible" in avoid:
        return False, "trop irritant pour une peau actuellement reactive"

    if ph.phototype in ("V", "VI") and "phototype_5_6" in avoid:
        return False, "inadapte aux phototypes fonces"

    # Compatibilite de type de peau, quand le produit la precise
    st = product.get("skin_types") or []
    if st and ph.skin_type in ("grasse", "mixte", "normale", "seche"):
        if ph.skin_type not in st:
            return False, f"non adapte a une peau {ph.skin_type}"

    return True, None


# Familles dont l'empilement provoque reellement une irritation. Doubler un
# retinoide ou un exfoliant dans la meme routine expose a la brulure ; doubler
# du zinc ou de la niacinamide, non. La regle anti-doublon ne vise que celles-ci.
POTENT_FAMILIES = frozenset({
    "retinoid", "bha", "aha", "benzoyl_peroxide", "azelaic", "vitamin_c",
})


def _conflicts(product: dict, chosen: List[Pick]) -> bool:
    """Incompatibilite d'actifs a l'interieur d'un meme moment de la journee."""
    fam = product.get("family")
    conf = set(product.get("conflicts_with", []) or [])
    step = product.get("step")

    for pick in chosen:
        other = pick.product
        of = other.get("family")
        # Un nettoyant reste quelques secondes sur la peau avant rincage : il
        # ne cumule pas ses actifs avec ceux des soins laisses en place.
        rinse_off = step == "nettoyant" or other.get("step") == "nettoyant"

        if not rinse_off:
            if of and of in conf:
                return True
            if fam and fam in set(other.get("conflicts_with", []) or []):
                return True
            # Pas deux produits de la meme famille PUISSANTE dans un meme moment
            if fam and of and fam == of and fam in POTENT_FAMILIES:
                return True
    return False


def _irritation_budget(ph: Phenotype, fp: SkinFingerprint, profile: dict) -> float:
    """Quantite d'irritation tolerable sur l'ensemble de la routine.

    Une peau reactive, une barriere alteree ou un debutant en actifs imposent
    un budget serre. C'est ce budget qui empeche l'ecueil classique des
    routines "anti-acne" trop agressives, lesquelles aggravent l'inflammation.
    """
    budget = 1.6
    budget -= 0.7 * fp.get("sensitivity")
    budget -= 0.6 * fp.get("barrier_damage")
    budget -= 0.3 * fp.get("redness")
    if ph.skin_type == "seche":
        budget -= 0.2
    if ph.skin_type == "grasse":
        budget += 0.25
    level = str(profile.get("experience") or "").lower()
    if "debut" in level or "aucun" in level:
        budget -= 0.35
    elif "avance" in level or "experiment" in level:
        budget += 0.3
    if profile.get("on_isotretinoin"):
        budget = min(budget, 0.35)
    return float(max(0.25, min(2.4, budget)))


def _price_ceiling(profile: dict) -> float:
    """Plafond indicatif par produit, d'apres le budget declare."""
    b = str(profile.get("budget") or "").lower()
    if "petit" in b or "etudiant" in b or "serre" in b:
        return 13.0
    if "large" in b or "confort" in b or "eleve" in b:
        return 100.0
    return 25.0


def _pick_for_step(cands: List[dict], step: str, moment: str,
                   fp: SkinFingerprint, ph: Phenotype, profile: dict,
                   chosen: List[Pick], budget_left: float
                   ) -> Optional[Pick]:
    essential = step in ESSENTIAL_STEPS
    ceiling = _price_ceiling(profile)

    scored: List[Tuple[float, dict, List[str]]] = []
    for p in cands:
        if p.get("step") != step:
            continue
        pm = p.get("moment", "both")
        if pm not in ("both", moment):
            continue
        ok, _ = _is_allowed(p, ph, fp, profile)
        if not ok:
            continue
        if _conflicts(p, chosen):
            continue
        # Le budget d'irritation ne regit que les etapes actives : une etape de
        # socle est conservee quoi qu'il arrive, dans sa version la plus douce.
        if not essential and float(p.get("irritation", 0.0)) > budget_left:
            continue
        s, why = _fit_score(p, fp)
        scored.append((s, p, why))

    if not scored:
        return None

    # Classement final. Le prix intervient en penalite PROGRESSIVE et non en
    # seuil : un couperet net ecarterait un produit ideal pour cinquante
    # centimes de depassement, ce qui n'a aucun sens pour l'utilisateur.
    ranked: List[Tuple[float, float, dict, List[str]]] = []
    for s, p, why in scored:
        rank = _essential_score(p, s, ph, fp) if essential else s
        rank *= _price_penalty(float(p.get("price_eur", 0.0)), ceiling)
        ranked.append((rank, s, p, why))

    ranked.sort(key=lambda t: (-round(t[0], 4),
                               float(t[2].get("irritation", 0.0)),
                               float(t[2].get("price_eur", 999))))
    best_rank, best_fit, best_p, why = ranked[0]
    # Pour une etape de socle, le pourcentage affiche doit traduire l'adequation
    # au type de peau, pas la couverture des preoccupations : afficher "8 %"
    # sur un hydratant parfaitement adapte serait absurde pour l'utilisateur.
    best_s = _essential_score(best_p, best_fit, ph, fp) if essential else best_fit

    # Un traitement cible sans motif mesure n'a pas lieu d'etre ; une etape de
    # socle reste utile meme sans correspondance forte.
    if step in ACTIVE_STEPS and best_s < 0.16:
        return None

    if essential and not why:
        why = [_ESSENTIAL_WHY.get(step, "etape de base de la routine")]

    return Pick(product=best_p, score=best_s, step=step, moment=moment, why=why)


def _price_penalty(price: float, ceiling: float) -> float:
    """Penalite douce au-dela du plafond budgetaire.

    Un produit a 13,50 EUR pour un plafond a 13 EUR perd 2 % de son classement,
    pas sa place. Un produit a 45 EUR en perd la moitie.
    """
    if price <= ceiling:
        return 1.0
    over = (price - ceiling) / max(1.0, ceiling)
    return float(max(0.35, 1.0 / (1.0 + over)))


def _essential_score(product: dict, concern_fit: float, ph: Phenotype,
                     fp: SkinFingerprint) -> float:
    """Note d'adequation pour une etape de socle.

    Un nettoyant, un hydratant ou une creme solaire ne "traitent" pas une
    preoccupation mesuree : les noter sur ce critere les condamne a des scores
    ridicules et fait remonter des produits inadaptes. On les juge donc sur ce
    qui compte reellement pour eux — convenir au type de peau mesure, et ne pas
    agresser une peau deja reactive.

    La specificite est valorisee : a type de peau egal, un produit cible
    "grasse, mixte" convient mieux qu'un produit generaliste qui annonce
    convenir a tout le monde.
    """
    types = product.get("skin_types") or []
    if types and ph.skin_type in types:
        specificity = 1.0 / max(1.0, len(types))          # 0.25 a 1.0
        type_fit = 0.55 + 0.45 * min(1.0, specificity * 2.0)
    elif not types:
        type_fit = 0.5
    else:
        type_fit = 0.25

    gentleness = 1.0 - float(product.get("irritation", 0.0))
    reactive = max(fp.get("sensitivity"), fp.get("barrier_damage"))
    w_gentle = 0.25 + 0.35 * reactive        # peau reactive : douceur prioritaire

    return float(
        (1.0 - w_gentle - 0.20) * type_fit
        + w_gentle * gentleness
        + 0.20 * concern_fit
    )


_ESSENTIAL_WHY = {
    "nettoyant": "socle de la routine : retire sebum et residus sans decaper",
    "hydratant": "maintient la barriere cutanee pendant le traitement",
    "protection": "indispensable sous actifs : ils photosensibilisent la peau",
}


def _phototype_spf_note(ph: Phenotype, pick: Optional[Pick]) -> Optional[str]:
    if pick is None:
        return None
    if ph.phototype in ("IV", "V", "VI"):
        return ("Phototype fonce : privilegier une texture fluide sans filtre "
                "mineral blanchissant, et verifier l'absence de fini gris.")
    return None


def build_routine(fp: SkinFingerprint, ph: Phenotype,
                  profile: Optional[dict] = None,
                  catalog: Optional[List[dict]] = None) -> Routine:
    profile = profile or {}
    cat = catalog if catalog is not None else _load_catalog()

    budget_total = _irritation_budget(ph, fp, profile)
    cautions: List[str] = []

    am: List[Pick] = []
    pm: List[Pick] = []

    # --- Routine du soir en premier ---------------------------------------
    # C'est elle qui porte les actifs. On lui alloue l'essentiel du budget
    # d'irritation, le matin se contentant de nettoyer, hydrater et proteger.
    left = budget_total
    for step in PM_STEPS:
        pick = _pick_for_step(cat, step, "pm", fp, ph, profile, pm, left)
        if pick:
            pm.append(pick)
            # Seules les etapes actives consomment le budget d'irritation.
            if pick.step in ACTIVE_STEPS:
                left -= float(pick.product.get("irritation", 0.0))

    left_am = max(0.2, left)
    for step in AM_STEPS:
        pick = _pick_for_step(cat, step, "am", fp, ph, profile, am, left_am)
        if pick:
            am.append(pick)
            if pick.step in ACTIVE_STEPS:
                left_am -= float(pick.product.get("irritation", 0.0))

    # Ordonne selon la sequence d'application
    am.sort(key=lambda p: STEP_ORDER.index(p.step) if p.step in STEP_ORDER else 9)
    pm.sort(key=lambda p: STEP_ORDER.index(p.step) if p.step in STEP_ORDER else 9)

    # --- Soin hebdomadaire -------------------------------------------------
    weekly: List[Pick] = []
    if fp.get("sensitivity") < 0.5 and fp.get("barrier_damage") < 0.5:
        mp = _pick_for_step(cat, "masque", "both", fp, ph, profile, [], budget_total)
        if mp and mp.score >= 0.2:
            weekly.append(mp)

    all_picks = am + pm + weekly
    irritation_load = sum(float(p.product.get("irritation", 0.0)) for p in all_picks)

    # Prix : un produit present matin ET soir n'est achete qu'une fois
    seen_ids = {}
    for p in all_picks:
        seen_ids[p.product["id"]] = float(p.product.get("price_eur", 0.0))
    total_price = sum(seen_ids.values())

    # --- Introduction progressive -----------------------------------------
    schedule = _build_schedule(am, pm, weekly, fp)

    # --- Avertissements ----------------------------------------------------
    if fp.get("acne_active") >= 0.75:
        cautions.append(
            "Les lesions inflammatoires reperees sont nombreuses. Une acne de "
            "ce niveau releve d'un avis dermatologique : les traitements "
            "disponibles sans ordonnance ne suffisent generalement pas, et un "
            "traitement precoce limite le risque de cicatrices."
        )
    if fp.get("barrier_damage") > 0.55:
        cautions.append(
            "La barriere cutanee parait alteree. Le protocole ci-dessous "
            "commence volontairement par la reparer avant d'introduire tout "
            "actif exfoliant."
        )
    if profile.get("pregnant"):
        cautions.append(
            "Grossesse declaree : retinoides et salicyles a forte dose sont "
            "ecartes du protocole. A confirmer avec votre medecin."
        )
    note = _phototype_spf_note(ph, next((p for p in am if p.step == "protection"), None))
    if note:
        cautions.append(note)
    if not any(p.step == "protection" for p in am):
        cautions.append(
            "Aucune protection solaire n'a pu etre retenue dans le catalogue. "
            "C'est pourtant le geste le plus determinant, en particulier sous "
            "traitement anti-acne qui sensibilise au soleil."
        )

    return Routine(am=am, pm=pm, weekly=weekly, total_price=total_price,
                   irritation_load=irritation_load, cautions=cautions,
                   schedule=schedule)


def _build_schedule(am: List[Pick], pm: List[Pick], weekly: List[Pick],
                    fp: SkinFingerprint) -> List[dict]:
    """Repartit l'introduction des actifs dans le temps.

    Introduire simultanement plusieurs actifs est la premiere cause d'echec
    d'une routine anti-acne : la peau reagit, l'utilisateur attribue l'irritation
    au traitement et abandonne. On commence donc par le socle non irritant, puis
    on ajoute un actif toutes les deux semaines, du plus doux au plus fort.
    """
    base, actives = [], []
    for p in am + pm + weekly:
        if float(p.product.get("irritation", 0.0)) >= 0.35:
            actives.append(p)
        else:
            base.append(p)

    actives.sort(key=lambda p: float(p.product.get("irritation", 0.0)))

    # Peau reactive : on espace davantage
    gap = 3 if fp.get("sensitivity") > 0.45 else 2
    steps: List[dict] = []
    if base:
        for p in base:
            p.introduce_week = 1
        steps.append({
            "week": 1,
            "title": "Socle : nettoyer, hydrater, proteger",
            "detail": "Deux semaines sans actif fort, pour installer l'habitude "
                      "et verifier la tolerance de base.",
            "products": [p.product["id"] for p in base],
        })
    wk = 1 + gap
    for p in actives:
        p.introduce_week = wk
        act = ", ".join(a.get("common") or a.get("inci", "") for a in p.product.get("actives", [])) or "actif"
        steps.append({
            "week": wk,
            "title": f"Introduction : {p.product['name']}",
            "detail": f"{act}. Commencer un soir sur deux, puis tous les soirs "
                      f"si la tolerance est bonne.",
            "products": [p.product["id"]],
        })
        wk += gap
    return steps
