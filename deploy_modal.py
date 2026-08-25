"""Deploiement SKYN sur Modal.com — API + application web, serverless.

Modal ne facture que les secondes d'utilisation reelle : l'app peut rester
accessible depuis un telephone sans qu'aucune machine tourne en permanence.

Prerequis (une fois) :
    cd frontend && npx expo export --platform web && cd ..
    pip install modal
    modal setup

Deploiement / mise a jour :
    modal deploy deploy_modal.py

L'URL affichee a la fin est celle a ouvrir sur le telephone.

NOTE SUR LES DEPENDANCES — le moteur v2 fait de la vision classique :
MediaPipe pour les 468 reperes du visage, OpenCV et SciPy pour la
segmentation en zones et la detection des lesions. Il n'y a ni torch ni
YOLO, donc pas de modele a telecharger au build. L'image est d'autant plus
legere et le demarrage a froid d'autant plus court.
"""
from pathlib import Path

import modal

HERE = Path(__file__).parent

image = (
    modal.Image.debian_slim(python_version="3.11")
    # MediaPipe et OpenCV ont besoin de ces bibliotheques systeme.
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install_from_requirements(str(HERE / "backend" / "requirements.local.txt"))
    .env(
        {
            "SKYN_WEB_DIR": "/app/webapp",
            # Demo sans compte : indispensable pour tester depuis un telephone
            # sans passer par la creation d'un compte Supabase.
            "SKYN_ALLOW_GUEST": "1",
            # L'app peut etre servie depuis GitHub Pages : le conteneur n'est
            # alors reveille que par les appels d'analyse.
            "CORS_ORIGINS": "https://hmzr944.github.io,http://localhost:8081,http://localhost:19006",
        }
    )
    # Code backend monte au demarrage : les redeploiements sont instantanes.
    .add_local_dir(
        str(HERE / "backend"),
        "/app",
        ignore=[
            "**/.venv/**",
            "**/datasets/**",
            "**/__pycache__/**",
            "**/*.log",
            "**/tests/**",
        ],
    )
    # Application web construite localement (npx expo export --platform web).
    .add_local_dir(str(HERE / "frontend" / "dist"), "/app/webapp")
)

app = modal.App("skyn")


@app.function(
    image=image,
    cpu=2.0,
    # MediaPipe charge son maillage facial en memoire ; 2 Go suffisent
    # largement sans torch.
    memory=2048,
    # COUT — c'est ce reglage qui domine la facture, pas le calcul.
    #
    # A 900 s, une visite de dix secondes faisait facturer quinze minutes de
    # 2 vCPU et 2 Go. L'essentiel du quota partait en attente, pas en analyse.
    # A 60 s on garde le benefice du conteneur chaud pendant qu'on navigue,
    # et on cesse de payer un quart d'heure de vide apres chaque passage.
    scaledown_window=60,
    timeout=120,
    # La base de demo vit en memoire : avec plusieurs conteneurs, un rapport
    # cree ici serait introuvable la-bas (404).
    max_containers=1,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app(label="skyn")
def web():
    import sys

    sys.path.insert(0, "/app")
    from server import app as fastapi_app

    return fastapi_app
