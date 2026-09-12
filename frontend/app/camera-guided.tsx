import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Ellipse, Path } from "react-native-svg";
import Animated, {
  useAnimatedProps,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { ScanRing } from "@/src/components/analysis/ScanRing";
import { FACE_CENTER, MARK_SCALE, ZONE_SHAPES } from "@/src/components/analysis/FaceZoneMap";
import { ease } from "@/src/animation/ease";
import { track } from "@/src/services/analytics";
import { framingOk, readDetection } from "@/src/services/faceGuide";
import { colors, palette, radius, spacing, type } from "@/src/theme";
import { facePathAt } from "@/src/theme/mark";
import type { ZoneKey } from "@/src/types/analysis";
import { useOnline } from "@/src/hooks/useOnline";
import { storage } from "@/src/utils/storage";

/**
 * Scan guide — le parcours principal (voir _layout.tsx/dashboard.tsx).
 * L'ancien scan 3 angles (camera.tsx) reste dans le code comme mode
 * secondaire, accessible depuis les reglages.
 *
 * Ce que cet ecran fait : collecte jusqu'a MAX_FRAMES vues pendant que la
 * personne tourne la tete, puis envoie tout en un seul appel a
 * /api/analyze/guided, qui decide lui-meme cote serveur combien de vues
 * etaient exploitables et quand la mesure est jugee stable.
 *
 * Le guidage automatique (MediaPipe, web uniquement) est un confort, pas
 * une condition : la capture manuelle et la galerie restent toujours
 * disponibles en repli, sur toutes les plateformes — memes filets de
 * securite que camera.tsx (voir sa note sur faceGuide.ts).
 *
 * Ce que cet ecran NE fait PAS : verifier que les vues captees sont
 * reellement des poses differentes. Le texte de guidage propose un
 * mouvement (gauche/centre/droite), mais rien ici ne confirme que la tete a
 * suivi — c'est exactement la limite documentee dans
 * skyn_engine.v2.multiview (STATUT_PAR_RAISON) : CAPTURE_TOO_SIMILAR
 * n'existe pas encore. Les `view_diagnostics` (yaw/roll par vue, renvoyes
 * par le serveur) sont conserves dans l'evenement `guided_scan_completed`
 * pour verifier ensuite, sur de vrais scans, si les vues envoyees etaient
 * effectivement variees.
 */

const cleanB64 = (b?: string | null) =>
  b ? (b.startsWith("data:") ? b.split(",")[1] ?? "" : b) : "";

/** Doit rester coherent avec les valeurs par defaut de /api/analyze/guided
 * (backend/skyn_engine/v2/multiview.py::ScanConfig). */
const MIN_FRAMES = 5;
const MAX_FRAMES = 9;

/** Cadence de capture automatique (web) quand le cadrage est bon. Plus lent
 * que le guidage 3-angles : ici on vise plusieurs vues d'affilee, pas une
 * seule par angle tenu. */
const CAPTURE_INTERVAL_MS = 700;

/** Simple suite d'instructions affichees a chaque nouvelle vue — ne verifie
 * pas que la tete suit reellement (voir la note en tete de fichier). */
const GUIDE_SEQUENCE = [
  "Regardez la caméra",
  "Tournez doucement vers la gauche",
  "Continuez",
  "Revenez au centre",
  "Tournez doucement vers la droite",
  "Continuez",
  "Revenez au centre",
  "Encore un peu",
  "Presque terminé",
];

/** Ordre de révélation des zones pendant la capture — suit le même geste
 * que GUIDE_SEQUENCE (centre, puis gauche, puis droite), pour que la carte
 * qui se construit corresponde à ce qu'on demande de faire. Ce n'est PAS
 * une détection reelle par zone (aucune n'existe pendant la capture) —
 * uniquement une couverture : "cette zone du visage a été montrée",
 * jamais "un bouton a été vu ici". Voir l'avertissement en tête de fichier
 * sur ce que cet écran ne vérifie pas encore. */
const ZONE_REVEAL_ORDER: ZoneKey[] = [
  "front", "nez", "glabelle",
  "tempe_g", "joue_g", "machoire_g",
  "tempe_d", "joue_d", "machoire_d",
  "sous_yeux_g", "sous_yeux_d", "peri_oral", "menton",
];

const AnimatedEllipse = Animated.createAnimatedComponent(Ellipse);

/** Une zone qui se couvre — se dessine, ne surgit pas d'un bloc (même
 * grammaire que ZoneEllipse dans FaceZoneMap.tsx). */
function CoverageZone({ cx, cy, rx, ry }: { cx: number; cy: number; rx: number; ry: number }) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withTiming(1, { duration: 700, easing: ease.out });
  }, [t]);
  const props = useAnimatedProps(() => ({ opacity: 0.22 * t.value }));
  return (
    <AnimatedEllipse cx={cx} cy={cy} rx={rx} ry={ry} fill={colors.accent} animatedProps={props} />
  );
}

