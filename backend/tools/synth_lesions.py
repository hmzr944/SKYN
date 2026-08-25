"""Banc d'essai du moteur : des lesions posees a des endroits connus.

Le probleme, jusqu'ici, etait qu'on ne pouvait rien mesurer. On voyait un
compte total et on ne savait pas s'il correspondait a quoi que ce soit. Sans
verite terrain, "ameliorer le moteur" revenait a deplacer des seuils jusqu'a
ce que le chiffre plaise — c'est-a-dire a surajuster sur une photo.

Le principe retenu : partir d'un VRAI visage, pour que la detection de repere
fonctionne normalement, et y peindre des lesions synthetiques a des positions
definies PAR CES REPERES. On connait alors exactement ou elles sont, et on
peut demander au moteur s'il les retrouve, et dans la bonne zone.

Ce que ce banc mesure honnêtement :
  * le rappel — combien de lesions posees sont retrouvees ;
  * la justesse de zone — sont-elles attribuees a la bonne region ;
  * les faux positifs — combien de lesions rapportees sur un visage vierge.

Ce qu'il NE mesure pas : la fidelite a de vraies lesions. Une lesion peinte est
une modulation lisse de la couleur locale ; une vraie a du relief, un halo, une
texture, parfois un centre purulent. Ce banc valide la geometrie et
l'attribution de zone, pas la reconnaissance clinique. Il faut des images
annotees pour ça, et ce banc ne les remplace pas.
"""
from __future__ import annotations

import argparse
import base64
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skyn_engine.v2.pipeline import analyze_face  # noqa: E402
from backend.skyn_engine.v2.zones import ZONE_LANDMARKS  # noqa: E402


# Amplitude de la modulation, en unites LAB (0-255 pour L, centre 128 pour a/b).
# Une papule inflammatoire est nettement plus rouge, un peu plus sombre, et sa
# teinte jaune bouge a peine.
D_ROUGE = 16.0
D_LUM = 7.0
D_JAUNE = 1.0


@dataclass
class Planted:
    """Une lesion posee, et l'endroit ou on l'a mise."""

    zone: str
    x: int
    y: int
    radius: int


def _landmarks(img: np.ndarray) -> np.ndarray | None:
    """Repere les 468 points du visage, en coordonnees pixel."""
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True
    ) as mesh:
        res = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not res.multi_face_landmarks:
        return None
    h, w = img.shape[:2]
    return np.array(
        [(p.x * w, p.y * h) for p in res.multi_face_landmarks[0].landmark],
        dtype=np.float32,
    )


def plant(
    img: np.ndarray,
    pts: np.ndarray,
    zone: str,
    n: int,
    seed: int = 0,
) -> Tuple[np.ndarray, List[Planted]]:
    """Peint `n` lesions inflammatoires dans la zone demandee.

    Les positions sont tirees a l'interieur du polygone de la zone, avec une
    marge : une lesion collee au bord serait attribuable a la zone voisine, et
    on ne saurait pas si une erreur vient du moteur ou de notre mise en place.
    """
    idx = ZONE_LANDMARKS.get(zone)
    if not idx:
        raise SystemExit(f"zone inconnue : {zone}")

    poly = pts[idx].astype(np.int32)
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(poly), 255)
    # Marge : on retire une bande au bord de la zone.
    face_w = float(np.ptp(pts[:, 0]))
    mask = cv2.erode(mask, np.ones((max(3, int(face_w / 40)),) * 2, np.uint8))

    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        raise SystemExit(f"zone trop petite apres marge : {zone}")

    rng = np.random.default_rng(seed)
    planted: List[Planted] = []

    # On peint en LAB, et RELATIVEMENT a la peau qui se trouve la.
    #
    # La premiere version fondait un disque d'une couleur ABSOLUE (un rouge
    # fixe) dans l'image. C'etait faux, et le banc s'est mis a mentir : sur une
    # joue claire, fondre vers un rouge sombre assombrit beaucoup et ne rougit
    # que peu — la lesion prenait la signature d'une ombre, que le moteur a
    # raison de rejeter. Mesure a l'appui : joue gauche L=156, joue droite
    # L=191, et le rappel tombait de 6/6 a 1/6 entre les deux, alors que la
    # consigne de pose etait identique.
    #
    # Une vraie lesion inflammatoire n'impose pas une couleur : elle MODULE
    # celle de la peau autour — plus rouge, un peu plus sombre, teinte jaune a
    # peu pres inchangee. C'est ce qu'on fait ici, et le meme geste vaut alors
    # sur une joue claire comme sur une joue sombre.
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)

    # Diametre plausible d'une papule : 2 a 4 mm. On l'exprime en pixels via
    # la largeur du visage, ~140 mm chez un adulte.
    px_per_mm = face_w / 140.0
    for _ in range(n):
        i = int(rng.integers(0, len(xs)))
        cx, cy = int(xs[i]), int(ys[i])
        r = max(3, int(round(rng.uniform(1.0, 2.0) * px_per_mm)))

        # Degrade : un disque a bord franc serait trop facile a detecter et
        # gonflerait le rappel.
        alpha = np.zeros(img.shape[:2], np.float32)
        cv2.circle(alpha, (cx, cy), r, 1.0, -1)
        alpha = cv2.GaussianBlur(alpha, (0, 0), r * 0.55)
        alpha = np.clip(alpha, 0, 1)

        lab[:, :, 0] -= alpha * D_LUM
        lab[:, :, 1] += alpha * D_ROUGE
        lab[:, :, 2] += alpha * D_JAUNE

        planted.append(Planted(zone=zone, x=cx, y=cy, radius=r))

    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out, planted


