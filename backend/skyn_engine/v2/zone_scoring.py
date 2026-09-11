"""Score de propreté par zone pour le flux de scan guidé (multi-vue).

Isolé de lesions.py et de calibration.py : aucune reclassification ici. Ce
module part des lésions DÉJÀ confirmées par `multiview.orchestrer_scan()`
(chacune étiquetée d'une zone directement dans multiview.py, au moment où la
FaceMap de sa vue est disponible — pas une approximation recalculée ici) et
de la couverture de zone déjà accumulée par ce même appel, pour ne produire
qu'une seule chose : `zone_scores`, un dict zone -> 0..100.

La formule de charge (`_zone_burden`) est importée de pipeline.py au lieu
d'être réinventée — c'est la MÊME grandeur que le flux v2 (scan classique),
calculée à partir d'une source différente (lésions déjà votées sur plusieurs
vues plutôt qu'une seule détection), pas une échelle parallèle avec sa
propre calibration.

Une zone absente de `result.zones_couvertes` (jamais vue par une vue
utilisable) n'apparaît JAMAIS dans le dict retourné : "non mesurée" reste
distinct de "mesurée, propre" (score 100 pour zéro lésion confirmée). C'est
précisément le manque documenté dans skin_memory.py::_extract_scan_fields
(source == "guided") que ce module comble — voir server.py pour le point de
branchement dans /api/analyze/guided.
"""
from __future__ import annotations

from typing import Dict

from .multiview import ScanResult
from .pipeline import _zone_burden

# Les seules lesions qui pesent sur la composante "inflammatoire" de la
# charge — meme liste que pipeline.py::_zone_scores, pas une nouvelle regle.
LESIONS_INFLAMMATOIRES = ("papule", "pustule", "nodule")


def zone_scores_from_confirmed(result: ScanResult) -> Dict[str, int]:
    """Note 0-100 par zone reellement couverte par ce scan guide.

    Fonction pure : ne depend que des champs deja portes par `result`
    (lesions_confirmees, zones_couvertes, zone_area_cm2), donc deterministe —
    memes lesions confirmees en entree, meme dict en sortie, a chaque appel.
    """
    par_zone: Dict[str, Dict[str, int]] = {}
    for lesion in result.lesions_confirmees:
        zone = lesion.get("zone")
        if not zone or zone == "autre":
            continue
        ltype = lesion.get("type") or "?"
        compte = par_zone.setdefault(zone, {})
        compte[ltype] = compte.get(ltype, 0) + 1

    out: Dict[str, int] = {}
    for zone in result.zones_couvertes:
        area_cm2 = result.zone_area_cm2.get(zone, 0.0)
        if area_cm2 <= 0:
            # Zone marquee couverte mais sans aire exploitable : on ne
            # devine pas un score plutot que de le calculer sur du vide.
            continue
        compte = par_zone.get(zone, {})
        densite = sum(compte.values()) / area_cm2
        infl = sum(compte.get(t, 0) for t in LESIONS_INFLAMMATOIRES)
        out[zone] = int(round(100 * (1.0 - _zone_burden(densite, infl))))
    return out
