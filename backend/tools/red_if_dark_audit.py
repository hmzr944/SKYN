"""Audit cible : RED_IF_DARK = 4,5 tombe-t-il dans un creux naturel de la
distribution, ou est-ce une valeur historique qui fonctionne aujourd'hui par
coincidence ?

────────────────────────────────────────────────────────────────────────
CE QUE CET AUDIT REPOND, ET CE QU'IL NE FAIT PAS.

`threshold_sensitivity.py` a deja montre que sur les 6 lesions actuellement
detectees, une seule est fragile, et qu'elle bascule exactement a la
frontiere RED_IF_DARK. Ca dit "c'est fragile ICI", pas "4,5 est un bon
choix" ou "4,5 est arbitraire". La question posee maintenant est differente :
si on regarde TOUTE la population de candidats eligibles a cette regle (pas
seulement ceux actuellement retenus), leur `red` se repartit-il en deux
paquets separes par un creux — auquel cas n'importe quel seuil dans ce creux
serait a peu pres equivalent, 4,5 y compris — ou la densite est-elle
continue autour de 4,5, auquel cas la valeur exacte compte et son origine
purement historique est un vrai risque ?

Aucune valeur n'est changee ici. C'est un audit de distribution, pas un
correctif — la consigne explicite est de ne PAS deplacer 4,5 juste pour
faire disparaitre la bascule deja identifiee.

Population eligible : tout candidat (source rouge OU sombre, retenu OU
rejete par la suite) qui tombe dans la branche `dark <= -1.2` de la regle
papule, c'est-a-dire la ou RED_IF_DARK est le seul filtre appliqué au canal
rouge — `d_mm >= 1.2` est deja requis par la regle elle-meme.

Usage :
    python3 backend/tools/red_if_dark_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2 import lesions as L  # noqa: E402
from backend.skyn_engine.v2.zones import build_face_map  # noqa: E402
from backend.tools.threshold_sensitivity import _b64, _tous_les_candidats  # noqa: E402

IMAGE = Path("backend/tests/fixtures_face.jpg")

# Fin pres de 4,5 (l'endroit qui compte), grossier ailleurs.
BALAYAGE = [4.0, 4.1, 4.2, 4.3, 4.35, 4.4, 4.45, 4.5, 4.55, 4.6, 4.65, 4.7, 4.8, 4.9, 5.0]


def run() -> None:
    img = cv2.imread(str(IMAGE))
    if img is None:
        raise SystemExit(f"image introuvable : {IMAGE}")
    fm = build_face_map(_b64(img))
    if not fm.detected:
        raise SystemExit("visage non detecte")

    tous = _tous_les_candidats(fm)
    valeur_dorigine = L.RED_IF_DARK

    eligibles = []
    for c in tous:
        d_mm = 2.0 * c.r_px / c.px_per_mm
        if c.dark <= -1.2 and d_mm >= 1.2:
            eligibles.append((c, d_mm))

    print(f"{len(tous)} candidats au total   |   {len(eligibles)} eligibles a la regle "
          f"RED_IF_DARK (dark <= -1.2 et d_mm >= 1.2)\n")

    if not eligibles:
        print("Aucun candidat eligible sur cette image de reference — l'audit "
              "de distribution ne peut pas conclure avec une population vide. "
              "Il faudra l'elargir a d'autres images pour juger 4,5.")
        return

    # ── 1. La distribution brute des `red` dans la population eligible. ──
    rouges = sorted(c.red for c, _ in eligibles)
    print(f"{'red (trie)':>12}")
    for r in rouges:
        print(f"{r:>12.2f}")

    ecarts = [(rouges[i + 1] - rouges[i], rouges[i], rouges[i + 1])
              for i in range(len(rouges) - 1)]
    if ecarts:
        # Le plus grand creux GLOBAL n'est pas la bonne question : sur cette
        # population, il separe des ombres tres sombres (red < 0) du reste de
        # la distribution, ce qui n'a rien a voir avec ou placer RED_IF_DARK.
        # Ce qui compte, c'est la structure LOCALE pres de 4,5 : on liste les
        # creux les plus larges, tries par taille, et on regarde ou 4,5 tombe.
        top5 = sorted(ecarts, key=lambda e: -e[0])[:5]
        print("\nplus larges creux de la distribution (tries par taille) :")
        for taille, bas, haut in top5:
            marque = "  <- 4,5 tombe ici" if bas < 4.5 < haut else ""
            print(f"  {taille:.2f}  (entre red={bas:.2f} et red={haut:.2f}){marque}")

        creux_local = next(((t, b, h) for t, b, h in top5 if b < 4.5 < h), None)
        if creux_local:
            print(f"\n4,5 tombe dans un creux local de {creux_local[0]:.2f} "
                  f"(entre {creux_local[1]:.2f} et {creux_local[2]:.2f}).")
        else:
            proche = min(rouges, key=lambda r: abs(r - 4.5))
            print(f"\n4,5 ne tombe dans AUCUN des {len(top5)} plus larges creux — "
                  f"le candidat eligible le plus proche a red={proche:.2f} "
                  f"(ecart {abs(proche-4.5):.2f}).")

        n_au_dela_de_3_5 = sum(1 for r in rouges if r > 3.5)
        print(f"\nATTENTION taille d'echantillon : seuls {n_au_dela_de_3_5} candidats "
              f"eligibles depassent red=3,5 sur cette unique photo de reference. "
              f"Toute conclusion sur un creux au-dela de ce point repose sur une "
              f"poignee de points — ce n'est pas une distribution assez peuplee "
              f"pour trancher seule ; il faudrait la revoir sur plusieurs photos.")

    # ── 2. Chaque candidat eligible, sa marge a 4,5, sa stabilite. ──
    print(f"\n{'zone':<10} {'src':<7} {'red':>6} {'dark':>7} {'marge a 4.5':>12} "
          f"{'classe a 4.5':<14} {'stable +-10%?':<14}")
    for c, d_mm in sorted(eligibles, key=lambda e: e[0].red):
        marge = c.red - 4.5
        L.RED_IF_DARK = 4.5
        classe_45 = L._classify(c.red, c.dark, c.yellow, c.core_l, c.core_s,
                                 c.skin_s, c.r_px, c.px_per_mm, c.src)
        stable = True
        for v in (4.05, 4.95):
            L.RED_IF_DARK = v
            d = L._classify(c.red, c.dark, c.yellow, c.core_l, c.core_s,
                            c.skin_s, c.r_px, c.px_per_mm, c.src)
            if d != classe_45:
                stable = False
        L.RED_IF_DARK = valeur_dorigine
        print(f"{c.zone:<10} {c.src:<7} {c.red:>6.2f} {c.dark:>7.2f} {marge:>+12.2f} "
              f"{str(classe_45):<14} {str(stable):<14}")

    # ── 3. Balayage : combien de candidats seraient acceptes a chaque valeur ? ──
    print(f"\n{'RED_IF_DARK':>12} {'papules (branche sombre)':>26} {'papules (total)':>17}")
    for v in BALAYAGE:
        L.RED_IF_DARK = v
        n_branche = sum(
            1 for c, d_mm in eligibles
            if L._classify(c.red, c.dark, c.yellow, c.core_l, c.core_s,
                           c.skin_s, c.r_px, c.px_per_mm, c.src) == "papule"
        )
        n_total = sum(
            1 for c in tous
            if L._classify(c.red, c.dark, c.yellow, c.core_l, c.core_s,
                           c.skin_s, c.r_px, c.px_per_mm, c.src) == "papule"
        )
        marque = "  <- valeur actuelle" if v == 4.5 else ""
        print(f"{v:>12.2f} {n_branche:>26} {n_total:>17}{marque}")
    L.RED_IF_DARK = valeur_dorigine


if __name__ == "__main__":
    run()
