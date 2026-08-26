# Photos de l'onboarding

Ce dossier accueille les images de l'onboarding. Il est vide : l'app n'en a
pas besoin pour fonctionner, le disque de la premiere page contient une
matiere dessinee tant qu'aucune photo n'est fournie.

## Ajouter une photo

1. Depose le fichier ici, par exemple `portrait.jpg`.
2. Dans `app/onboarding.tsx`, remplace :

   ```ts
   const PORTRAIT = null; // require("@/assets/onboarding/portrait.jpg")
   ```

   par :

   ```ts
   const PORTRAIT = require("@/assets/onboarding/portrait.jpg");
   ```

## Ce qu'il faut respecter

- **Cadrage carre.** Le disque recadre au centre : une photo verticale y perd
  le haut et le bas.
- **Sujet centre**, avec de l'air autour. Un visage au bord du cadre sera
  coupe par le rond.
- **1000 px de cote suffisent.** Le disque fait 196 points, soit 588 px sur un
  ecran a trois fois la densite. Au dela, on alourdit le telechargement sans
  rien gagner.
- **JPEG de qualite 80**, pas de PNG : une photo en PNG pese cinq a dix fois
  plus pour un rendu identique. Vise moins de 150 Ko.
- **Les droits.** Une photo trouvee en ligne n'est pas libre d'usage. Pour une
  app publiee sur l'App Store il faut une licence commerciale, ou une photo
  prise par toi.
