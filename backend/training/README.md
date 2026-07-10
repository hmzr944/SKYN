# SKYN Engine v2 — Entraînement des modèles

Le moteur d'analyse utilise trois modèles entraînés (dossier `skyn_engine/models/`,
téléchargés par `python scripts/download_models.py`) :

| Modèle | Rôle | Architecture | Source initiale |
|---|---|---|---|
| `acne_yolo/acne.pt` | Détection localisée des lésions (boîtes + confiance) | YOLOv8 | [Tinny-Robot/acne](https://huggingface.co/Tinny-Robot/acne) |
| `acne_severity/` | Grade clinique de l'acné (niveau −1 à 3) | ViT-base | [imfarzanansari/skintelligent-acne](https://huggingface.co/imfarzanansari/skintelligent-acne) |
| `skin_type/` | Type de peau (sèche / normale / grasse) | ViT-base | [dima806/skin_types_image_detection](https://huggingface.co/dima806/skin_types_image_detection) |

Si un modèle est absent, le moteur bascule automatiquement sur l'analyse CV
classique (v1) — l'application ne casse jamais.

## Améliorer le détecteur d'acné (fine-tuning)

### 1. Obtenir un dataset annoté

Dataset utilisé pour le premier fine-tuning SKYN (2026-07) :
[KhaMinh/my-acne-dataset](https://huggingface.co/datasets/KhaMinh/my-acne-dataset)
— miroir HuggingFace du Roboflow « Pimples detection » v14, ~4 600 images,
10 types de lésions, **licence CC BY 4.0** (mentionnez la source).

```bash
cd backend
.venv/Scripts/python -c "from huggingface_hub import snapshot_download; \
  snapshot_download(repo_id='KhaMinh/my-acne-dataset', repo_type='dataset', local_dir='datasets/_raw_acne')"
python training/prepare_dataset.py           # remap mono-classe + data.yaml
```

Autres sources : **ACNE04** (~1 450 images, référence académique) et
**Roboflow Universe** (exports au format YOLOv8) :
https://universe.roboflow.com/search?q=acne — placez-les au format YOLO puis
adaptez `data.yaml` (voir `data.example.yaml`).

### 2. Entraîner

```bash
cd backend
# GPU / machine puissante :
python training/train_acne_yolo.py --data training/data.yaml --epochs 60
# CPU modeste (backbone gelé, images réduites) :
python training/train_acne_yolo.py --data training/data.yaml --epochs 12 --imgsz 480 --batch 8 --freeze 10
```

Le script part des poids actuels du moteur (transfert d'apprentissage), applique
des augmentations adaptées aux selfies (rotations légères, variations de
luminosité, symétrie horizontale) et s'arrête tôt si la validation stagne.

### 3. Évaluer puis déployer

Le script affiche `mAP50` et `mAP50-95` en fin d'entraînement. Si le nouveau
modèle fait mieux que l'ancien :

```bash
python training/train_acne_yolo.py --deploy runs/detect/skyn_acne/weights/best.pt
```

L'ancien modèle est sauvegardé en `.bak`. Redémarrez le backend, le moteur
charge les nouveaux poids sans modification de code. Le champ `source` de
l'API passe à `skyn_engine_v2` quand les modèles ML sont actifs.

## Limites et honnêteté scientifique

Une détection « parfaite » n'existe pas, même chez un dermatologue. Les axes qui
rapprochent le plus d'une fiabilité clinique :
1. **Plus de données annotées, plus variées** (types de peau, éclairages,
   appareils) — c'est le levier n°1, loin devant l'architecture.
2. **Qualité de prise de vue contrôlée** — le check basse lumière existe déjà
   côté app ; ajouter distance/netteté aiderait.
3. **Validation régulière** — gardez un jeu de test fixe et comparez chaque
   nouveau modèle dessus avant de déployer.

L'application reste un outil cosmétique de conseil, pas un dispositif médical :
ne présentez jamais les résultats comme un diagnostic dermatologique.
