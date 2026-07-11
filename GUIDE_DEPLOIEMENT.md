# Déployer SKYN en ligne — accès depuis votre téléphone, sans PC

L'image Docker à la racine du projet contient **tout** : l'API, les 3 modèles
d'analyse, et l'application web. Une fois déployée, vous ouvrez simplement une
URL dans le navigateur de votre téléphone.

Hébergeur recommandé : **Modal.com** — $30 de crédits offerts **chaque mois**,
sans carte bancaire. Facturation à la seconde d'utilisation réelle uniquement
(l'app "s'endort" quand personne ne l'utilise) : pour une démo, les crédits
mensuels sont largement suffisants. RAM configurable (nos modèles ont besoin
de ~3 Go, ce que les hébergeurs gratuits classiques type Render/Koyeb ne
permettent pas — ils plafonnent à 512 Mo).

## Étape 1 — Compte Modal (2 min)

1. https://modal.com → **Sign up** (connexion via GitHub ou Google, gratuit,
   pas de carte bancaire).

## Étape 2 — Déployer depuis votre PC (3 commandes)

Dans un terminal, dans le dossier `SKYN-main` :

```bash
# 1. Construire l'app web (à refaire seulement si le frontend change)
cd frontend
npx expo export --platform web
cd ..

# 2. Déployer
pip install modal
modal setup            # ouvre le navigateur pour lier votre compte
modal deploy deploy_modal.py
```

Le premier déploiement télécharge les dépendances et les modèles côté Modal :
comptez **10-15 min**. Les suivants prennent quelques secondes (le code est
monté au démarrage, l'image n'est pas reconstruite).

À la fin, Modal affiche votre URL :

```
https://VOTRE-PSEUDO--skyn.modal.run
```

## Étape 3 — Autoriser l'URL dans Supabase (2 min)

Pour que la connexion fonctionne depuis cette URL :

1. https://supabase.com/dashboard → votre projet → **Authentication → URL Configuration**
2. Ajoutez dans **Redirect URLs** : `https://VOTRE-PSEUDO--skyn.modal.run/auth/callback`

## C'est tout ✅

Ouvrez l'URL sur votre téléphone : onboarding, connexion, scan (le navigateur
demande l'accès caméra — HTTPS oblige, c'est bon), analyse par les modèles
entraînés, rapport avec produits. PC éteint, ça tourne dans le cloud.

**Première visite après une pause** : l'app se réveille en ~30-60 s (chargement
des modèles). Ensuite elle reste chaude 15 min après chaque visite.

## Notes

- **Base de données** : par défaut, mode démo (base en mémoire) — comptes et
  rapports sont remis à zéro quand l'app se rendort. Pour du persistant :
  cluster gratuit sur https://www.mongodb.com/cloud/atlas (M0), puis dans
  `deploy_modal.py` ajoutez au décorateur `@app.function(...)` :
  `secrets=[modal.Secret.from_dict({"MONGO_URL": "mongodb+srv://...", "DB_NAME": "skyn"})]`
  (ou créez le secret dans le dashboard Modal et référencez-le par nom).
- **Suivi de la consommation** : dashboard Modal → Usage. Une session de démo
  coûte quelques centimes de crédit ; $30/mois ≈ 27 h de calcul actif.
- **Mise à jour de l'app** : relancez `modal deploy deploy_modal.py`.
- **Alternative 100 % statique** (si vous voulez juste montrer l'interface,
  sans analyse IA réelle) : `npx expo export --platform web` puis déposez le
  dossier `frontend/dist` sur un Space Hugging Face « Static » (gratuit) —
  mais l'analyse échouera sans backend ; la vraie démo, c'est Modal.
