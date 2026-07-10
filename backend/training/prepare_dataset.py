"""Prépare le dataset d'entraînement SKYN à partir de l'export Roboflow brut.

Source : datasets/_raw_acne/Pimples-detection-14 (KhaMinh/my-acne-dataset,
Roboflow "Pimples detection" v14, licence CC BY 4.0 — 10 classes de lésions).

Transformations :
1. Remap mono-classe — toutes les lésions → classe 0 "acne" (aligné sur le
   modèle du moteur ; plus robuste qu'un multi-classes déséquilibré).
2. Échantillonnage reproductible (seed fixe) pour tenir sur un CPU modeste.
3. Écrit datasets/skyn_acne/{train,val}/{images,labels} + training/data.yaml.

Usage :  python training/prepare_dataset.py [--train-n 1200] [--val-n 300]
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
RAW = BACKEND / "datasets" / "_raw_acne" / "Pimples-detection-14"
OUT = BACKEND / "datasets" / "skyn_acne"
DATA_YAML = BACKEND / "training" / "data.yaml"


def remap_label(src: Path, dst: Path) -> int:
    """Rewrite a YOLO label file with every class id forced to 0. Returns #boxes."""
    lines_out = []
    for line in src.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) >= 5:
            lines_out.append(" ".join(["0"] + parts[1:]))
    dst.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))
    return len(lines_out)


def collect(split_dir: Path) -> list[Path]:
    imgs = sorted((split_dir / "images").glob("*.jpg")) + sorted((split_dir / "images").glob("*.png"))
    # Keep only images that have a non-empty label file
    keep = []
    for img in imgs:
        lbl = split_dir / "labels" / (img.stem + ".txt")
        if lbl.exists() and lbl.stat().st_size > 0:
            keep.append(img)
    return keep


def build_split(pairs: list[Path], src_split: Path, out_split: Path, n: int, seed: int = 42) -> tuple[int, int]:
    random.Random(seed).shuffle(pairs)
    chosen = pairs[: n if n > 0 else len(pairs)]
    (out_split / "images").mkdir(parents=True, exist_ok=True)
    (out_split / "labels").mkdir(parents=True, exist_ok=True)
    boxes = 0
    for img in chosen:
        shutil.copy2(img, out_split / "images" / img.name)
        lbl = src_split / "labels" / (img.stem + ".txt")
        boxes += remap_label(lbl, out_split / "labels" / (img.stem + ".txt"))
    return len(chosen), boxes


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--train-n", type=int, default=1200, help="images d'entraînement (0 = toutes)")
    p.add_argument("--val-n", type=int, default=300, help="images de validation (0 = toutes)")
    args = p.parse_args()

    if not RAW.exists():
        raise SystemExit(f"Dataset brut introuvable : {RAW}\n"
                         "Lancez d'abord le téléchargement HuggingFace (voir README).")

    if OUT.exists():
        shutil.rmtree(OUT)

    n_tr, b_tr = build_split(collect(RAW / "train"), RAW / "train", OUT / "train", args.train_n)
    # Roboflow v14 : split "valid"
    n_va, b_va = build_split(collect(RAW / "valid"), RAW / "valid", OUT / "val", args.val_n)

    DATA_YAML.write_text(
        f"# Généré par prepare_dataset.py — mono-classe 'acne'\n"
        f"# Source : Roboflow 'Pimples detection' v14 (CC BY 4.0)\n"
        f"path: {OUT.as_posix()}\n"
        f"train: train/images\n"
        f"val: val/images\n\n"
        f"names:\n  0: acne\n",
        encoding="utf-8",
    )
    print(f"train : {n_tr} images / {b_tr} boîtes")
    print(f"val   : {n_va} images / {b_va} boîtes")
    print(f"config: {DATA_YAML}")


if __name__ == "__main__":
    main()
