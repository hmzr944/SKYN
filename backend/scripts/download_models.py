"""Download the SKYN Engine v2 ML models into skyn_engine/models/.

Models (all public, Hugging Face):
1. Tinny-Robot/acne                      — YOLOv8 acne detection (52 MB)
2. imfarzanansari/skintelligent-acne     — ViT acne severity, 5 levels (~350 MB)
3. dima806/skin_types_image_detection    — ViT skin type dry/normal/oily (~350 MB)

Usage:  python scripts/download_models.py
Safe to re-run: existing files are skipped.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "skyn_engine" / "models"

FILES = {
    # target relative path -> HF resolve URL
    "acne_yolo/acne.pt":
        "https://huggingface.co/Tinny-Robot/acne/resolve/main/acne.pt",
    "acne_severity/config.json":
        "https://huggingface.co/imfarzanansari/skintelligent-acne/resolve/main/config.json",
    "acne_severity/model.safetensors":
        "https://huggingface.co/imfarzanansari/skintelligent-acne/resolve/main/model.safetensors",
    "acne_severity/preprocessor_config.json":
        "https://huggingface.co/imfarzanansari/skintelligent-acne/resolve/main/preprocessor_config.json",
    "skin_type/config.json":
        "https://huggingface.co/dima806/skin_types_image_detection/resolve/main/config.json",
    "skin_type/model.safetensors":
        "https://huggingface.co/dima806/skin_types_image_detection/resolve/main/model.safetensors",
    "skin_type/preprocessor_config.json":
        "https://huggingface.co/dima806/skin_types_image_detection/resolve/main/preprocessor_config.json",
}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.relative_to(BASE)} (déjà présent)")
        return
    print(f"  [get ] {dest.relative_to(BASE)} ...")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "skyn-engine/2.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.rename(dest)
    print(f"         ok ({dest.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    print(f"Téléchargement des modèles vers {BASE}")
    failed = []
    for rel, url in FILES.items():
        try:
            download(url, BASE / rel)
        except Exception as e:
            failed.append((rel, str(e)))
            print(f"  [FAIL] {rel}: {e}")
    if failed:
        print(f"\n{len(failed)} échec(s) — relancez le script.")
        return 1
    print("\nTous les modèles sont en place. SKYN Engine v2 est prêt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
