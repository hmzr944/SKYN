"""Déploiement SKYN sur Modal.com — backend ML + application web, serverless.

Modal offre $30/mois de crédits gratuits (sans carte bancaire) et ne facture
que les secondes d'utilisation réelle : parfait pour une démo accessible depuis
un téléphone, PC éteint.

Prérequis (une fois) :
    cd frontend && npx expo export --platform web && cd ..   # build de l'app web
    pip install modal
    modal setup                    # ouvre le navigateur pour se connecter

Déploiement / mise à jour :
    modal deploy deploy_modal.py

L'URL affichée à la fin (https://VOTRE-PSEUDO--skyn.modal.run) est celle à
ouvrir sur le téléphone.
"""
from pathlib import Path

import modal

HERE = Path(__file__).parent
FINETUNED_ACNE = HERE / "backend" / "skyn_engine" / "models" / "acne_yolo" / "acne.pt"

# Image construite nativement par Modal (pas de Dockerfile multi-étages) :
# dépendances Python + téléchargement des modèles au build, dans /models.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install_from_requirements(str(HERE / "backend" / "requirements.local.txt"))
    .pip_install_from_requirements(str(HERE / "backend" / "requirements.ml.txt"))
    .env({
        "SKYN_MODELS_DIR": "/models",
        "SKYN_WEB_DIR": "/app/webapp",
        "SKYN_ALLOW_GUEST": "1",  # mode démo "Tester sans compte"
    })
    .add_local_file(str(HERE / "backend" / "scripts" / "download_models.py"),
                    "/tmp/download_models.py", copy=True)
    .run_commands("python /tmp/download_models.py")
    # Code backend monté au démarrage (redéploiements instantanés)
    .add_local_dir(str(HERE / "backend"), "/app", ignore=[
        "**/.venv/**", "**/datasets/**", "**/__pycache__/**",
        "**/skyn_engine/models/**", "**/*.log", "**/tests/**",
    ])
    # Application web construite localement (npx expo export --platform web)
    .add_local_dir(str(HERE / "frontend" / "dist"), "/app/webapp")
)

# Le YOLO fine-tuné local remplace le modèle de base téléchargé au build
if FINETUNED_ACNE.exists():
    image = image.add_local_file(str(FINETUNED_ACNE), "/models/acne_yolo/acne.pt")

app = modal.App("skyn")


@app.function(
    image=image,
    cpu=2.0,
    memory=3072,           # les 3 modèles (torch CPU) tiennent dans ~2,5 Go
    scaledown_window=900,  # reste chaud 15 min après la dernière visite
    timeout=120,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app(label="skyn")
def web():
    import sys
    sys.path.insert(0, "/app")
    from server import app as fastapi_app
    return fastapi_app
