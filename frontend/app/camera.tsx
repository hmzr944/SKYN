import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutChangeEvent, Platform, StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Defs, G, Mask, Path, Rect } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import {
  AUTO_CAPTURE_MS,
  evaluate,
  guideMessage,
  readDetection,
  STEPS,
  type GuideState,
  type ScanStep,
} from "@/src/services/faceGuide";
import { colors, motion, radius, spacing, type } from "@/src/theme";
import { FACE_CLOSED, FACE_LENGTH, FACE_PATH } from "@/src/theme/mark";
import { storage } from "@/src/utils/storage";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

const RING_R = 36;
const RING_CIRC = 2 * Math.PI * RING_R;

/** Base64 nu, sans entete : c'est ce que le reste de l'app attend. */
const cleanB64 = (b?: string | null) =>
  b ? (b.startsWith("data:") ? b.split(",")[1] ?? "" : b) : "";

/**
 * L'ecran de scan, guide en direct.
 *
 * Le principe : on ne demande pas une photo, on accompagne une pose. Un
 * detecteur lit le flux en continu et dit ce qu'il faut corriger — trop loin,
 * decentre, tete pas assez tournee — puis declenche seul quand le cadrage
 * tient reellement. Trois angles s'enchainent, face puis les deux profils,
 * parce qu'une vue de face aplatit les joues et les tempes.
 *
 * Le guidage est un confort, pas une condition : si le detecteur ne se charge
 * pas, le declencheur manuel reste disponible et l'ecran fonctionne.
 */
