"""SKYN Engine v2 — Etape 3 : detection et classification des lesions.

Trois defauts de v1 sont corriges ici, tous les trois bloquants pour une acne
moderee a severe :

1. v1 s'arretait a `max_n=5`. Une personne avec cinq lesions et une personne
   avec quarante obtenaient exactement le meme score. Le moteur etait donc
   incapable de distinguer une acne legere d'une acne severe : c'est la raison
   pour laquelle 1,6 % seulement des profils simules recevaient le diagnostic
   "Imperfections actives". Ici on compte TOUT, sans plafond.

2. v1 ne cherchait que des taches SOMBRES (`_detect_dark_blobs`). Or une lesion
   inflammatoire — papule, pustule — est rouge et souvent plus CLAIRE que la
   peau autour. Le detecteur etait aveugle a l'acne active, et ne voyait
   essentiellement que les comedons ouverts, les grains de beaute et les
   sourcils. On travaille ici sur trois cartes : exces de rouge, exces de
   sombre, et coeur clair desature (le centre purulent d'une pustule).

3. v1 renvoyait un type unique, "spot". Impossible d'adapter le conseil : un
   comedon se traite par un keratolytique, une papule inflammatoire par un
   anti-inflammatoire, une marque post-acne par un depigmentant. On distingue
   ici cinq categories.

Note d'honnetete : ceci reste de la vision par ordinateur classique. Une lesion
est reperee par sa signature optique, pas par un diagnostic histologique. Le
module expose un contrat stable (`detect_lesions`) pour qu'un modele appris
puisse le remplacer sans toucher au reste du moteur.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .zones import FaceMap, ZONE_WEIGHT
from . import calibration as C

# Largeur faciale bizygomatique moyenne chez l'adulte, en millimetres. Sert a
# convertir les tailles de lesion en pixels quelle que soit la distance de prise
# de vue.
FACE_WIDTH_MM = 140.0

LESION_TYPES = ("comedon", "papule", "pustule", "marque_rouge", "marque_brune")

# Gravite relative, inspiree du Global Acne Grading System : un comedon vaut 1,
# une papule 2, une pustule 3, un nodule 4. Les marques post-inflammatoires ne
# sont pas des lesions actives : elles comptent peu dans la severite mais
# beaucoup dans le choix des produits.
LESION_SEVERITY = {
    "comedon": 1.0,
    "papule": 2.0,
    "pustule": 3.0,
    "marque_rouge": 0.5,
    "marque_brune": 0.5,
}


@dataclass
class Lesion:
    type: str
    x: float            # centre, normalise 0..1 sur la bbox du visage
    y: float
    radius: float       # normalise sur la plus grande dimension de la bbox
    diameter_mm: float  # estimation metrique
    zone: str
    confidence: float
    redness: float      # exces de a* par rapport a la peau voisine
    darkness: float     # exces de luminance (negatif = plus sombre)


@dataclass
class LesionReport:
    lesions: List[Lesion]
    counts: Dict[str, int]                    # par type
    per_zone: Dict[str, Dict[str, int]]       # zone -> type -> compte
    density: Dict[str, float]                 # zone -> lesions par cm2
    gags_score: float
    severity_level: int                       # 0..4
    severity_label: str
    inflammatory_ratio: float                 # part de lesions inflammatoires
    dominant_zones: List[str]
    hormonal_pattern: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lesions"] = [asdict(l) if not isinstance(l, dict) else l
                        for l in self.lesions]
        return d


# --------------------------------------------------------------------------
def _local_excess(chan: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Ecart d'un canal a son fond local, calcule sur la peau UNIQUEMENT.

    On compare chaque pixel a son voisinage large plutot qu'a la moyenne du
    visage : une pommette naturellement plus rosee ne doit pas generer des
    dizaines de fausses lesions.

    Le fond est estime par convolution normalisee : on floute le canal masque
    puis on divise par le masque floute, de sorte que seuls les pixels de peau
    contribuent. Un flou gaussien ordinaire ferait deborder les cheveux, le
    fond de l'image et l'ombre du cou dans l'estimation ; au bord du visage le
    fond serait alors trop sombre, et toute la mandibule ressortirait comme une
    zone en "exces de rouge". C'etait la principale source de faux positifs.
    """
    m = (mask > 0).astype(np.float32)
    num = cv2.GaussianBlur(chan * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    bg = num / np.maximum(den, 1e-3)
    return (chan - bg) * m


def _robust_thr(vals: np.ndarray, k: float) -> float:
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) or 1e-3
    return med + k * 1.4826 * mad


