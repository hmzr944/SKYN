"""SKYN Engine v2 — Etape 2 : phenotype cutane.

C'est le module qui manquait entierement en v1. Sans lui, l'application ne sait
pas si elle parle a une peau grasse ou a une peau seche, et recommande donc la
meme chose a tout le monde.

On produit ici trois axes independants, mesures et non declares :

* TYPE DE PEAU, deduit du differentiel zone T / zone U. C'est la definition
  clinique meme d'une peau mixte : une zone T qui brille alors que les joues ne
  brillent pas. v1 calculait le masque de zone T puis ne le lisait jamais.

* PHOTOTYPE, via l'angle typologique individuel (ITA), standard colorimetrique
  utilise en dermatologie pour objectiver la carnation :
      ITA = arctan((L* - 50) / b*) x 180 / pi
  Le phototype conditionne deux choses que les applications concurrentes ratent
  souvent : le risque d'hyperpigmentation post-inflammatoire (une peau foncee
  garde des marques brunes la ou une peau claire garde des marques rouges), et
  le choix du filtre solaire (les filtres mineraux laissent un voile blanc).

* REACTIVITE, via le canal a* de LAB apres correction de balance des blancs.

Les grandeurs de type "sebum" ou "hydratation" sont des PROXYS optiques, pas des
mesures biophysiques. Un sebumetre mesure le sebum ; une photo mesure la
reflexion speculaire qu'il produit. Les noms de variables le refletent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np

from .zones import FaceMap, T_ZONE, U_ZONE
from . import calibration as C


# --------------------------------------------------------------------------
# Bornes ITA -> phototype (echelle colorimetrique usuelle en dermatologie)
# --------------------------------------------------------------------------
ITA_BANDS = [
    (55.0, "I", "Tres claire"),
    (41.0, "II", "Claire"),
    (28.0, "III", "Intermediaire"),
    (10.0, "IV", "Mate"),
    (-30.0, "V", "Brune"),
    (-1e9, "VI", "Foncee"),
]


@dataclass
class ZoneStats:
    """Mesures brutes sur une zone."""
    name: str
    shine: float        # part de reflexion speculaire (proxy sebum), 0..1
    redness: float      # a* moyen au-dessus du neutre
    texture: float      # energie haute frequence (proxy grain / pores)
    l_mean: float       # luminance moyenne (L* 0..100)
    l_std: float        # dispersion de luminance (proxy uniformite)
    b_mean: float       # b* moyen (axe jaune-bleu, sert a l'ITA)
    dark_ratio: float   # part de pixels nettement plus sombres (proxy taches)
    hair_ratio: float


@dataclass
class Phenotype:
    skin_type: str              # grasse | mixte | normale | seche
    skin_type_confidence: float
    phototype: str              # I..VI
    phototype_label: str
    ita_deg: float
    sensitive: bool
    # Axes continus 0..1 (1 = marque)
    sebum_t: float
    sebum_u: float
    shine_delta: float
    dryness: float
    redness_global: float
    pore_load: float
    unevenness: float
    zones: Dict[str, ZoneStats] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
def _masked(arr: np.ndarray, mask: np.ndarray) -> Optional[np.ndarray]:
    if mask is None or mask.sum() == 0:
        return None
    v = arr[mask > 0]
    return v if v.size else None


def _shine_ratio(l_flat: np.ndarray, sat: np.ndarray, mask: np.ndarray,
                 l_ref: float, mad_ref: float) -> float:
    """Part de la zone en reflexion speculaire.

    Le sebum rend la peau brillante : elle renvoie une lumiere vive ET
    desaturee (le reflet prend la couleur de la source, pas celle de la peau).
    On exige donc les deux conditions, sinon une joue rose et lumineuse serait
    comptee comme grasse.
    """
    sel_l = _masked(l_flat, mask)
    sel_s = _masked(sat, mask)
    if sel_l is None or sel_s is None:
        return 0.0
    bright = sel_l > (l_ref + 1.6 * mad_ref)
    desat = sel_s < np.percentile(sel_s, 35)
    return float(np.mean(bright & desat))


def _texture_energy(l_flat: np.ndarray, mask: np.ndarray, face_w: int) -> float:
    """Energie haute frequence a l'echelle du pore.

    On travaille sur la luminance aplanie : le relief du visage ne doit pas
    compter comme du grain de peau.
    """
    sel = _masked(l_flat, mask)
    if sel is None:
        return 0.0
    sigma = max(1.0, face_w / 400.0)
    low = cv2.GaussianBlur(l_flat, (0, 0), sigma * 3.0)
    hi = l_flat - low
    v = _masked(hi, mask)
    return float(np.std(v)) if v is not None else 0.0


def _zone_stats(fm: FaceMap, sat: np.ndarray, l_ref: float, mad_ref: float,
                face_w: int) -> Dict[str, ZoneStats]:
    lab = fm.lab
    L = lab[:, :, 0] * (100.0 / 255.0)      # L* 0..100
    A = lab[:, :, 1] - 128.0                # a* centre
    B = lab[:, :, 2] - 128.0                # b* centre

    out: Dict[str, ZoneStats] = {}
    for name, z in fm.zones.items():
        if not z.available:
            continue
        m = z.mask
        l_sel = _masked(L, m)
        a_sel = _masked(A, m)
        b_sel = _masked(B, m)
        if l_sel is None or a_sel is None or b_sel is None:
            continue
        l_mean, l_std = float(l_sel.mean()), float(l_sel.std())
        med = float(np.median(l_sel))
        mad = float(np.median(np.abs(l_sel - med))) or 1.0
        dark_ratio = float(np.mean(l_sel < med - 1.8 * mad))
        out[name] = ZoneStats(
            name=name,
            shine=_shine_ratio(fm.l_flat, sat, m, l_ref, mad_ref),
            redness=max(0.0, float(a_sel.mean())),
            texture=_texture_energy(fm.l_flat, m, face_w),
            l_mean=l_mean, l_std=l_std, b_mean=float(b_sel.mean()),
            dark_ratio=dark_ratio, hair_ratio=z.hair_ratio,
        )
    return out


def _group_mean(stats: Dict[str, ZoneStats], names, attr: str) -> float:
    vals = [getattr(stats[n], attr) for n in names if n in stats]
    return float(np.mean(vals)) if vals else 0.0


def _ita(l_star: float, b_star: float) -> float:
    if abs(b_star) < 1e-6:
        b_star = 1e-6
    return math.degrees(math.atan((l_star - 50.0) / b_star))


def _phototype_from_ita(ita: float):
    for thr, code, label in ITA_BANDS:
        if ita > thr:
            return code, label
    return "VI", "Foncee"


def _norm(v: float, lo: float, hi: float) -> float:
    """Normalise lineairement dans 0..1 en bornant les extremes."""
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (v - lo) / (hi - lo))))


def analyze_phenotype(fm: FaceMap) -> Phenotype:
    if not fm.detected:
        return Phenotype(
            skin_type="indetermine", skin_type_confidence=0.0,
            phototype="?", phototype_label="Indeterminee", ita_deg=0.0,
            sensitive=False, sebum_t=0.0, sebum_u=0.0, shine_delta=0.0,
            dryness=0.0, redness_global=0.0, pore_load=0.0, unevenness=0.0,
            notes=["visage_non_detecte"],
        )

    face_w = max(1, fm.bbox[2])
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    sat = hsv[:, :, 1]

    ref = _masked(fm.l_flat, fm.skin_mask)
    l_ref = float(np.median(ref)) if ref is not None else 128.0
    mad_ref = float(np.median(np.abs(ref - l_ref))) if ref is not None else 1.0
    mad_ref = mad_ref or 1.0

    stats = _zone_stats(fm, sat, l_ref, mad_ref, face_w)
    notes: List[str] = []

    # --- Sebum : le differentiel T/U est le coeur du typage ----------------
    sebum_t_raw = _group_mean(stats, T_ZONE, "shine")
    sebum_u_raw = _group_mean(stats, U_ZONE, "shine")
    sebum_t = _norm(sebum_t_raw, *C.SHINE_RANGE)
    sebum_u = _norm(sebum_u_raw, *C.SHINE_RANGE)
    shine_delta = sebum_t - sebum_u

    # --- Grain de peau / pores --------------------------------------------
    tex_t = _group_mean(stats, T_ZONE, "texture")
    tex_u = _group_mean(stats, U_ZONE, "texture")
    pore_load = _norm(max(tex_t, tex_u), *C.TEXTURE_RANGE)

    # --- Secheresse : grain marque SANS brillance --------------------------
    # Une peau seche desquame : beaucoup de micro-relief, peu de reflet.
    dryness = _norm(tex_u, *C.TEXTURE_RANGE) * (1.0 - max(sebum_t, sebum_u))
    dryness = float(max(0.0, min(1.0, dryness)))

    # --- Rougeurs ----------------------------------------------------------
    red_vals = [s.redness for s in stats.values()]
    redness_raw = float(np.mean(red_vals)) if red_vals else 0.0
    redness_global = _norm(redness_raw, *C.REDNESS_RANGE)
    # Reactivite : rougeur diffuse marquee, concentree sur les joues et le nez
    red_cheeks = _group_mean(stats, ("joue_g", "joue_d", "nez"), "redness")
    sensitive = bool(red_cheeks > C.SENSITIVE_A_STAR_MIN
                     and redness_global > C.SENSITIVE_GLOBAL_MIN)

    # --- Uniformite du teint ----------------------------------------------
    l_stds = [s.l_std for s in stats.values()]
    unevenness = _norm(float(np.mean(l_stds)) if l_stds else 0.0,
                       *C.UNEVENNESS_RANGE)

    # --- Phototype (ITA) ---------------------------------------------------
    # Mesure sur les joues et le front : zones larges, planes et peu ombrees.
    ita_zones = [n for n in ("joue_g", "joue_d", "front") if n in stats]
    if ita_zones:
        l_star = float(np.mean([stats[n].l_mean for n in ita_zones]))
        b_star = float(np.mean([stats[n].b_mean for n in ita_zones]))
    else:
        l_star, b_star = 65.0, 15.0
        notes.append("phototype_estime_par_defaut")
    ita_deg = _ita(l_star, b_star)
    phototype, phototype_label = _phototype_from_ita(ita_deg)

    # L'ITA n'est fiable que sous un eclairage correct.
    if not fm.quality.usable or fm.quality.clipped > 0.08:
        notes.append("phototype_peu_fiable_eclairage")

    # --- Decision du type de peau -----------------------------------------
    skin_type, conf = _decide_skin_type(sebum_t, sebum_u, shine_delta, dryness)

    if any(s.hair_ratio > 0.35 for n, s in stats.items()
           if n in ("menton", "machoire_g", "machoire_d", "peri_oral")):
        notes.append("pilosite_importante_bas_du_visage")

    return Phenotype(
        skin_type=skin_type, skin_type_confidence=conf,
        phototype=phototype, phototype_label=phototype_label, ita_deg=ita_deg,
        sensitive=sensitive,
        sebum_t=sebum_t, sebum_u=sebum_u, shine_delta=shine_delta,
        dryness=dryness, redness_global=redness_global,
        pore_load=pore_load, unevenness=unevenness,
        zones=stats, notes=notes,
    )


def _decide_skin_type(sebum_t: float, sebum_u: float, delta: float,
                      dryness: float):
    """Arbre de decision sur le differentiel T/U.

    Retourne (type, confiance). La confiance traduit la marge par rapport aux
    seuils : proche d'une frontiere, on l'annonce comme incertain plutot que
    d'afficher une categorie peremptoire.
    """
    seb_max = max(sebum_t, sebum_u)

    if sebum_t >= C.OILY_T_MIN and sebum_u >= C.OILY_U_MIN:
        t = "grasse"
        margin = min(sebum_t - C.OILY_T_MIN, sebum_u - C.OILY_U_MIN)
    elif delta >= C.COMBO_DELTA_MIN and sebum_t >= C.COMBO_T_MIN:
        t = "mixte"
        margin = min(delta - C.COMBO_DELTA_MIN, sebum_t - C.COMBO_T_MIN)
    elif seb_max < C.DRY_SEBUM_MAX and dryness >= C.DRY_DRYNESS_MIN:
        t = "seche"
        margin = min(C.DRY_SEBUM_MAX - seb_max, dryness - C.DRY_DRYNESS_MIN)
    else:
        t = "normale"
        margin = 0.12
    conf = float(max(0.35, min(0.95, 0.55 + margin * 2.2)))
    return t, conf
