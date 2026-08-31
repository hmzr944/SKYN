import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dimensions, Platform, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";
import { useSharedValue, withTiming } from "react-native-reanimated";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { ScanRing } from "@/src/components/analysis/ScanRing";
import { track } from "@/src/services/analytics";
import { framingOk, readDetection } from "@/src/services/faceGuide";
import { colors, palette, radius, spacing, type } from "@/src/theme";
import { facePathAt } from "@/src/theme/mark";
import { useOnline } from "@/src/hooks/useOnline";
import { storage } from "@/src/utils/storage";

/**
 * Scan guide (v0, EXPERIMENTAL) — parallele au scan 3 angles de camera.tsx,
 * qui reste intact et reste le parcours par defaut.
 *
 * Ce que cet ecran fait : collecte jusqu'a MAX_FRAMES vues pendant que la
 * personne tourne la tete, puis envoie tout en un seul appel a
 * /api/analyze/guided, qui decide lui-meme cote serveur combien de vues
 * etaient exploitables et quand la mesure est jugee stable.
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

const { width: WIN_W, height: WIN_H } = Dimensions.get("window");

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

export default function CameraGuidedScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
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
        <Text style={styles.headerTitle} accessibilityLabel={`${count} sur ${MAX_FRAMES} vues capturées`}>
          bêta
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
          {Platform.OS !== "web" ? (
            <AnimatedPressable
              onPress={capture}
              style={styles.secondaryBtn}
              disabled={!canUseCamera || !ready || count >= MAX_FRAMES}
              haptic="medium"
            >
              <Text style={styles.secondaryText}>Capturer une vue</Text>
            </AnimatedPressable>
          ) : null}

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
