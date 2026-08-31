"""Suite du mini-chantier diagnostic — meme question, sur 4 captures reelles
a eclairages/angles differents (sujet 001, captures 005 a 008), pour savoir
si "l'ombre mange le signal" est un phenomene qui se reproduit ou un artefact
d'une seule photo.

REGLE STRICTE, inchangee : ni lesions.py ni calibration.py ne sont modifies.
Toute la mecanique de candidat/classification/trace vient telle quelle de
cheek_candidate_diagnostic.py (importee, pas dupliquee).

Nouveau dans ce banc : la question posee n'est plus seulement "combien sont
rejetes", mais "le patch contient-il deja un signal recuperable que la
MOYENNE pleine-patch detruit ?" — chaque candidat est desormais coupe en sa
moitie la plus claire / la plus sombre (Candidat.red_moitie_claire/sombre,
voir cheek_candidate_diagnostic.py), et on regarde si la moitie claire, a
elle seule, aurait franchi les seuils de _classify() la ou la moyenne
pleine-patch echoue. Aucun seuil de production n'est utilise pour decider
quoi que ce soit ici — seulement pour MESURER l'ecart.

Usage :
    python3 backend/tools/cheek_candidate_diagnostic_multi.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cheek_candidate_diagnostic import (  # noqa: E402
    CIBLES, Champs, Candidat, _b64_from_bgr, _candidats, _charger_oriente_bgr,
    _fmt, _verifier_trace, build_face_map,
)
from skyn_engine.v2.lesions import RED_IF_DARK  # noqa: E402
from tools.synth_lesions import _landmarks, plant  # noqa: E402

SUBJECT = Path("/home/user/real_skin_pilot/subject_001")
CAPTURES = [
    SUBJECT / "capture_005.jpg",
    SUBJECT / "capture_006.jpg",
    SUBJECT / "capture_007.jpg",
    SUBJECT / "capture_008.jpg",
]


class Resultat:
    """Ce qu'on retient d'UNE photo, pour la comparaison finale."""

    def __init__(self, nom: str):
        self.nom = nom
        self.detected = False
        self.joue: List[Candidat] = []
        self.synth_joue: List[Candidat] = []
        self.quality = None
        self.zones_L = {}


def _diagnostiquer(chemin: Path) -> Resultat:
    res = Resultat(chemin.name)
    bgr = _charger_oriente_bgr(chemin)
    fm = build_face_map(_b64_from_bgr(bgr))
    if not fm.detected:
        return res
    res.detected = True
    res.quality = fm.quality
    champs = Champs(fm)

    tous = _candidats(champs)
    joue = [c for c in tous if c.zone in CIBLES]
    _verifier_trace(joue)
    res.joue = joue

    for zname in ("nez", "joue_g", "joue_d", "front"):
        z = fm.zones.get(zname)
        if z is not None and z.available:
            zm = z.mask > 0
            res.zones_L[zname] = (
                float(champs.L[zm].mean()),
                float(champs.S[zm].mean()),
                float(champs.A[zm].mean()),
            )

    pts_repere = _landmarks(bgr)
    if pts_repere is not None:
        marque = bgr.copy()
        try:
            for zone in CIBLES:
                marque, _p = plant(marque, pts_repere, zone, 4, seed=11)
        except SystemExit:
            return res
        fm_synth = build_face_map(_b64_from_bgr(marque, quality=100))
        if fm_synth.detected:
            champs_synth = Champs(fm_synth)
            res.synth_joue = _candidats(champs_synth, zones_filtre=CIBLES)

    return res


def _rejet_red_if_dark(c: Candidat) -> bool:
    """Vrai si CE candidat rejete l'est bien via la garde RED_IF_DARK (dark
    assez negatif, red insuffisant) — distingue cette cause des autres
    (taille, marque_rouge trop petite, etc.) deja listees par
    _explique_rejet()."""
    return c.type is None and c.dark <= -1.2 and c.red <= RED_IF_DARK


def main() -> None:
    resultats = [_diagnostiquer(p) for p in CAPTURES]

    print("=" * 108)
    print("PAR PHOTO — candidats de joue, rejet RED_IF_DARK, éclairage local")
    print("=" * 108)
    header = (f"{'photo':<16}{'détecté':<9}{'n_joue':<8}{'rejet_RIF':<11}"
              f"{'n_synth':<9}{'synth_rejet_RIF':<17}{'L(nez)':>8}{'L(joue_g)':>11}{'L(joue_d)':>11}")
    print(header)
    for r in resultats:
        if not r.detected:
            print(f"{r.nom:<16}{'NON':<9}(visage non détecté — capture ignorée)")
            continue
        n_joue = len(r.joue)
        n_rif = sum(1 for c in r.joue if _rejet_red_if_dark(c))
        n_synth = len(r.synth_joue)
        n_synth_rif = sum(1 for c in r.synth_joue if _rejet_red_if_dark(c))
        l_nez = r.zones_L.get("nez", (float("nan"),))[0]
        l_jg = r.zones_L.get("joue_g", (float("nan"),))[0]
        l_jd = r.zones_L.get("joue_d", (float("nan"),))[0]
        print(f"{r.nom:<16}{'oui':<9}{n_joue:<8}{n_rif:<11}{n_synth:<9}{n_synth_rif:<17}"
              f"{l_nez:>8.1f}{l_jg:>11.1f}{l_jd:>11.1f}")

    print("\n" + "=" * 108)
    print("LE SIGNAL EST-IL RÉCUPÉRABLE ? Moitié claire du patch vs moyenne pleine-patch")
    print("=" * 108)
    print("Candidats de joue RÉELS rejetés par RED_IF_DARK, sur les 4 photos :\n")
    print(f"{'photo':<16}{'red (patch entier)':<20}{'red (moitié claire)':<22}"
          f"{'moitié claire > 1.8':<22}{'moitié claire > 4.5':<20}")
    total_rejetes = 0
    total_clair_depasse_18 = 0
    total_clair_depasse_45 = 0
    for r in resultats:
        rejetes = [c for c in r.joue if _rejet_red_if_dark(c) and c.red_moitie_claire is not None]
        for c in rejetes:
            total_rejetes += 1
            d18 = c.red_moitie_claire > 1.8
            d45 = c.red_moitie_claire > RED_IF_DARK
            total_clair_depasse_18 += int(d18)
            total_clair_depasse_45 += int(d45)
            print(f"{r.nom:<16}{c.red:<20.2f}{c.red_moitie_claire:<22.2f}"
                  f"{'oui' if d18 else 'non':<22}{'oui' if d45 else 'non':<20}")

    if total_rejetes:
        print(f"\nSur {total_rejetes} candidats réels rejetés (RED_IF_DARK, toutes photos confondues) :")
        print(f"  {total_clair_depasse_18}/{total_rejetes} ont une moitié claire "
              f"qui dépasse déjà 1.8 (le seuil \"peu sombre\")")
        print(f"  {total_clair_depasse_45}/{total_rejetes} ont une moitié claire "
              f"qui dépasse même 4.5 (RED_IF_DARK lui-même)")

    print("\nMême mesure sur les lésions SYNTHÉTIQUES (vérité terrain) rejetées :\n")
    print(f"{'photo':<16}{'red (patch entier)':<20}{'red (moitié claire)':<22}"
          f"{'moitié claire > 1.8':<22}{'moitié claire > 4.5':<20}")
    total_synth_rejetes = 0
    total_synth_clair_18 = 0
    total_synth_clair_45 = 0
    for r in resultats:
        rejetes = [c for c in r.synth_joue if _rejet_red_if_dark(c) and c.red_moitie_claire is not None]
        for c in rejetes:
            total_synth_rejetes += 1
            d18 = c.red_moitie_claire > 1.8
            d45 = c.red_moitie_claire > RED_IF_DARK
            total_synth_clair_18 += int(d18)
            total_synth_clair_45 += int(d45)
            print(f"{r.nom:<16}{c.red:<20.2f}{c.red_moitie_claire:<22.2f}"
                  f"{'oui' if d18 else 'non':<22}{'oui' if d45 else 'non':<20}")

    if total_synth_rejetes:
        print(f"\nSur {total_synth_rejetes} lésions synthétiques rejetées (RED_IF_DARK, toutes photos) :")
        print(f"  {total_synth_clair_18}/{total_synth_rejetes} ont une moitié claire > 1.8")
        print(f"  {total_synth_clair_45}/{total_synth_rejetes} ont une moitié claire > 4.5")

    print("\n" + "=" * 108)
    print("SYNTHÈSE — le phénomène se reproduit-il, et le signal est-il structurellement présent ?")
    print("=" * 108)
    def _distrib(cands: List[Candidat], label: str) -> None:
        if not cands:
            print(f"{label:<40} (aucun)")
            return
        red = np.array([c.red for c in cands])
        dark = np.array([c.dark for c in cands])
        print(f"{label:<40} n={len(cands):<4} red={red.mean():>5.2f}±{red.std():<5.2f} "
              f"dark={dark.mean():>6.2f}±{dark.std():<5.2f}")

    print("\nDistribution red/dark agrégée sur les 4 photos :")
    tous_joue_rejetes = [c for r in resultats for c in r.joue if _rejet_red_if_dark(c)]
    tous_joue_acceptes = [c for r in resultats for c in r.joue if c.type]
    tous_synth_rejetes = [c for r in resultats for c in r.synth_joue if _rejet_red_if_dark(c)]
    tous_synth_acceptes = [c for r in resultats for c in r.synth_joue if c.type]
    _distrib(tous_joue_rejetes, "Réels rejetés (RED_IF_DARK, 4 photos)")
    _distrib(tous_joue_acceptes, "Réels acceptés (4 photos)")
    _distrib(tous_synth_rejetes, "Synthétiques rejetés (RED_IF_DARK, 4 photos)")
    _distrib(tous_synth_acceptes, "Synthétiques acceptés (4 photos)")

    n_photos_ok = sum(1 for r in resultats if r.detected)
    n_photos_avec_rejet_rif = sum(
        1 for r in resultats if any(_rejet_red_if_dark(c) for c in r.joue)
    )
    n_photos_avec_synth_rejet = sum(
        1 for r in resultats if any(_rejet_red_if_dark(c) for c in r.synth_joue)
    )
    print(f"{n_photos_ok}/{len(CAPTURES)} photos exploitables.")
    print(f"RED_IF_DARK rejette au moins un candidat de joue réel sur "
          f"{n_photos_avec_rejet_rif}/{n_photos_ok} photos.")
    print(f"RED_IF_DARK rejette au moins une lésion SYNTHÉTIQUE (vérité terrain) sur "
          f"{n_photos_avec_synth_rejet}/{n_photos_ok} photos.")


if __name__ == "__main__":
    main()