def _zone_of(fm: FaceMap, cx: int, cy: int) -> str:
    for name, z in fm.zones.items():
        if z.available and z.mask[cy, cx] > 0:
            return name
    return "autre"


def _shape_stats(comp: np.ndarray) -> Optional[Tuple[int, int, int, float, float]]:
    """Aire, largeur, hauteur, remplissage et circularite d'un masque binaire
    d'une seule composante. `None` si le contour est degenere."""
    ys, xs = np.nonzero(comp)
    if ys.size == 0:
        return None
    area = int(ys.size)
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    fill = area / float(max(1, bw * bh))
    cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    perim = cv2.arcLength(cnts[0], True)
    if perim <= 0:
        return None
    circularity = 4.0 * np.pi * area / (perim * perim)
    return area, bw, bh, fill, circularity


def _passes_shape(area: int, bw: int, bh: int, fill: float, circularity: float,
                  a_min: int, a_max: int) -> bool:
    """Le meme jeu de criteres pour un candidat isole ou pour un fragment issu
    d'une separation — c'est ce qui garantit qu'un fragment n'est retenu que
    s'il ressemble VRAIMENT a une lesion, pas seulement parce qu'il est plus
    petit que le bloc dont il vient."""
    if area < a_min or area > a_max:
        return False
    if max(bw, bh) > 3.2 * max(1, min(bw, bh)):
        return False
    if fill < 0.32:
        return False
    if circularity < 0.55:
        return False
    return True


def _split_touching(comp: np.ndarray, r_min_px: float) -> List[np.ndarray]:
    """Separe une composante en lesions individuelles quand elle en contient
    plusieurs collees, par ligne de partage des eaux.

    ────────────────────────────────────────────────────────────────────────
    POURQUOI CETTE ETAPE MANQUAIT.

    Deux ou trois lesions rondes qui se touchent forment, une fois binarisees,
    UNE SEULE composante connexe — allongee, avec une aire qui peut depasser
    le plafond d'une lesion seule. Les filtres de forme existants (aire,
    circularite) rejettent alors le tout, perdant plusieurs lesions a la fois
    a cause d'une seule. Diagnostic mesure sur le banc de reference : 6 des 8
    lesions non retrouvees etaient dans ce cas — chacune partageait sa
    composante avec une ou deux voisines plantees a proximite.

    La transformee de distance d'une composante formee de disques qui se
    touchent presente un maximum local PAR DISQUE — c'est la signature meme
    d'un amas de taches rondes, la ou une structure lineaire (poil, pli,
    ombre) n'en presente qu'un, faible et continu le long de sa longueur. Le
    seuil sur la hauteur du maximum (`r_min_px * 0.6`) ecarte ces structures :
    une ombre fine n'atteint jamais une distance au bord comparable au rayon
    minimal d'une lesion plausible.

    Chaque fragment issu du partage repasse ensuite par EXACTEMENT les memes
    criteres de forme qu'un candidat isole (`_passes_shape`) : rien n'est
    retenu ici pour la seule raison qu'il est plus petit que le bloc d'origine.
    ────────────────────────────────────────────────────────────────────────
    """
    dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
    seuil_pic = max(1.5, r_min_px * 0.6)
    local_max = (dist == cv2.dilate(dist, np.ones((5, 5), np.uint8))) & (dist > seuil_pic)
    n_seeds, seed_labels = cv2.connectedComponents(local_max.astype(np.uint8))
    # 1 seul foyer (0 = fond) : rien a separer, c'est une lesion unique.
    if n_seeds <= 2:
        return []

    # Convention de `cv2.watershed` : 0 = INCONNU, a remplir par le partage ;
    # tout le reste doit deja porter un marqueur distinct. Y compris le fond,
    # qui a droit a SON PROPRE marqueur (1) plutot qu'a 0 — sans quoi le fond
    # se ferait lui aussi inonder comme s'il restait a determiner.
    #
    # La premiere version mettait `seed_labels + 1` PARTOUT (fond du calcul de
    # `connectedComponents` compris) puis ne remettait a 0 que le vrai fond de
    # `comp` : chaque pixel du premier plan qui n'etait pas lui-meme un germe
    # heritait donc du marqueur "1", DEJA attribue, au lieu de rester "a
    # determiner". Le partage n'avait alors plus rien a inonder, et les
    # fragments rendus faisaient 1 pixel — la separation ne separait rien.
    markers = np.zeros(comp.shape, dtype=np.int32)
    markers[comp == 0] = 1
    markers[seed_labels > 0] = seed_labels[seed_labels > 0] + 1
    color = cv2.cvtColor(comp * 255, cv2.COLOR_GRAY2BGR)
    cv2.watershed(color, markers)

    fragments = []
    for lbl in range(2, n_seeds + 1):
        frag = (markers == lbl).astype(np.uint8)
        if frag.sum() > 0:
            fragments.append(frag)
    return fragments