def _b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise SystemExit("encodage impossible")
    return base64.b64encode(buf.tobytes()).decode()


def evaluate(base: Path, zones: List[str], per_zone: int, seed: int) -> None:
    """Mesure par ZONE, pas par coordonnees.

    Le moteur rend la zone de chaque lesion : c'est donc la comparaison la plus
    directe, et elle ne depend pas d'un repere partage. Une premiere version de
    ce banc appariait par distance en pixels, en reconstruisant la boite du
    visage — sauf que le rapport ne l'expose pas. Elle mesurait donc du bruit.
    """
    from collections import Counter

    img = cv2.imread(str(base))
    if img is None:
        raise SystemExit(f"image introuvable : {base}")

    pts = _landmarks(img)
    if pts is None:
        raise SystemExit("aucun visage detecte dans l'image de base")

    ref = analyze_face(_b64(img))
    ref_zone = Counter(l["zone"] for l in ref.lesions)
    print(f"Visage de base : {len(ref.lesions)} lesions rapportees")
    print(f"  reparties : {dict(ref_zone)}\n")

    total_posees = 0
    total_gagnees = 0
    total_ailleurs = 0

    for zone in zones:
        marked, planted = plant(img, pts, zone, per_zone, seed=seed)
        rep = analyze_face(_b64(marked))
        by_zone = Counter(l["zone"] for l in rep.lesions)

        # Gagnees : lesions supplementaires rapportees DANS la zone visee.
        gagnees = max(0, by_zone[zone] - ref_zone[zone])
        # Ailleurs : lesions supplementaires apparues dans les autres zones —
        # soit une attribution erronee, soit un effet de bord de la retouche.
        ailleurs = max(0, (len(rep.lesions) - len(ref.lesions)) - gagnees)

        total_posees += len(planted)
        total_gagnees += gagnees
        total_ailleurs += ailleurs

        print(
            f"{zone:<12} posees={len(planted):>2} "
            f"detectees_dans_la_zone={gagnees:>2} "
            f"apparues_ailleurs={ailleurs:>2} "
            f"| total {len(ref.lesions)} -> {len(rep.lesions)}"
        )

    if total_posees:
        print(
            f"\nRAPPEL PAR ZONE : {total_gagnees}/{total_posees} "
            f"({100 * total_gagnees / total_posees:.0f} %)"
        )
        print(f"ATTRIBUEES AILLEURS : {total_ailleurs}")
    print(f"FAUX POSITIFS sur visage vierge : {len(ref.lesions)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", default="backend/tests/fixtures_face.jpg")
    ap.add_argument(
        "--zones",
        default="joue_g,joue_d,front,menton,nez",
        help="zones a tester, separees par des virgules",
    )
    ap.add_argument("--n", type=int, default=4, help="lesions par zone")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    evaluate(Path(a.image), [z.strip() for z in a.zones.split(",")], a.n, a.seed)


if __name__ == "__main__":
    main()