export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  const [step, setStep] = useState<ScanStep>(0);
  const stepRef = useRef<ScanStep>(0);
  useEffect(() => {
    stepRef.current = step;
  }, [step]);

  const [guide, setGuide] = useState<GuideState>("loading");
  const capturesRef = useRef<string[]>([]);
  const yawRef = useRef(0);
  const sideSignRef = useRef(0);
  const capturingRef = useRef(false);

  const [stage, setStage] = useState({ w: 0, h: 0 });
  const onStageLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setStage((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
  };

  const canUseCamera = !!permission?.granted;
  const isPerfect = guide === "perfect";

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  /* ————— guidage live ————— */
  useEffect(() => {
    if (Platform.OS !== "web" || !canUseCamera) {
      // Hors web, le detecteur n'est pas disponible ici : on rend la main au
      // declencheur manuel plutot que de laisser un ecran qui attend.
      setGuide("searching");
      return;
    }
    let stopped = false;
    let raf = 0;
    let last = 0;
    let detector: any = null;

    (async () => {
      try {
        // Import ESM natif : ces fichiers sont servis tels quels, hors bundler.
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
          if (stopped) return;
          const v = document.querySelector("video");
          const now = performance.now();
          // ~5 images par seconde : au-dela on chauffe le telephone sans rien
          // gagner, l'oeil ne suit pas des corrections plus rapides.
          if (v && v.readyState >= 2 && v.videoWidth > 0 && now - last > 180) {
            last = now;
            try {
              const d = readDetection(
                detector.detectForVideo(v, now),
                v.videoWidth,
                v.videoHeight,
              );
              if (d) yawRef.current = d.yaw;
              setGuide(evaluate(d, stepRef.current, sideSignRef.current));
            } catch {
              /* image suivante */
            }
          }
          raf = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        // Detecteur indisponible : l'ecran reste utilisable a la main.
        if (!stopped) setGuide("searching");
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
  }, [canUseCamera]);

  /* ————— animations ————— */
  const breath = useSharedValue(0);
  useEffect(() => {
    breath.value = withRepeat(
      withTiming(1, { duration: 2200, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [breath]);

  // Le contour se stabilise des que la pose est bonne : il cesse de respirer
  // et passe au plein. C'est le signal le plus lisible d'un cadrage valide.
  const lock = useSharedValue(0);
  useEffect(() => {
    lock.value = withSpring(isPerfect ? 1 : 0, motion.spring);
  }, [isPerfect, lock]);

  const contourProps = useAnimatedProps(() => ({
    strokeOpacity: lock.value + (1 - lock.value) * (0.45 + breath.value * 0.35),
  }));

  const countdown = useSharedValue(0);
  const ringProps = useAnimatedProps(() => ({
    strokeDashoffset: RING_CIRC * (1 - countdown.value),
  }));

  const flash = useSharedValue(0);
  const flashStyle = useAnimatedStyle(() => ({ opacity: flash.value }));

  /* ————— enchainement des prises ————— */
  const finalizeAll = useCallback(
    async (captures: string[]) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      await storage.setItem("skyn_last_capture_b64", captures[0] || "");
      await storage.setItem("skyn_last_captures", JSON.stringify(captures));
      router.replace("/analysis");
    },
    [router],
  );

  const onCaptured = useCallback(
    async (b64: string | null) => {
      const clean = cleanB64(b64);
      if (!clean) {
        await finalizeAll(capturesRef.current);
        return;
      }
      capturesRef.current.push(clean);
      const st = stepRef.current;
      // On memorise de quel cote la tete etait tournee au premier profil pour
      // exiger l'autre au suivant.
      if (st === 1) sideSignRef.current = Math.sign(yawRef.current) || 1;

      if (st < 2) {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        capturingRef.current = false;
        countdown.value = 0;
        setStep((st + 1) as ScanStep);
      } else {
        await finalizeAll(capturesRef.current);
      }
    },
    [finalizeAll, countdown],
  );

  const capture = useCallback(async () => {
    if (capturingRef.current) return;
    capturingRef.current = true;
    flash.value = withTiming(1, { duration: 60 }, () => {
      flash.value = withTiming(0, { duration: 260 });
    });
    if (!cameraRef.current) {
      await onCaptured(null);
      return;
    }
    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.55,
        skipProcessing: true,
      });
      await onCaptured(photo?.base64 ?? null);
    } catch {
      await onCaptured(null);
    }
  }, [onCaptured, flash]);

  /* ————— declenchement automatique ————— */
  useEffect(() => {
    // Chaque nouvelle etape repart d'un compteur neutre.
    capturingRef.current = false;
    countdown.value = 0;
  }, [step, countdown]);

  useEffect(() => {
    if (!isPerfect || capturingRef.current) {
      countdown.value = withTiming(0, { duration: motion.fast });
      return;
    }
    // La pose doit tenir : un cadrage bon pendant un dixieme de seconde ne
    // prouve rien, c'est en le maintenant qu'on obtient une image nette.
    countdown.value = withTiming(1, { duration: AUTO_CAPTURE_MS, easing: Easing.linear });
    const t = setTimeout(() => {
      if (!capturingRef.current) capture();
    }, AUTO_CAPTURE_MS);
    return () => clearTimeout(t);
  }, [isPerfect, step, capture, countdown]);

  const pickFromGallery = async () => {
    try {
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        base64: true,
        quality: 0.55,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const clean = cleanB64(res.assets[0].base64);
      await finalizeAll(clean ? [clean] : []);
    } catch {
      await finalizeAll(capturesRef.current);
    }
  };

  /* ————— geometrie ————— */
  const CONTENT_W = 36.8;
  const CONTENT_H = 44.5;
  const CENTER = { x: 32, y: 32.3 };
  const k = Math.min((stage.w * 0.78) / CONTENT_W, (stage.h * 0.74) / CONTENT_H);
  const tx = stage.w / 2 - CENTER.x * k;
  const ty = stage.h / 2 - CENTER.y * k;
  const stroke = k > 0 ? 2.4 / k : 0;
  const laid = stage.w > 0 && stage.h > 0;

  const current = STEPS[step];

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <AnimatedPressable
          testID="camera-close-btn"
          onPress={() => router.back()}
          style={styles.closeBtn}
          scaleTo={0.9}
        >
          <Text style={styles.closeText}>✕</Text>
        </AnimatedPressable>
        <View style={styles.stepDots}>
          {STEPS.map((s, i) => (
            <View
              key={s.label}
              style={[styles.stepDot, i === step && styles.stepDotOn, i < step && styles.stepDotDone]}
            />
          ))}
        </View>
        <View style={{ width: 36 }} />
      </View>

      {retake === "no_face" ? (
        <Reveal distance={6} style={styles.noticeWrap}>
          <View style={styles.notice} testID="camera-retake-notice">
            <Text style={styles.noticeText}>
              {"Aucun visage détecté sur la dernière prise. Suivez le guidage ci-dessous."}
            </Text>
          </View>
        </Reveal>
      ) : null}

      <View style={styles.stage} onLayout={onStageLayout}>
        {canUseCamera ? (
          <CameraView
            ref={cameraRef}
            style={StyleSheet.absoluteFill}
            facing="front"
            onCameraReady={() => setReady(true)}
          />
        ) : null}

        {laid ? (
          <Svg width={stage.w} height={stage.h} style={StyleSheet.absoluteFill} pointerEvents="none">
            <Defs>
              <Mask id="skyn-window">
                <Rect width={stage.w} height={stage.h} fill="white" />
                <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
                  <Path d={FACE_CLOSED} fill="black" />
                </G>
              </Mask>
            </Defs>

            {/* Voile creme : la fenetre decoupe le fond de l'app, elle ne
                l'assombrit pas. */}
            <Rect width={stage.w} height={stage.h} fill={colors.bg} mask="url(#skyn-window)" />

            <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
              {!canUseCamera ? <Path d={FACE_CLOSED} fill={colors.fg} opacity={0.05} /> : null}
              <AnimatedPath
                d={FACE_PATH}
                fill="none"
                stroke={colors.accent}
                strokeWidth={stroke}
                strokeLinecap="round"
                strokeDasharray={FACE_LENGTH}
                animatedProps={contourProps}
              />
            </G>
          </Svg>
        ) : null}

        {!canUseCamera ? (
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
        ) : null}

        <Animated.View style={[StyleSheet.absoluteFill, styles.flash, flashStyle]} pointerEvents="none" />
      </View>

      <View style={styles.guidance}>
        <Text style={styles.stepLabel}>{current.label}</Text>
        <Text style={styles.guide}>{current.title}</Text>
        {/* La consigne live remplace le rappel statique des qu'elle a du sens. */}
        <Text style={[styles.live, isPerfect && styles.liveOk]} testID="camera-guide">
          {canUseCamera ? guideMessage(guide, step) : current.hint}
        </Text>
      </View>

      <View style={styles.controls}>
        <AnimatedPressable
          testID="camera-gallery-btn"
          onPress={pickFromGallery}
          style={styles.galleryBtn}
        >
          <Text style={styles.galleryText}>Galerie</Text>
        </AnimatedPressable>

        <AnimatedPressable
          testID="camera-capture-btn"
          onPress={capture}
          style={styles.captureWrap}
          disabled={canUseCamera ? !ready : false}
          haptic="medium"
          scaleTo={0.92}
        >
          {/* L'anneau se remplit pendant que la pose se maintient : on voit
              le declenchement venir au lieu de le subir. */}
          <Svg width={84} height={84} style={StyleSheet.absoluteFill}>
            <Circle cx={42} cy={42} r={RING_R} fill="none" stroke={colors.borderMid} strokeWidth={2} />
            <AnimatedCircle
              cx={42}
              cy={42}
              r={RING_R}
              fill="none"
              stroke={colors.accent}
              strokeWidth={3}
              strokeLinecap="round"
              strokeDasharray={RING_CIRC}
              transform="rotate(-90 42 42)"
              animatedProps={ringProps}
            />
          </Svg>
          <View style={styles.captureInner} />
        </AnimatedPressable>

        <View style={styles.controlsSpacer} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.s,
    paddingBottom: spacing.s,
  },
  closeBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSunken,
  },
  closeText: { color: colors.fg, fontSize: 15 },
  stepDots: { flexDirection: "row", gap: 7, alignItems: "center" },
  stepDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.fgFaint,
  },
  stepDotOn: { width: 22, backgroundColor: colors.accent },
  stepDotDone: { backgroundColor: colors.fgDim },

  noticeWrap: { paddingHorizontal: spacing.l, paddingBottom: spacing.s },
  notice: {
    borderWidth: 1,
    borderColor: colors.accentLine,
    backgroundColor: colors.accentSofter,
    paddingVertical: 11,
    paddingHorizontal: spacing.m,
    borderRadius: radius.md,
  },
  noticeText: { ...type.bodySmall, color: colors.fg, textAlign: "center" },

  stage: { flex: 1, overflow: "hidden" },
  flash: { backgroundColor: colors.bg },
  placeholder: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.m,
  },
  placeholderText: { ...type.bodySmall, color: colors.fgDim, textAlign: "center", maxWidth: 240 },
  permBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: 26,
    paddingVertical: 11,
    borderRadius: radius.pill,
  },
  permBtnText: { ...type.kicker, color: colors.accent },

  guidance: { alignItems: "center", paddingHorizontal: spacing.l, paddingTop: spacing.m, gap: 5 },
  stepLabel: { ...type.kicker, color: colors.fgDim },
  guide: { ...type.subtitle, color: colors.fg, textAlign: "center" },
  live: { ...type.bodySmall, color: colors.fgMuted, textAlign: "center", minHeight: 20 },
  liveOk: { color: colors.accent, fontFamily: type.label.fontFamily },

  controls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.m,
    paddingBottom: spacing.m,
  },
  galleryBtn: {
    width: 84,
    paddingVertical: 11,
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  galleryText: { ...type.kicker, color: colors.fgMuted },
  controlsSpacer: { width: 84 },
  captureWrap: { width: 84, height: 84, alignItems: "center", justifyContent: "center" },
  captureInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: colors.accent },
});