def _blob_candidates(excess: np.ndarray, mask: np.ndarray, k: float,
                     a_min: int, a_max: int) -> List[Tuple[int, int, float, int]]:
    """Composantes connexes au-dessus d'un seuil robuste.

    Retourne (cx, cy, aire, label) pour chaque candidat de taille plausible.
    Le label distingue les candidats entre eux mais ne correspond plus
    directement a une etiquette de `connectedComponents` : un candidat issu
    d'une separation recoit un label negatif, unique dans l'appel.
    """
    sel = excess[mask > 0]
    if sel.size < 50:
        return []
    thr = _robust_thr(sel, k)
    binary = ((excess > thr) & (mask > 0)).astype(np.uint8) * 255
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    n, labels, stats, cent = cv2.connectedComponentsWithStats(binary, connectivity=8)
    r_min_px = float(np.sqrt(max(a_min, 1) / np.pi))
    out = []
    prochain_label_fragment = -1
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        comp = (labels[
            stats[i, cv2.CC_STAT_TOP]:stats[i, cv2.CC_STAT_TOP] + bh,
            stats[i, cv2.CC_STAT_LEFT]:stats[i, cv2.CC_STAT_LEFT] + bw
        ] == i).astype(np.uint8)
        shape = _shape_stats(comp)
        if shape is None:
            continue
        s_area, s_bw, s_bh, fill, circularity = shape
        if _passes_shape(s_area, s_bw, s_bh, fill, circularity, a_min, a_max):
            out.append((int(cent[i][0]), int(cent[i][1]), float(area), i))
            continue

        # Rejete tel quel : peut-etre plusieurs lesions collees. On ne tente
        # la separation que si le bloc est assez grand pour en contenir
        # plusieurs — l'essayer sur un fragment deja minuscule ne ferait que
        # chercher du bruit dans du bruit.
        if area < a_min * 1.6:
            continue
        for frag in _split_touching(comp, r_min_px):
            fshape = _shape_stats(frag)
            if fshape is None:
                continue
            f_area, f_bw, f_bh, f_fill, f_circ = fshape
            if not _passes_shape(f_area, f_bw, f_bh, f_fill, f_circ, a_min, a_max):
                continue
            ys, xs = np.nonzero(frag)
            top = int(stats[i, cv2.CC_STAT_TOP])
            left = int(stats[i, cv2.CC_STAT_LEFT])
            fcx = int(round(float(xs.mean()))) + left
            fcy = int(round(float(ys.mean()))) + top
            out.append((fcx, fcy, float(f_area), prochain_label_fragment))
            prochain_label_fragment -= 1
    return out


