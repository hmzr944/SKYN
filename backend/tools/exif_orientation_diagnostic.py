"""Diagnostic ponctuel — pas un banc, un seul cas reel (capture_005, sujet
001, hors depot : /home/user/real_skin_pilot/subject_001/).

Question posee par l'utilisateur : "le scan capte pas bien le visage" sur
cette photo precise. Avant de toucher a quoi que ce soit, verifier UNE
hypothese concrete, deja visible dans le code :

  - Les scripts de pilotage (real_skin_pilot_session_ab.py) corrigent
    l'orientation EXIF avant analyse (`ImageOps.exif_transpose`).
  - Le decodage de PRODUCTION (`skyn_engine/v2/zones.py::_decode`) ne le
    fait PAS : `cv2.imdecode` lit les pixels bruts du capteur, sans
    jamais regarder le tag EXIF Orientation.

Ce script ne modifie rien : il decode la meme image des deux façons et
compare ce que `build_face_map` en tire.
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from PIL import Image, ExifTags, ImageOps

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from skyn_engine.v2.zones import build_face_map  # noqa: E402


def _b64_from_pil(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _rapport(nom: str, image_b64: str) -> None:
    fm = build_face_map(image_b64)
    print(f"\n--- {nom} ---")
    print(f"detected        = {fm.detected}")
    if not fm.detected:
        return
    q = fm.quality
    print(f"quality.usable  = {q.usable}")
    print(f"quality.issues  = {q.issues}")
    print(f"face_ratio      = {q.face_ratio:.3f}")
    print(f"roll_deg        = {q.roll_deg:.1f}")
    print(f"yaw_proxy       = {q.yaw_proxy:.2f}")
    print(f"blur (norm)     = {q.blur:.1f}")
    print(f"exposure        = {q.exposure:.1f}")
    zones_dispo = sum(1 for z in fm.zones.values() if z.available)
    print(f"zones dispo     = {zones_dispo} / {len(fm.zones)}")


def main() -> None:
    chemin = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/home/user/real_skin_pilot/subject_001/capture_005.jpg"
    )
    raw_bytes = chemin.read_bytes()

    pil = Image.open(io.BytesIO(raw_bytes))
    orientation_tag = pil.getexif().get(274)
    print(f"Fichier : {chemin}")
    print(f"Dimensions brutes (pixels du capteur) : {pil.size}")
    print(f"Tag EXIF Orientation : {orientation_tag}")

    # 1) Exactement ce que fait la production aujourd'hui : les octets
    #    JPEG bruts, base64, decodes par cv2.imdecode — AUCUNE correction.
    image_b64_brut = base64.b64encode(raw_bytes).decode()
    _rapport("PRODUCTION (zones.py._decode tel quel, pas de correction EXIF)", image_b64_brut)

    # 2) Ce que font deja les scripts de pilotage : PIL corrige
    #    l'orientation AVANT d'encoder en JPEG.
    corrige = ImageOps.exif_transpose(pil)
    print(f"\nDimensions apres exif_transpose : {corrige.size}")
    image_b64_corrige = _b64_from_pil(corrige)
    _rapport("CORRIGE (ImageOps.exif_transpose avant decodage)", image_b64_corrige)


if __name__ == "__main__":
    main()
