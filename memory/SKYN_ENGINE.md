# SKYN Engine — Documentation Technique

## Architecture du Pipeline (Phase 1 — Backend Hybride)

L'analyse cutanée SKYN s'exécute en 3 étapes orchestrées dans `/app/backend/skyn_engine/`. Aujourd'hui, le pipeline tourne sur le backend FastAPI ; il est conçu dès le départ pour être migré sur l'appareil (Phase 2 — On-Device) sans changer le contrat d'API.

```
[ Photo ]
   ↓ base64
[ Étape 1 — Préprocessing ]            preprocessing.py
   • MediaPipe Face Mesh (468 landmarks)
   • Bounding box + roll angle
   • Skin mask, T-zone mask, U-zone mask
   • Luminance moyenne → flag low_light
   ↓
[ Étape 2 — Computer Vision classique ] cv_analysis.py
   • Sobel + Laplacian sur U-zone → texture
   • LAB (canal L) mean / std sur skin → radiance
   • Ratio pixels sombres → imperfections_pre
   • LAB canal a (rougeur) → redness
   ↓
[ Étape 3 — Détection d'imperfections ] imperfections.py
   • Difference of Gaussians + connected components
   • Filtrage par aire + position normalisée
   • Sortie : [{type, x, y, confidence, radius}] (drop-in pour YOLOv8 plus tard)
   ↓
[ Système Expert ]                       expert_system.py
   • Arbre de décision → diagnostic clinique
   • Templates modulaires (variables : âge, env, scores)
   • Top 3 recommandations triées par pondération
   ↓
[ AnalysisOutput ]
```

## Performance mesurée
- Image 600×600 px sur backend FastAPI : **185ms** end-to-end
- MediaPipe Face Mesh chargé à la volée (~80ms premier appel, ~30ms ensuite)
- Aucune dépendance LLM, aucun appel réseau sortant, aucun stockage de la photo

## Endpoint
```
POST /api/analyze
Authorization: Bearer <session_token>
Body: { "image_base64": "..." }
Response: AnalyzeResponse {
  detected: bool, low_light: bool, luminance: float,
  global_score, texture, radiance, imperfections: int,
  diagnosis: str,
  recommendations: [str, str, str],
  detections: [{ type, x, y, confidence, radius }],
  source: "skyn_engine_v1"
}
```

## Migration Phase 2 (On-Device)

Le contrat `AnalysisOutput` est volontairement identique à ce que produira la version embarquée. Pour migrer :

1. **Préprocessing** → remplacer `skyn_engine/preprocessing.py` par `react-native-mediapipe` (frame processor de `react-native-vision-camera`) ou un module natif WebAssembly. Sortie identique : ROI masks + bbox.
2. **CV classique** → écrire les filtres Sobel/Laplacien en Swift/Kotlin natif (10× plus rapide qu'en JS) ou via `react-native-fast-opencv`. Aucune logique métier ne change.
3. **Imperfections** → drop d'un modèle TFLite (MobileNetV3 ou YOLOv8-segmentation entraîné sur Fitzpatrick 17k) dans `skyn_engine/models/`, et remplacer le contenu de `imperfections.detect()` par un appel inférence. Sortie : même `List[Detection]`.
4. **Expert system** → portage trivial du fichier `expert_system.py` en TypeScript (logique pure, 200 lignes).
5. Suppression de l'appel réseau `/api/analyze` côté frontend, remplacé par un import local. Garde le même nom de fonction `analyze_skin(imageB64, profile)`.

⚠️ Phase 2 nécessitera un **EAS Build de développement** (incompatible avec Expo Go), un fichier `.tflite` (~5-15 MB), et 2-3 jours d'intégration.

## Garanties de confidentialité (Phase 1)
- La photo arrive en base64 dans la requête, est décodée en mémoire, analysée, jamais écrite sur disque.
- Le serveur logge uniquement les métriques numériques anonymisées (pas l'image).
- Le rapport stocké en base ne contient que les scores + recommandations + coordonnées normalisées des spots, jamais la photo.

En Phase 2, la photo ne quittera pas l'appareil — c'est l'argument marketing "Luxe Confidentialité Totale".