def detect_lesions(fm: FaceMap) -> LesionReport:
    if not fm.detected or fm.skin_mask.sum() == 0:
        return LesionReport([], {t: 0 for t in LESION_TYPES}, {}, {},
                            0.0, 0, "indetermine", 0.0, [], False)

    face_w = max(1.0, float(fm.bbox[2]))
    px_per_mm = face_w / FACE_WIDTH_MM

    lab = fm.lab
    A = lab[:, :, 1] - 128.0                    # a* : axe vert-rouge
    B = lab[:, :, 2] - 128.0                    # b* : axe bleu-jaune
    L = fm.l_flat                               # luminance sans ombrage
    hsv = cv2.cvtColor(fm.rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[:, :, 1]

    # Fond local a une echelle nettement superieure a la plus grosse lesion
    mask = fm.skin_mask
    sigma_bg = max(4.0, 5.0 * px_per_mm)
    a_exc = _local_excess(A, mask, sigma_bg)
    l_exc = _local_excess(L, mask, sigma_bg)
    b_exc = _local_excess(B, mask, sigma_bg)

    # Zone de mesure fiable : on ecarte une bande le long du contour du masque.
    # Meme avec un fond local propre, les quelques millimetres du bord melangent
    # peau, duvet et arriere-plan, et la frontiere du masque n'est jamais au
    # pixel pres. On exige donc une distance minimale au bord.
    margin_px = max(3.0, C.BOUNDARY_MARGIN_MM * px_per_mm)
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    core_mask = ((dist > margin_px) * 255).astype(np.uint8)

    # Le contour de l'oeil est structurellement inexploitable pour la detection
    # de lesions : cerne, creux lacrymal et ombre des cils y produisent en
    # permanence des taches sombres arrondies. On l'ecarte de la recherche.
    # Ces zones restent analysees par ailleurs (cernes, deshydratation).
    for zn in ("sous_yeux_g", "sous_yeux_d"):
        z = fm.zones.get(zn)
        if z is not None and z.available:
            core_mask = cv2.bitwise_and(core_mask, cv2.bitwise_not(z.mask))

    # Bornes de taille : du microcomedon a la grosse papule
    r_min_px = max(1.2, (C.LESION_MIN_MM / 2.0) * px_per_mm)
    r_max_px = max(4.0, (C.LESION_MAX_MM / 2.0) * px_per_mm)
    a_min = max(4, int(np.pi * r_min_px ** 2))
    a_max = max(a_min + 8, int(np.pi * r_max_px ** 2))

    cands: Dict[Tuple[int, int], Tuple[float, str]] = {}

    # (a) Lesions inflammatoires : exces de rouge
    for cx, cy, area, _ in _blob_candidates(a_exc, core_mask, C.RED_BLOB_K,
                                            a_min, a_max):
        cands[(cx, cy)] = (area, "rouge")
    # (b) Comedons ouverts et marques brunes : exces de sombre
    for cx, cy, area, _ in _blob_candidates(-l_exc, core_mask, C.DARK_BLOB_K,
                                            a_min, a_max):
        if (cx, cy) not in cands:
            cands[(cx, cy)] = (area, "sombre")

    if not cands:
        return LesionReport([], {t: 0 for t in LESION_TYPES}, {}, {},
                            0.0, 0, "peau_nette", 0.0, [], False)

    # Deduplication spatiale : deux cartes peuvent reperer la meme lesion
    pts = sorted(cands.items(), key=lambda kv: -kv[1][0])
    kept: List[Tuple[int, int, float, str]] = []
    min_sep = max(3.0, 1.2 * px_per_mm)
    for (cx, cy), (area, src) in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < min_sep ** 2
               for kx, ky, _, _ in kept):
            continue
        kept.append((cx, cy, area, src))

    h, w = mask.shape
    bx, by, bw, bh = fm.bbox
    norm_dim = float(max(bw, bh)) or 1.0

    skin_s = float(S[mask > 0].mean())

    lesions: List[Lesion] = []
    for cx, cy, area, src in kept:
        r_px = float(np.sqrt(area / np.pi))
        rr = max(1, int(round(r_px)))
        y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
        x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        patch_m = mask[y0:y1, x0:x1] > 0
        if patch_m.sum() < 3:
            continue

        red = float(a_exc[y0:y1, x0:x1][patch_m].mean())
        dark = float(l_exc[y0:y1, x0:x1][patch_m].mean())
        yellow = float(b_exc[y0:y1, x0:x1][patch_m].mean())

        # Coeur de la lesion : un noyau clair et desature signe une pustule
        cr = max(1, int(r_px * 0.5))
        cy0, cy1 = max(0, cy - cr), min(h, cy + cr + 1)
        cx0, cx1 = max(0, cx - cr), min(w, cx + cr + 1)
        core_l = float(l_exc[cy0:cy1, cx0:cx1].mean())
        core_s = float(S[cy0:cy1, cx0:cx1].mean())

        ltype = _classify(red, dark, yellow, core_l, core_s, skin_s,
                          r_px, px_per_mm, src)
        if ltype is None:
            continue

        conf = _confidence(ltype, red, dark, core_l, area, a_min, a_max)
        lesions.append(Lesion(
            type=ltype,
            x=float((cx - bx) / max(1, bw)),
            y=float((cy - by) / max(1, bh)),
            radius=float(r_px / norm_dim),
            diameter_mm=float(2.0 * r_px / px_per_mm),
            zone=_zone_of(fm, cx, cy),
            confidence=conf,
            redness=red, darkness=dark,
        ))

    return _build_report(fm, lesions, px_per_mm)