export default function CameraGuidedScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // useWindowDimensions plutot que Dimensions.get() au niveau module : cette
  // derniere se figeait a la taille mesuree au premier chargement du bundle,
  // pas a celle de l'ecran au moment ou cette camera s'ouvre reellement.
  const { width: WIN_W, height: WIN_H } = useWindowDimensions();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const online = useOnline();

  const [count, setCount] = useState(0);
  const capturesRef = useRef<string[]>([]);
  const busyRef = useRef(false);
  const doneRef = useRef(false);
  const lastCaptureRef = useRef(0);
  const startedAtRef = useRef(0);

  const canUseCamera = !!permission?.granted;

  useEffect(() => {
    startedAtRef.current = Date.now();
    track("guided_scan_started");
  }, []);

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  const finish = useCallback(async () => {
    if (doneRef.current) return;
    doneRef.current = true;
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    await storage.setItem("skyn_guided_captures", JSON.stringify(capturesRef.current));
    await storage.setItem(
      "skyn_guided_capture_ms",
      String(Date.now() - startedAtRef.current),
    );
    router.replace("/analysis-guided");
  }, [router]);

  const capture = useCallback(async () => {
    if (busyRef.current || doneRef.current) return;
    if (capturesRef.current.length >= MAX_FRAMES) return;
    busyRef.current = true;
    try {
      const photo = await cameraRef.current?.takePictureAsync({
        base64: true,
        quality: 0.55,
        skipProcessing: true,
      });
      const clean = cleanB64(photo?.base64 ?? null);
      if (clean) {
        capturesRef.current.push(clean);
        setCount(capturesRef.current.length);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        if (capturesRef.current.length >= MAX_FRAMES) await finish();
      }
    } catch {
      /* on retentera a l'image suivante */
    } finally {
      busyRef.current = false;
    }
  }, [finish]);

  /**
   * Repli si la camera en direct ne mene nulle part (guidage automatique en
   * echec sur web, ou simplement une preference) : selectionner plusieurs
   * photos depuis la galerie plutot que de rester bloque sur cet ecran.
   */
  const pickFromGallery = useCallback(async () => {
    if (doneRef.current) return;
    try {
      const remaining = MAX_FRAMES - capturesRef.current.length;
      if (remaining <= 0) return;
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        base64: true,
        quality: 0.55,
        allowsMultipleSelection: true,
        selectionLimit: remaining,
      });
      if (res.canceled) return;
      for (const asset of res.assets ?? []) {
        if (capturesRef.current.length >= MAX_FRAMES) break;
        const clean = cleanB64(asset.base64 ?? null);
        if (clean) capturesRef.current.push(clean);
      }
      setCount(capturesRef.current.length);
      if (capturesRef.current.length >= MAX_FRAMES) await finish();
    } catch {
      /* l'utilisateur garde la main : rien a capturer ne bloque pas l'ecran */
    }
  }, [finish]);

  /* ————— capture automatique (web uniquement, meme limite que camera.tsx :
     le guidage en direct repose sur MediaPipe charge en WASM, sans
     equivalent natif pour l'instant) ————— */
  useEffect(() => {
    if (Platform.OS !== "web" || !canUseCamera) return;
    let stopped = false;
    let raf = 0;
    let last = 0;
    let detector: any = null;

    (async () => {
      try {
        const vision: any = await new Function("u", "return import(u)")(
          "/mediapipe/vision_bundle.mjs",
        );
        const fileset = await vision.FilesetResolver.forVisionTasks("/mediapipe");
        detector = await vision.FaceDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: "/mediapipe/blaze_face_short_range.tflite" },
          runningMode: "VIDEO",
        });
        if (stopped) return;

        const loop = () => {
          if (stopped || doneRef.current) return;
          const v = document.querySelector("video");
          const now = performance.now();
          if (v && v.readyState >= 2 && v.videoWidth > 0 && now - last > 110) {
            last = now;
            try {
              const d = readDetection(
                detector.detectForVideo(v, now),
                v.videoWidth,
                v.videoHeight,
              );
              if (d && framingOk(d) && now - lastCaptureRef.current >= CAPTURE_INTERVAL_MS) {
                lastCaptureRef.current = now;
                capture();
              }
            } catch {
              /* image suivante */
            }
          }
          raf = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        /* Detecteur indisponible : repli sur la capture manuelle ci-dessous. */
      }
    })();

    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      try {
        detector?.close?.();
      } catch {
        /* noop */
      }
    };
  }, [canUseCamera, capture]);

  const guideText =
    Platform.OS === "web"
      ? GUIDE_SEQUENCE[Math.min(count, GUIDE_SEQUENCE.length - 1)]
      : "Prenez plusieurs vues de votre visage, sous différents angles";

  const canFinishEarly = count >= MIN_FRAMES;

  /* ————— la carte se construit en direct, pas un simple compteur —————
     Reprend le meme mecanisme que la couronne "façon Face ID" de camera.tsx
     (voir src/components/analysis/ScanRing.tsx) : ici la position est fixe
     (ce scan ne suit pas le visage image par image, contrairement au 3
     angles), mais la progression avance a chaque vue captee. */
  const centerX = useSharedValue(WIN_W / 2);
  const centerY = useSharedValue(WIN_H / 2 - 20);
  const ringRadius = useSharedValue(Math.min(WIN_W, WIN_H) * 0.24);
  const ringProgress = useSharedValue(0);
  const ovalScale = Math.min(WIN_W, WIN_H) * 0.0092;
  const ovalPath = facePathAt(WIN_W / 2, WIN_H / 2 - 20, ovalScale);

  // Meme geometrie que ZONE_SHAPES (FaceZoneMap.tsx), remise a l'echelle de
  // CET ovale-ci : ZONE_SHAPES est defini en offsets depuis FACE_CENTER a
  // l'echelle MARK_SCALE, donc le ratio ovalScale/MARK_SCALE les replace au
  // bon endroit ici sans dupliquer la geometrie.
  const zoneScreenShapes = useMemo(() => {
    const ratio = ovalScale / MARK_SCALE;
    const centerXpx = WIN_W / 2;
    const centerYpx = WIN_H / 2 - 20;
    const out: Record<string, { cx: number; cy: number; rx: number; ry: number }> = {};
    for (const key of ZONE_REVEAL_ORDER) {
      const s = ZONE_SHAPES[key];
      out[key] = {
        cx: centerXpx + (s.cx - FACE_CENTER.cx) * ratio,
        cy: centerYpx + (s.cy - FACE_CENTER.cy) * ratio,
        rx: s.rx * ratio,
        ry: s.ry * ratio,
      };
    }
    return out;
  }, [ovalScale, WIN_W, WIN_H]);

  const zonesActives = ZONE_REVEAL_ORDER.slice(
    0, Math.round((count / MAX_FRAMES) * ZONE_REVEAL_ORDER.length),
  );

  useEffect(() => {
    ringProgress.value = withTiming(count / MAX_FRAMES, { duration: 320 });
  }, [count, ringProgress]);

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.s }]}>
        <AnimatedPressable
          onPress={() => router.back()}
          style={styles.closeBtn}
          scaleTo={0.9}
          hitSlop={8}
          accessibilityLabel="Fermer le scan guidé"
        >
          <Text style={styles.closeText}>✕</Text>
        </AnimatedPressable>
        {/* "bêta" restait affiché ici alors que ce scan est desormais LE
            parcours principal (voir _layout.tsx/dashboard.tsx) — un vrai
            titre, pas une etiquette qui sape la confiance au moment precis
            ou l'on veut qu'il se lise comme le coeur de l'app. */}
        <Text style={styles.headerTitle} accessibilityLabel={`${count} sur ${MAX_FRAMES} vues capturées`}>
          Scan guidé
        </Text>
        <View style={{ width: 36 }} />
      </View>

      {!online ? (
        <Reveal distance={6} style={[styles.noticeWrap, { top: insets.top + 62 }]}>
          <View style={styles.notice}>
            <Text style={styles.noticeText}>
              {"Pas de connexion. L'analyse a besoin du réseau."}
            </Text>
          </View>
        </Reveal>
      ) : null}

      <View style={styles.stage}>
        {canUseCamera ? (
          <>
            <CameraView
              ref={cameraRef}
              style={StyleSheet.absoluteFill}
              facing="front"
              onCameraReady={() => setReady(true)}
            />
            <Svg width={WIN_W} height={WIN_H} style={StyleSheet.absoluteFill} pointerEvents="none">
              {zonesActives.map((key) => (
                <CoverageZone key={key} {...zoneScreenShapes[key]} />
              ))}
              <Path d={ovalPath} fill="none" stroke={colors.accent} strokeWidth={1.6} opacity={0.7} />
              <ScanRing cx={centerX} cy={centerY} radius={ringRadius} progress={ringProgress} />
            </Svg>
          </>
        ) : (
          <View style={styles.placeholder} pointerEvents="box-none">
            <Text style={styles.placeholderText}>
              {permission?.canAskAgain === false
                ? "Autorisez la caméra dans les réglages, puis rechargez."
                : "Autorisez la caméra pour lancer un scan."}
            </Text>
            {!permission?.granted ? (
              <AnimatedPressable style={styles.permBtn} haptic="medium" onPress={requestPermission}>
                <Text style={styles.permBtnText}>Autoriser</Text>
              </AnimatedPressable>
            ) : null}
            {/* Sans camera du tout (refus definitif), la galerie reste le
                seul chemin vers un scan — jamais un ecran sans issue. */}
            <AnimatedPressable style={styles.permBtn} haptic="medium" onPress={pickFromGallery}>
              <Text style={styles.permBtnText}>Choisir depuis la galerie</Text>
            </AnimatedPressable>
          </View>
        )}
      </View>

      <View style={[styles.bas, { paddingBottom: insets.bottom + spacing.m }]}>
        <View style={styles.guidance}>
          <Reveal key={guideText} distance={6}>
            <Text style={styles.guide}>{guideText}</Text>
          </Reveal>
          <Text style={styles.progressCaption}>
            {count} / {MAX_FRAMES}
          </Text>
        </View>

        <View style={styles.controls}>
          {/* Le guidage automatique (web) est un confort, pas une condition :
              la capture manuelle reste toujours accessible, memes filets de
              securite que camera.tsx (voir la note en tete de fichier). */}
          <AnimatedPressable
            onPress={capture}
            style={styles.secondaryBtn}
            disabled={!canUseCamera || !ready || count >= MAX_FRAMES}
            haptic="medium"
            squash
          >
            <Text style={styles.secondaryText}>Capturer une vue</Text>
          </AnimatedPressable>

          <AnimatedPressable
            onPress={pickFromGallery}
            style={styles.secondaryBtn}
            disabled={count >= MAX_FRAMES}
            haptic="medium"
          >
            <Text style={styles.secondaryText}>Galerie</Text>
          </AnimatedPressable>

          <AnimatedPressable
            onPress={finish}
            style={[styles.secondaryBtn, !canFinishEarly && styles.secondaryBtnDim]}
            disabled={!canFinishEarly}
            haptic="medium"
          >
            <Text style={styles.secondaryText}>
              {canFinishEarly ? "Terminer" : `Encore ${MIN_FRAMES - count} vue(s) minimum`}
            </Text>
          </AnimatedPressable>
        </View>
      </View>
    </View>
  );
}

