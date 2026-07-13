# SKYN — Analyse de peau par IA

Application mobile/web : scan du visage en 3 prises guidées (face + profils),
analyse par modèles entraînés (détection de lésions YOLOv8 fine-tuné, grade
clinique d'acné et type de peau par ViT), routine de produits personnalisée
avec images et liens.

- **Frontend** : Expo / React Native (export web servi par le backend)
- **Backend** : FastAPI + moteur `skyn_engine` (MediaPipe, OpenCV, torch CPU)
- **En ligne** : https://mezouarhamza3--skyn.modal.run

## Installer sur un nouveau PC

Prérequis : [Git](https://git-scm.com), [Node.js 20+](https://nodejs.org),
[Python 3.11](https://www.python.org/downloads/release/python-3110/).

```bash
git clone https://github.com/hmzr944/SKYN.git
cd SKYN
```

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate sur Mac/Linux)
pip install -r requirements.local.txt
pip install -r requirements.ml.txt
python scripts/download_models.py  # ~700 Mo : les 2 ViT (le YOLO fine-tuné est déjà dans le dépôt)
```

### Frontend

```bash
cd frontend
npm install
npx expo export --platform web     # construit l'app web dans dist/
```

### Lancer en local

Depuis `backend/`, avec le venv activé :

```bash
# Windows PowerShell :
$env:MONGO_URL="demo"; $env:SKYN_ALLOW_GUEST="1"; $env:SKYN_WEB_DIR="..\frontend\dist"
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

→ http://localhost:8000 (app complète, caméra incluse). `MONGO_URL=demo` =
base en mémoire, aucun MongoDB requis. Le bouton « Tester sans compte »
fonctionne grâce à `SKYN_ALLOW_GUEST=1`.

### Déployer sur Modal (mise à jour du site en ligne)

```bash
pip install modal
modal setup                        # se connecter au compte Modal (mezouarhamza3)
modal deploy deploy_modal.py
```

⚠️ Pièges connus sous **Windows** (rencontrés et résolus) :
- Erreur `Could not contact DNS servers` → `pip uninstall aiodns`
- Erreur `'charmap' codec` → préfixer : `$env:PYTHONIOENCODING="utf-8"; modal deploy deploy_modal.py`

Voir aussi [GUIDE_DEPLOIEMENT.md](GUIDE_DEPLOIEMENT.md).

## Ré-entraîner le détecteur d'acné

Pipeline complet dans [backend/training/](backend/training/README.md)
(dataset CC BY 4.0, préparation, fine-tuning YOLOv8, évaluation mAP,
déploiement conditionnel). Dernier run : mAP50 0,135 → **0,161** (+19 %).

## Notes

- Les poids ViT (~700 Mo) ne sont pas dans le dépôt — `download_models.py`
  les récupère. Le **YOLO fine-tuné SKYN** (`backend/skyn_engine/models/acne_yolo/acne.pt`)
  est versionné : c'est le seul artefact non reproductible.
- Auth : Supabase (Google OAuth) — ajouter chaque nouvelle URL dans
  Authentication → URL Configuration → Redirect URLs (`…/auth/callback`).
- SKYN est un outil de conseil cosmétique, pas un dispositif médical.
