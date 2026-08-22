"""SKYN Engine v2 — constantes de calibration.

AVERTISSEMENT IMPORTANT, a lire avant d'exploiter les scores.

Les bornes ci-dessous convertissent des mesures physiques (reflectance, canal
a* de LAB, energie haute frequence) en axes normalises 0..1. Elles ont ete
posees a partir de valeurs observees sur un petit nombre d'images, PAS sur une
cohorte annotee par des dermatologues.

Consequence : l'ordre des scores est fiable (une peau plus grasse qu'une autre
sortira bien avec un `sebum_t` plus eleve), mais la valeur absolue ne l'est pas
encore (un `sebum_t` de 0,74 ne signifie pas "74 % de sebum").

Pour calibrer serieusement il faut :
  1. Un jeu d'images avec type de peau et grade d'acne annotes par un
     professionnel, couvrant les six phototypes.
  2. Faire tourner `tools/calibrate.py` pour recalculer chaque borne sur les
     percentiles 5 et 95 de la cohorte.
  3. Verifier l'absence de biais par phototype : c'est le mode de defaillance
     classique de l'analyse cutanee par vision, les seuils de luminance regles
     sur des peaux claires degradent silencieusement les peaux foncees.

Tant que ce travail n'est pas fait, l'interface doit presenter les scores comme
des tendances relatives, jamais comme des mesures cliniques.
"""
from __future__ import annotations

# --- Phenotype : bornes de normalisation (valeur_basse, valeur_haute) ------
# La grandeur est ramenee lineairement dans 0..1 entre ces deux bornes.

SHINE_RANGE = (0.01, 0.22)
"""Part de pixels en reflexion speculaire. 0,01 = peau parfaitement mate."""

TEXTURE_RANGE = (2.0, 7.5)
"""Ecart-type du residu haute frequence de la luminance, a l'echelle du pore."""

REDNESS_RANGE = (4.0, 16.0)
"""a* moyen au-dessus du neutre, apres correction de balance des blancs."""

UNEVENNESS_RANGE = (3.0, 13.0)
"""Ecart-type de L* dans une zone : proxy d'uniformite du teint."""

# --- Seuils de decision du type de peau -----------------------------------
OILY_T_MIN = 0.55
OILY_U_MIN = 0.45
COMBO_DELTA_MIN = 0.18
COMBO_T_MIN = 0.35
DRY_SEBUM_MAX = 0.30
DRY_DRYNESS_MIN = 0.45

# --- Reactivite ------------------------------------------------------------
SENSITIVE_A_STAR_MIN = 13.0
SENSITIVE_GLOBAL_MIN = 0.45

# --- Detection de lesions --------------------------------------------------
LESION_MIN_MM = 0.8
LESION_MAX_MM = 6.0
"""Diametres plausibles : du microcomedon a la grosse papule."""

RED_BLOB_K = 2.2
DARK_BLOB_K = 2.6
"""Nombre d'ecarts robustes (MAD) au-dessus du fond local pour retenir un
candidat. Plus haut = plus conservateur, moins de faux positifs."""

BOUNDARY_MARGIN_MM = 1.5
"""Distance minimale au bord du masque peau. Les millimetres du contour
melangent peau, duvet et arriere-plan."""

# --- Classification des lesions -------------------------------------------
PUSTULE_RED_MIN = 1.6
PUSTULE_CORE_L_MIN = 0.8
PUSTULE_CORE_SAT_RATIO = 0.82
PAPULE_RED_MIN = 1.8
PAPULE_DARK_MIN = -1.2
COMEDON_DARK_MAX = -1.5
COMEDON_RED_MAX = 1.6
COMEDON_MM_MAX = 2.2
MARK_RED_MIN = 1.2
MARK_BROWN_YELLOW_MIN = 0.5

# --- Severite (paliers facon GAGS) ----------------------------------------
GAGS_BANDS = ((1.0, 0, "peau_nette"),
              (8.0, 1, "acne_legere"),
              (18.0, 2, "acne_moderee"),
              (30.0, 3, "acne_severe"),
              (float("inf"), 4, "acne_tres_severe"))
