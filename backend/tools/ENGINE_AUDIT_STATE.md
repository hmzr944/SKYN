# État du moteur SKYN — figé le 2026-08-31

Ce document capture la conclusion du chantier diagnostic mené sur le moteur
v2 (mono-vue puis multi-vue). Il sert de référence pour ne pas rouvrir des
questions déjà tranchées, et pour dire honnêtement ce qu'on ne sait pas
encore. Rien ici n'a modifié `lesions.py` ni `calibration.py` — ce chantier
entier est resté diagnostic.

## F0 — baseline gelée

Mesurée sur **subject_001** (12 photos réelles, plusieurs éclairages/angles,
hors dépôt), 300 lésions synthétiques plantées (`synth_lesions.py`) sur les
13 zones :

| Étape | Résultat |
|---|---|
| Détection visage | 100 % |
| Zones (disponibilité + attribution) | 98 % |
| Candidats générés | 83 % |
| **Classification** | **67 % — goulot principal** |
| **Confirmation (rappel global)** | **54 %** |
| Stabilité mono-vue (proxy perturbations) | 24,5 |

**Ne jamais présenter le 54 % comme « SKYN est précis à 54 % ».** C'est un
rappel sur banc synthétique, avec ses propres lésions plantées et ses
limites (voir `engine_loss_funnel_audit.py`) — utile pour comparer deux
versions du moteur entre elles, pas comme mesure de précision clinique.

Reproductible via `backend/tools/subject_fiche.py`.

## Ce qui a été tenté sur la classification, et fermé

1. **Recalibrage RED/DARK** (`red_dark_calibration_bench.py`) — 22
   formulations de la relation rouge/obscurité balayées (paliers, linéaire,
   ratio normalisé), sélection à tolérance zéro (aucun nouveau faux
   positif, aucune dégradation de stabilité, mesurés contre F0). **0/22
   retenue.**
2. **Garde de récupération basée sur de nouvelles features**
   (`classification_feature_exploration.py` puis `classification_guard_bench.py`)
   — `contraste_centre_bord` (d=3,07) et `dispersion_signal` (d=2,12)
   séparent fortement en théorie, dans la zone où RED_IF_DARK échoue déjà.
   Testées comme garde additive (jamais en remplacement), 18
   configurations balayées. **0/18 retenue** — le point le plus proche
   (contraste>2.5 ET dispersion>0.7) atteint Δrappel=+11,9 %, ΔFP=+2,
   Δinstabilité=0, mais échoue au critère strict sur les 2 faux positifs.

**Conclusion** : le plafond actuel n'est pas un seuil mal choisi qu'on
aurait pu corriger facilement. Toute reprise de cette branche devra partir
d'un jeu de calibration plus large, pas d'un nouveau bricolage de seuil.

## P2 — Multi-vue : candidat v1

Tracking → nettoyage (MAD) → pureté de piste → vote-gate → arrêt adaptatif
(cible 7 vues / max 9), chacun validé séparément lors du chantier
précédent (`lesion_tracking_audit.py`, `vote_gate_bench.py`,
`track_purity_gate_bench.py`, `track_clean_purity_bench.py`). Porté en
production : `skyn_engine/v2/multiview.py`, endpoint
`POST /api/analyze/guided`, mémoire persistante (`skin_memory.py`),
prototype frontend (`skin-map.tsx`, `camera-guided.tsx`, `what-changed.tsx`,
`phase-history.tsx`). Considéré comme candidat v1, pas comme vérité
définitive.

## P3 — Généralisation inter-personnes : **UNKNOWN**

Un seul sujet réel disponible pour ce chantier (subject_001). Une tentative
d'obtenir un second sujet a produit des images confirmées comme générées/
améliorées par IA par l'utilisateur lui-même — écartées, jamais utilisées
comme donnée. **On ne sait donc pas si ces chiffres se généralisent à
d'autres phototypes, niveaux de rougeur, ou sévérités d'acné.** C'est une
limite de validation explicitement non résolue, pas une hypothèse
silencieuse.

Prochaine étape quand le produit le justifiera : un protocole de
recrutement de quelques volontaires avec consentement explicite, données
toujours hors dépôt Git, jamais de données identifiantes.

## Outils construits (tous diagnostic-only, `backend/tools/`)

- `exif_orientation_diagnostic.py` — a écarté l'hypothèse EXIF comme cause
  du problème de capture initial.
- `cheek_candidate_diagnostic.py` / `cheek_candidate_diagnostic_multi.py` —
  diagnostic candidat-par-candidat de la garde RED_IF_DARK.
- `red_dark_calibration_bench.py` — benchmark formel de recalibrage.
- `engine_loss_funnel_audit.py` — entonnoir de perte, toutes zones.
- `classification_feature_exploration.py` — séparabilité de nouvelles
  features (Cohen's d).
- `classification_guard_bench.py` — test de validation de ces features
  comme garde de récupération.
- `subject_fiche.py` — la fiche par sujet (ce document en est la synthèse
  écrite).