# Exces de rouge exige quand la lesion est aussi plus sombre que la peau
# voisine. Le seuil ordinaire (1,8) frole le bruit de fond d'une peau normale ;
# on demande ici une marge nette au-dessus.
RED_IF_DARK = 4.5


def _classify(red: float, dark: float, yellow: float, core_l: float,
              core_s: float, skin_s: float, r_px: float, px_per_mm: float,
              src: str):
    """Attribue un type a une lesion d'apres sa signature colorimetrique."""
    d_mm = 2.0 * r_px / px_per_mm

    # Pustule : halo rouge + coeur clair nettement desature
    if red > 1.6 and core_l > 0.8 and core_s < skin_s * 0.82:
        return "pustule"
    # Papule : le niveau de preuve exige depend de l'obscurite.
    #
    # L'ancienne regle imposait `dark > -1.2`, en supposant qu'une lesion en
    # relief ne peut pas etre plus sombre que la peau voisine. C'est faux : une
    # papule inflammatoire est erythemateuse ET plus foncee, d'autant plus sur
    # peau mate. Une lesion franchement rouge et franchement sombre ne
    # correspondait alors a AUCUNE regle et disparaissait du rapport.
    #
    # Mais lever la condition sans rien mettre a la place ne marche pas non
    # plus : les ombres legerement rosees passent en masse. C'est ce que la
    # garde faisait de utile, et le banc d'essai l'a montre — le rappel montait
    # de 3 a 27 % pendant que les faux positifs passaient de 4 a 49.
    #
    # Une tache sombre doit donc apporter DAVANTAGE de preuve coloree qu'une
    # tache en relief : c'est la seule facon de distinguer une lesion d'une
    # ombre, puisque l'obscurite seule est ambigue.
    if d_mm >= 1.2 and (
        (dark > -1.2 and red > 1.8) or (dark <= -1.2 and red > RED_IF_DARK)
    ):
        return "papule"
    # Comedon ouvert : petit, sombre, ET BRUN.
    #
    # L'exigence de chroma est ce qui separe une lesion d'un poil. Un comedon
    # ouvert est du sebum oxyde : il tire vers le brun, donc b* positif. Un
    # poil, une ombre ou un debut de barbe sont sombres et NEUTRES. Sans cette
    # condition, la regle "sombre et peu rouge" decrivait exactement un poil —
    # d'ou des comedons rapportes entre les sourcils, ou il n'y a que l'ombre
    # inter-sourciliere et quelques poils epars.
    if dark < -1.5 and red < 1.6 and d_mm <= 2.2 and yellow > 0.35:
        # Un noyau tres desature par rapport a la peau environnante reste un
        # poil, meme legerement chaud.
        if core_s < skin_s * 0.55:
            return None
        return "comedon"
    # Marque post-inflammatoire rouge (erythemateuse) : plate et etendue
    if red > 1.2 and abs(dark) < 1.0 and d_mm > 1.8:
        return "marque_rouge"
    # Marque post-inflammatoire brune : sombre, jaune-brun, peu rouge
    if dark < -1.0 and yellow > 0.5 and red < 1.2:
        return "marque_brune"
    return None


