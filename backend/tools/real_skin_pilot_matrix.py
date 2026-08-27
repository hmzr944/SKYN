"""Real-Skin Pilot — matrice complete des 4 captures reelles.

────────────────────────────────────────────────────────────────────────
POURQUOI CE SCRIPT EXISTE.

Session D devait etre prise avec le MEME appareil que Session A, pour
isoler la variable appareil de la variable eclairage. Verifie avant toute
analyse : capture_004.jpg a la MEME resolution (3088x2316) et la MEME
orientation EXIF (5) que capture_002.jpg (B) et capture_003.jpg (C) — PAS
celles de capture_001.jpg (A : 1242x2208, EXIF=1). Donc B, C et D
partagent tres probablement le meme appareil ; A est l'exception. Ce
script ne pretend donc PAS avoir obtenu la comparaison "meme appareil que
A" demandee — elle reste manquante. Ce qu'il fait a la place : calculer
les 6 comparaisons deux-a-deux possibles entre les 4 captures pour voir
ce qu'on peut en tirer quand meme, notamment parmi B/C/D qui partagent un
appareil.

Chaque rapport de base (`analyze_face`) n'est calcule qu'UNE FOIS par
capture (4 appels), puis les 6 paires sont derivees de ces 4 rapports —
6x moins d'appels moteur que si chaque paire etait executee separement.

Rien n'est modifie en production. Aucune image commitee.

Usage :
    python3 backend/tools/real_skin_pilot_matrix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.tools.real_skin_pilot_session_ab import (  # noqa: E402
    RAYON_APPARIEMENT_AB,
    _appareiller,
    _charger_oriente,
    _rapport,
)

DOSSIER = Path("/home/user/real_skin_pilot/subject_001")
CAPTURES = [
    ("A", DOSSIER / "capture_001.jpg", "1242x2208, EXIF=1"),
    ("B", DOSSIER / "capture_002.jpg", "3088x2316, EXIF=5, sombre/casque"),
    ("C", DOSSIER / "capture_003.jpg", "3088x2316, EXIF=5, salle de bain claire"),
    ("D", DOSSIER / "capture_004.jpg", "3088x2316, EXIF=5, sombre/casque"),
]


def run() -> None:
    rapports = {}
    for nom, chemin, note in CAPTURES:
        if not chemin.exists():
            print(f"{nom} ({chemin.name}) absente — ignoree")
            continue
        img = _charger_oriente(chemin)
        rapports[nom] = _rapport(img)
        r = rapports[nom]
        print(f"{nom} [{note}] : score={r.global_score}  lesions={len(r.lesions)}  confiance={r.confidence:.2f}")

    print("\n" + "=" * 100)
    print("MATRICE DES 6 PAIRES (rayon d'appariement=" + str(RAYON_APPARIEMENT_AB) + ")")
    print("=" * 100)
    print(f"{'paire':<8} {'|Dscore|':>9} {'|Dcompte|':>10} {'retrouvees':>12} {'faux-evt':>9} "
          f"{'chang.classe':>13}  note")

    noms = list(rapports.keys())
    for i in range(len(noms)):
        for j in range(i + 1, len(noms)):
            na, nb = noms[i], noms[j]
            ra, rb = rapports[na], rapports[nb]
            appariees = _appareiller(ra.lesions, rb.lesions, RAYON_APPARIEMENT_AB)
            retrouvees = [(r, n) for r, n in appariees if n is not None]
            perdues = sum(1 for _, n in appariees if n is None)
            nouvelles = len(rb.lesions) - len(retrouvees)
            changements = sum(1 for r, n in retrouvees if r["type"] != n["type"])
            print(f"{na}-{nb:<6} {abs(ra.global_score-rb.global_score):>9} "
                  f"{abs(len(ra.lesions)-len(rb.lesions)):>10} "
                  f"{f'{len(retrouvees)}/{len(ra.lesions)}':>12} {perdues+nouvelles:>9} "
                  f"{f'{changements}/{len(retrouvees)}' if retrouvees else '-':>13}")

    print("\nA n'a pas d'equivalent 'meme appareil' parmi B/C/D dans ce jeu — toute paire "
          "impliquant A mesure a la fois appareil ET conditions. Seules les paires B-C, B-D, "
          "C-D partagent (probablement) le meme appareil.")
    print("Aucune image commitee. Aucune modification de production.")


if __name__ == "__main__":
    run()