const VOILE_HAUT = "rgba(42,29,24,0.55)";
const VOILE_BAS = "rgba(42,29,24,0.78)";

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: palette.terre },
  header: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 2,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.l,
    paddingBottom: spacing.m,
    backgroundColor: VOILE_HAUT,
  },
  bas: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 2,
    paddingTop: spacing.m,
    backgroundColor: VOILE_BAS,
  },
  closeBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,246,240,0.16)",
  },
  closeText: { color: colors.onInverse, fontSize: 15 },
  headerTitle: { ...type.kicker, color: colors.onInverse, fontVariant: ["tabular-nums"] },

  noticeWrap: { position: "absolute", left: 0, right: 0, zIndex: 2, paddingHorizontal: spacing.l },
  notice: {
    borderWidth: 1,
    borderColor: colors.accentLine,
    backgroundColor: colors.accentSofter,
    paddingVertical: 11,
    paddingHorizontal: spacing.m,
    borderRadius: radius.md,
  },
  noticeText: { ...type.bodySmall, color: colors.onInverse, textAlign: "center" },

  stage: { ...StyleSheet.absoluteFillObject, overflow: "hidden" },
  placeholder: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.m,
  },
  placeholderText: { ...type.bodySmall, color: colors.onInverse, textAlign: "center", maxWidth: 240 },
  permBtn: {
    minHeight: 44,
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: 26,
    paddingVertical: 11,
    borderRadius: radius.pill,
  },
  permBtnText: { ...type.kicker, color: colors.accent },

  guidance: { alignItems: "center", paddingHorizontal: spacing.l, paddingTop: spacing.m },
  guide: { ...type.subtitle, color: colors.onInverse, textAlign: "center", minHeight: 26 },
  progressCaption: {
    ...type.bodySmall,
    color: colors.onInverseMuted,
    marginTop: spacing.xs,
    fontVariant: ["tabular-nums"],
  },

  controls: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.s,
    paddingHorizontal: spacing.m,
    paddingTop: spacing.l,
    paddingBottom: spacing.m,
  },
  secondaryBtn: {
    paddingVertical: 13,
    paddingHorizontal: spacing.l,
    borderWidth: 1,
    borderColor: "rgba(255,246,240,0.42)",
    borderRadius: radius.pill,
    minHeight: 44,
    justifyContent: "center",
  },
  secondaryBtnDim: { opacity: 0.5 },
  secondaryText: { ...type.kicker, color: colors.onInverse },
});
