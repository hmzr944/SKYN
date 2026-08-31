"""P3 — Real Skin Benchmark : la fiche par sujet.

Ne mesure toujours rien de nouveau — agrège ce qu'engine_loss_funnel_audit.py
sait déjà faire (l'entonnoir de perte mono-vue, sur lésions synthétiques
plantées à position connue) en une fiche compacte par sujet, comme demandé :

    SUBJECT 001
    Détection visage        100 %
    Zones                    98 %
    Candidats                 XX %
    Classification            XX %
    Confirmation              XX %
    Stabilité multi-vue       XX %

REGLE STRICTE inchangée : lesions.py et calibration.py ne sont pas modifiés.
Rien ici ne decide quoi que ce soit — c'est une lecture, pas un chantier.

────────────────────────────────────────────────────────────────────────
CE QUE CHAQUE LIGNE MESURE EXACTEMENT (pour ne pas lire une fiche comme un
score de precision global, ce que ce chantier voulait explicitement eviter)

  Détection visage    — part des PHOTOS du sujet où un visage est détecté.
  Zones                — parmi les lésions plantées sur une photo où le
                          visage est détecté, part qui tombe dans une zone
                          disponible ET correctement attribuée.
  Candidats             — parmi celles qui ont franchi "Zones", part pour
                          laquelle un candidat est généré à proximité.
  Classification        — parmi celles qui ont franchi "Candidats", part
                          classifiée (donc confirmée — c'est la même chose
                          au sens du pipeline mono-vue actuel, il n'y a pas
                          d'étape supplémentaire entre les deux).
  Confirmation          — le rappel GLOBAL, cumulé : confirmées / plantées.
                          C'est la seule ligne qui résume tout l'entonnoir ;
                          les autres sont des taux LOCAUX, conditionnels à
                          l'étape précédente — deux sujets avec la même
                          "Confirmation" peuvent échouer à des étages
                          complètement différents, d'où l'intérêt de garder
                          le détail.
  Stabilité multi-vue   — PROXY, pas une vraie session de scan guidé :
                          stabilité du pipeline mono-vue sous perturbations
                          plausibles (stability_bench.py, déjà validé),
                          pas encore le tracking/vote-gate multi-vue réel
                          (qui a besoin d'une vraie séquence de 7-9 vues
                          consécutives du même sujet — pas encore
                          disponible pour de nouveaux sujets). Étiqueté
                          explicitement comme tel dans la fiche.

Usage :
    python3 backend/tools/subject_fiche.py <nom_sujet> <dossier_photos>
    python3 backend/tools/subject_fiche.py  # sans argument : sujets connus
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools.stability_bench import PERTURBATIONS  # noqa: E402
from tools.red_dark_calibration_bench import PERTURBATIONS_BALAYAGE  # noqa: E402
from tools.engine_loss_funnel_audit import auditer_photo, STAGES  # noqa: E402
from tools.classification_guard_bench import (  # noqa: E402
    garde_toujours_fausse, stabilite,
)
from tools.cheek_candidate_diagnostic import build_face_map, _b64_from_bgr, _charger_oriente_bgr  # noqa: E402

# Sujets déjà connus de cette session — chemins hors dépôt, jamais commités.
SUJETS_CONNUS: Dict[str, List[Path]] = {
    "001": [Path(f"/home/user/real_skin_pilot/subject_001/capture_{i}.jpg")
            for i in ("001", "002", "003", "004", "005", "006", "007", "008")],
    "002_fixture_depot": [BACKEND / "tests" / "fixtures_face.jpg"],
}


def photos_valides(photos: List[Path]) -> List[Path]:
    return [p for p in photos if p.exists()]


def fiche(nom: str, photos: List[Path], n_photos_stabilite: int = 2) -> None:
    photos = photos_valides(photos)
    print(f"\n{'=' * 70}\nSUBJECT {nom}  ({len(photos)} photo(s))\n{'=' * 70}")
    if not photos:
        print("  Aucune photo trouvée — fiche ignorée.")
        return

    pertes: Dict[str, Counter] = defaultdict(Counter)
    par_zone: Dict[str, Counter] = defaultdict(Counter)
    n_photos_detectees = 0

    for photo in photos:
        r = auditer_photo(photo, pertes, par_zone)
        if r.get("detectee"):
            n_photos_detectees += 1

    total: Counter = Counter()
    for c in pertes.values():
        total.update(c)
    n_total = sum(total.values())

    if n_total == 0:
        print("  Aucune lésion synthétique exploitable — fiche incomplète.")
        return

    # Taux locaux, conditionnels a l'etape precedente — pas la perte brute
    # deja affichee par engine_loss_funnel_audit.py.
    detection_pct = 100 * n_photos_detectees / len(photos)
    n_zone_ok = n_total - total.get("zone_disponible", 0) - total.get("attribution_zone", 0)
    zones_pct = 100 * n_zone_ok / n_total if n_total else 0.0
    n_candidat_ok = n_zone_ok - total.get("candidat_genere", 0)
    candidats_pct = 100 * n_candidat_ok / n_zone_ok if n_zone_ok else 0.0
    n_classif_ok = n_candidat_ok - total.get("classification", 0)
    classification_pct = 100 * n_classif_ok / n_candidat_ok if n_candidat_ok else 0.0
    confirmation_pct = 100 * total.get("confirme", 0) / n_total

    # Stabilite (proxy mono-vue) : sur au plus `n_photos_stabilite` photos,
    # pour rester a un cout raisonnable par sujet.
    stab_photos = photos[:n_photos_stabilite]
    instabs = []
    for p in stab_photos:
        bgr = _charger_oriente_bgr(p)
        if not build_face_map(_b64_from_bgr(bgr, quality=100)).detected:
            continue
        instabs.append(stabilite(garde_toujours_fausse, p, PERTURBATIONS_BALAYAGE)["instabilite"])
    stabilite_moy = (sum(instabs) / len(instabs)) if instabs else None

    print(f"Détection visage        {detection_pct:>5.0f} %   "
          f"({n_photos_detectees}/{len(photos)} photos)")
    print(f"Zones                   {zones_pct:>5.0f} %   "
          f"(sur {n_total} lésions plantées)")
    print(f"Candidats               {candidats_pct:>5.0f} %   "
          f"(sur {n_zone_ok} correctement zonées)")
    print(f"Classification          {classification_pct:>5.0f} %   "
          f"(sur {n_candidat_ok} avec un candidat)")
    print(f"Confirmation (rappel)   {confirmation_pct:>5.0f} %   (global, {n_total} plantées)")
    if stabilite_moy is not None:
        print(f"Stabilité mono-vue*     {stabilite_moy:>5.1f}   "
              f"(événements perdus/type/zone, {len(PERTURBATIONS_BALAYAGE)} perturbations, "
              f"moy. sur {len(instabs)} photo(s))")
    else:
        print("Stabilité mono-vue*     n/a")
    print("* proxy JPEG/luminosité/contraste/rotation — pas encore une vraie session "
          "multi-vue guidée pour ce sujet.")


def main() -> None:
    if len(sys.argv) >= 3:
        nom, dossier = sys.argv[1], Path(sys.argv[2])
        photos = sorted(dossier.glob("*.jpg")) + sorted(dossier.glob("*.jpeg"))
        fiche(nom, photos)
        return

    print("Aucun sujet précisé en argument — fiche des sujets déjà connus de cette session :")
    for nom, photos in SUJETS_CONNUS.items():
        fiche(nom, photos)


if __name__ == "__main__":
    main()
