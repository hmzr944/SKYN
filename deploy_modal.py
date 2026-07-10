"""Déploiement SKYN sur Modal.com — backend ML + application web, serverless.

Modal offre $30/mois de crédits gratuits (sans carte bancaire) et ne facture
que les secondes d'utilisation réelle : parfait pour une démo accessible depuis
un téléphone, PC éteint.

Déploiement (une seule fois) :
    pip install modal
    modal setup                    # ouvre le navigateur pour se connecter
    modal deploy deploy_modal.py   # construit l'image (~20 min la 1re fois)

L'URL affichée à la fin (https://VOTRE-PSEUDO--skyn.modal.run) est celle à
ouvrir sur le téléphone. Mise à jour : relancez simplement `modal deploy`.
"""
import modal

# Réutilise le Dockerfile racine (build web Expo + backend + modèles ML)
image = modal.Image.from_dockerfile("Dockerfile")

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