def _confidence(ltype: str, red: float, dark: float, core_l: float,
                area: float, a_min: int, a_max: int) -> float:
    """Confiance heuristique : force du signal x plausibilite de la taille."""
    if ltype in ("papule", "pustule"):
        signal = min(1.0, red / 6.0)
    elif ltype == "comedon":
        signal = min(1.0, abs(dark) / 6.0)
    else:
        signal = min(1.0, max(red, abs(dark)) / 5.0)
    mid = (a_min + a_max) / 2.0
    size_fit = 1.0 - min(1.0, abs(area - mid) / max(1.0, mid))
    return float(max(0.30, min(0.97, 0.42 + 0.42 * signal + 0.16 * size_fit)))


def _build_report(fm: FaceMap, lesions: List[Lesion],
                  px_per_mm: float) -> LesionReport:
    counts = {t: 0 for t in LESION_TYPES}
    per_zone: Dict[str, Dict[str, int]] = {}
    for l in lesions:
        counts[l.type] = counts.get(l.type, 0) + 1
        per_zone.setdefault(l.zone, {t: 0 for t in LESION_TYPES})
        per_zone[l.zone][l.type] += 1

    # Densite surfacique, en lesions par cm2 : comparable d'une photo a l'autre
    density: Dict[str, float] = {}
    px_per_cm2 = (px_per_mm * 10.0) ** 2
    for name, z in fm.zones.items():
        if not z.available or z.area_px <= 0:
            continue
        n = sum(per_zone.get(name, {}).values())
        density[name] = float(n / max(1e-6, z.area_px / px_per_cm2))

    # --- Severite facon GAGS ----------------------------------------------
    # GAGS = somme sur les regions de (poids de region x grade de la region),
    # le grade valant 0 (rien), 1 (comedons), 2 (papules), 3 (pustules),
    # 4 (nodules). On module par la densite pour separer "quelques papules"
    # de "joue entierement couverte".
    gags = 0.0
    for name, z in fm.zones.items():
        if not z.available:
            continue
        zc = per_zone.get(name)
        if not zc:
            continue
        if zc["pustule"] > 0:
            grade = 3.0
        elif zc["papule"] > 0:
            grade = 2.0
        elif zc["comedon"] > 0:
            grade = 1.0
        else:
            grade = 0.0
        if grade > 0:
            d = density.get(name, 0.0)
            grade = min(4.0, grade + min(1.0, d / 2.5))
        gags += ZONE_WEIGHT.get(name, 1.0) * grade

    level, label = _severity(gags)

    inflam = counts["papule"] + counts["pustule"]
    total_active = inflam + counts["comedon"]
    inflam_ratio = float(inflam / total_active) if total_active else 0.0

    dominant = sorted(density.items(), key=lambda kv: -kv[1])[:3]
    dominant_zones = [n for n, d in dominant if d > 0.15]

    # Repartition mandibulaire : evocatrice d'une composante hormonale
    jaw = sum(density.get(z, 0.0) for z in ("machoire_g", "machoire_d", "menton"))
    upper = sum(density.get(z, 0.0) for z in ("front", "nez", "glabelle"))
    hormonal = bool(jaw > 0.4 and jaw > upper * 1.8)

    return LesionReport(
        lesions=lesions, counts=counts, per_zone=per_zone, density=density,
        gags_score=float(gags), severity_level=level, severity_label=label,
        inflammatory_ratio=inflam_ratio, dominant_zones=dominant_zones,
        hormonal_pattern=hormonal,
    )


def _severity(gags: float):
    """Bornes calquees sur les paliers usuels du GAGS (leger / moyen / severe)."""
    for thr, level, label in C.GAGS_BANDS:
        if gags < thr:
            return level, label
    return 4, "acne_tres_severe"
