"""Fine-tuning du détecteur d'acné SKYN (YOLOv8).

Entraîne à partir des poids actuels (skyn_engine/models/acne_yolo/acne.pt) ou
d'un YOLOv8 générique, sur un dataset au format YOLO (voir data.example.yaml).

Exemples :
    # Fine-tuning depuis le modèle actuel (recommandé)
    python training/train_acne_yolo.py --data training/data.yaml --epochs 60

    # Depuis zéro (YOLOv8s pré-entraîné COCO)
    python training/train_acne_yolo.py --data training/data.yaml --base yolov8s.pt

    # Après entraînement : évaluer puis déployer les nouveaux poids
    python training/train_acne_yolo.py --data training/data.yaml --deploy runs/detect/skyn_acne/weights/best.pt
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
CURRENT_WEIGHTS = BACKEND / "skyn_engine" / "models" / "acne_yolo" / "acne.pt"


def train(data: str, base: str, epochs: int, imgsz: int, batch: int, freeze: int, workers: int) -> Path:
    from ultralytics import YOLO

    model = YOLO(base)
    results = model.train(
        data=data,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        freeze=freeze or None,   # geler N couches du backbone (fine-tuning CPU)
        workers=workers,
        name="skyn_acne",
        exist_ok=True,
        # Augmentations adaptées aux photos de visage smartphone
        degrees=10.0,       # légère rotation (selfies inclinés)
        translate=0.1,
        scale=0.3,
        fliplr=0.5,         # symétrie gauche/droite du visage
        flipud=0.0,         # jamais de visage à l'envers
        hsv_h=0.01,         # teinte quasi fixe (couleur de peau = signal)
        hsv_s=0.4,
        hsv_v=0.4,          # forte variation de luminosité (éclairages variés)
        mosaic=0.5,
        patience=15,
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    print(f"\nMeilleurs poids : {best}")

    # Évaluation finale sur le split val
    metrics = model.val(data=data)
    print(f"mAP50: {metrics.box.map50:.3f} | mAP50-95: {metrics.box.map:.3f}")
    print("Comparez au modèle précédent avant de déployer (--deploy).")
    return best


def deploy(weights: str) -> None:
    src = Path(weights)
    if not src.exists():
        raise SystemExit(f"Poids introuvables : {src}")
    CURRENT_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    if CURRENT_WEIGHTS.exists():
        backup = CURRENT_WEIGHTS.with_suffix(".pt.bak")
        shutil.copy2(CURRENT_WEIGHTS, backup)
        print(f"Ancien modèle sauvegardé : {backup}")
    shutil.copy2(src, CURRENT_WEIGHTS)
    print(f"Déployé : {CURRENT_WEIGHTS}")
    print("Redémarrez le backend — le moteur charge les nouveaux poids automatiquement.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="training/data.yaml", help="Fichier dataset YOLO (yaml)")
    p.add_argument("--base", default=str(CURRENT_WEIGHTS), help="Poids de départ")
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--freeze", type=int, default=0,
                   help="Nombre de couches backbone à geler (10 recommandé sur CPU)")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--deploy", metavar="BEST_PT", help="Copier ces poids vers le moteur (pas d'entraînement)")
    args = p.parse_args()

    if args.deploy:
        deploy(args.deploy)
        return
    train(args.data, args.base, args.epochs, args.imgsz, args.batch, args.freeze, args.workers)


if __name__ == "__main__":
    main()
