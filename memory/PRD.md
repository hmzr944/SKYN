# SKYN — PRD

## Vision
Luxury editorial AI skin-analysis app (Expo React Native + FastAPI). Strict bicolor (#0D0D0D / #E8D5C0), Playfair Display + DM Sans, fluid reanimated motion, expo-haptics. All inter-screen transitions: fade 400ms.

## Stack
- **Frontend**: Expo Router, React Native, react-native-svg, react-native-reanimated, expo-haptics, expo-camera, expo-image-picker, expo-apple-authentication
- **Backend**: FastAPI + MongoDB (sessions, profile, reports), Emergent OAuth for Google, native Apple Sign-In
- **SKYN Engine** (NEW, Phase 1): MediaPipe Face Mesh + OpenCV (Sobel/Laplacian/LAB) + classical DoG blob detection + deterministic expert system with modular French templates. Endpoint: `POST /api/analyze`. ~185ms per scan. See `/app/memory/SKYN_ENGINE.md` for full architecture + Phase 2 (on-device) migration plan.
- **Legacy**: `/api/recommendations` still available via GPT-4o Vision for fallback / experimentation. Default flow uses SKYN Engine.

## User flow
1. Auth — single CTA "Se connecter via Google / Apple" → bottom sheet → Google (Emergent) or Apple (iOS native).
2. Profile setup — 3 swipeable questions: tranche d'âge, environnement, priorité.
3. Dashboard — "Bonjour, {prénom}." + date, SVG line chart on 4 derniers scans, historique, CTA "Initier un nouveau Scan".
4. Camera — fullscreen + dashed oval contour + subtle grain overlay + low-light banner + galerie import + base64 capture stored locally.
5. Analysis — 7s cinematic: 0–2s surface scan + continuous haptic, 2–4s mapping zones T/U, 4–6s micro-patterns (real SVG circles at SKYN Engine coordinates, haptics on each), 6–7s génération + écran noir 0.5s. `/api/analyze` runs in parallel.
6. Report — animated SVG score ring (0→value), italic diagnosis line, asymmetric 3-metric grid (Texture/Éclat/Imperfections), recommendations bottom sheet, "Terminer et Sauvegarder" returns to dashboard with chart updated.

## Backend endpoints (`/api`)
- POST `/auth/google/session`, POST `/auth/apple/session`, GET `/auth/me`, POST `/auth/logout`
- GET/PUT `/profile` (age_range / environment / priority / onboarded)
- GET/POST `/reports`, GET `/reports/{id}` — texture/radiance/imperfections/global_score/recommendations + optional diagnosis + detections
- **POST `/analyze`** — SKYN Engine v1, returns scores + diagnosis + 3 recos + normalized detection coordinates (~185ms)
- POST `/recommendations` (legacy) — GPT-4o Vision text-only

## Edge cases
- Low-light banner in camera screen
- Offline queue via AsyncStorage (`skyn_pending_reports`) + silent sync on next dashboard load
- SKYN Engine fallback path : if face not detected or pipeline fails, scores + recommendations still returned (template-only, profile-based)

## Smart business enhancement
SKYN Engine processes locally on backend (no LLM cost), giving sub-second analysis. Freemium SKYN Atelier subscription unlocks: unlimited bilans, comparative trend insights, PDF routine export, and (future) face-aging projection — all impossible to deliver at this cost with LLM-based analysis.

## Phase 2 roadmap (on-device, requires EAS Build)
1. Replace `skyn_engine/preprocessing.py` ↔ `react-native-mediapipe` frame processor
2. Replace CV filters ↔ Swift/Kotlin native modules or `react-native-fast-opencv`
3. Drop a `.tflite` dermatology model into `skyn_engine/models/` (e.g. MobileNetV3 fine-tuned on Fitzpatrick 17k)
4. Port `expert_system.py` → TypeScript (~200 lines, pure logic)
5. Replace `api.analyze()` → local `analyzeSkin()`. Photo never leaves the device → "Luxe Confidentialité Totale" marketing claim.

Full details in `/app/memory/SKYN_ENGINE.md`.
