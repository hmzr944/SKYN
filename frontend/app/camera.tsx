import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutChangeEvent, Platform, StyleSheet, Text, View } from "react-native";
import Svg, { Defs, G, Mask, Path, Rect } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withRepeat,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { track } from "@/src/services/analytics";
import {
  ANGLES,
  angleOf,
  evaluate,
  framingOk,
  guideMessage,
  HOLD_MS,
  readDetection,
  type Angle,
  type GuideState,
} from "@/src/services/faceGuide";
import { colors, motion, radius, spacing, type } from "@/src/theme";
import { FACE_CLOSED, FACE_LENGTH, FACE_PATH } from "@/src/theme/mark";
import { storage } from "@/src/utils/storage";

const AnimatedPath = Animated.createAnimatedComponent(Path);

/**
 * Neutralise le miroir de l'apercu, directement sur l'element video.
 *
 * expo-camera applique un scaleX(-1) sur la video en camera frontale et
 * n'implemente pas la prop `mirror` sur le web. Deux approches ont ete
 * ecartees avant celle-ci :
 *   - compenser par une transformation opposee sur un conteneur parent :
 *     correct dans Chromium, mais WebKit compose la video dans sa propre
 *     couche, qui peut ignorer la transformation d'un ancetre ;
 *   - poser la regle dans app/+html.tsx : ce fichier n'est pas applique par
 *     `expo export --platform web`, l'index.html genere n'en contient rien.
 *
 * Reste l'injection a l'execution, qui vise l'element lui-meme et ne depend
 * d'aucune indirection.
 */
const STYLE_ID = "skyn-unmirror";
function neutraliseMiroir() {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement("style");
  el.id = STYLE_ID;
  el.textContent = "[data-skyn-camera] video{transform:none !important;}";
  document.head.appendChild(el);
}

/** Base64 nu, sans entete : c'est ce que le reste de l'app attend. */
const cleanB64 = (b?: string | null) =>
  b ? (b.startsWith("data:") ? b.split(",")[1] ?? "" : b) : "";

/**
 * Le scan, en une seule session continue.
 *
 * On ne prend pas de photos : on tourne lentement la tete et l'app
 * echantillonne toute seule les angles qui lui manquent, comme l'enregistrement
 * de Face ID. Le contour se remplit au fur et a mesure de la couverture ; quand
 * il est complet, l'analyse part.
 *
 * MIROIR — l'apercu n'est pas inverse : voir neutraliseMiroir() ci-dessous.
 * La capture, elle, est inversee separement par la bibliotheque
 * (isImageMirror) et reste corrigee par unmirror(). Ce sont deux
 * transformations independantes, il faut traiter les deux.
 */
export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  const [guide, setGuide] = useState<GuideState>("loading");
  const [covered, setCovered] = useState<Angle[]>([]);
  const coveredRef = useRef<Angle[]>([]);
  const capturesRef = useRef<string[]>([]);
  const holdSinceRef = useRef<number | null>(null);
  const busyRef = useRef(false);
  const doneRef = useRef(false);

  const [stage, setStage] = useState({ w: 0, h: 0 });
  const onStageLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setStage((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
  };

  const canUseCamera = !!permission?.granted;

  useEffect(() => {
    neutraliseMiroir();
    track("scan_started");
  }, []);

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  /* ————— fin de session ————— */
  const finish = useCallback(
    async (captures: string[]) => {
      if (doneRef.current) return;
      doneRef.current = true;
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      await storage.setItem("skyn_last_capture_b64", captures[0] || "");
      await storage.setItem("skyn_last_captures", JSON.stringify(captures));
      router.replace("/analysis");
    },
    [router],
  );

  const unmirror = (b64: string): Promise<string> =>
    new Promise((resolve) => {
      if (Platform.OS !== "web") {
        resolve(b64);
        return;
      }
      const img = new window.Image();
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = img.width;
          c.height = img.height;
          const g = c.getContext("2d");
          if (!g) return resolve(b64);
          g.translate(img.width, 0);
          g.scale(-1, 1);
          g.drawImage(img, 0, 0);
          resolve(c.toDataURL("image/jpeg", 0.85).split(",")[1] ?? b64);
        } catch {
          resolve(b64);
        }
      };
      img.onerror = () => resolve(b64);
      img.src = b64.startsWith("data:") ? b64 : `data:image/jpeg;base64,${b64}`;
    });

  /** Echantillonne l'angle courant, sans ceremonie : ni flash ni compte a rebours. */
  const sample = useCallback(
    async (angle: Angle) => {
      if (busyRef.current || doneRef.current) return;
      busyRef.current = true;
      try {
        const photo = await cameraRef.current?.takePictureAsync({
          base64: true,
          quality: 0.55,
          skipProcessing: true,
        });
        const clean = cleanB64(photo?.base64 ?? null);
        if (clean) {
          capturesRef.current.push(await unmirror(clean));
          const next = [...coveredRef.current, angle];
          coveredRef.current = next;
          setCovered(next);
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          if (next.length >= ANGLES.length) await finish(capturesRef.current);
        }
      } catch {
        /* on retentera a l'image suivante */
      } finally {
        busyRef.current = false;
        holdSinceRef.current = null;
      }
    },
    [finish],
  );

  /* ————— guidage live ————— */
  useEffect(() => {
    if (Platform.OS !== "web" || !canUseCamera) {
      setGuide("searching");
      return;
    }
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
              const state = evaluate(d, coveredRef.current);
              setGuide(state);

              // L'angle doit tenir un court instant avant d'etre echantillonne :
              // une image prise en plein mouvement serait floue.
              const angle = d && framingOk(d) ? angleOf(d.yaw) : null;
              const wanted = angle && !coveredRef.current.includes(angle) ? angle : null;
              if (wanted) {
                if (holdSinceRef.current === null) holdSinceRef.current = now;
                else if (now - holdSinceRef.current >= HOLD_MS) sample(wanted);
              } else {
                holdSinceRef.current = null;
              }
            } catch {
              /* image suivante */
            }
          }
          raf = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        // Detecteur indisponible : on rend la main au declencheur manuel.
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
  }, [canUseCamera, sample]);

  /* ————— animations ————— */
  const breath = useSharedValue(0);
  useEffect(() => {
    breath.value = withRepeat(
      withTiming(1, { duration: 2200, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [breath]);

  // Le contour se remplit a mesure que les angles sont couverts : c'est la
  // seule jauge de l'ecran, et elle est portee par la forme de la marque.
  const fill = useSharedValue(0);
  useEffect(() => {
    fill.value = withSpring(covered.length / ANGLES.length, motion.spring);
  }, [covered.length, fill]);

  const trackProps = useAnimatedProps(() => ({
    strokeOpacity: 0.16 + breath.value * 0.1,
  }));
  const fillProps = useAnimatedProps(() => ({
    strokeDashoffset: FACE_LENGTH * (1 - fill.value),
  }));

  /* ————— repli manuel ————— */
  const manualCapture = async () => {
    const photo = await cameraRef.current?.takePictureAsync({
      base64: true,
      quality: 0.55,
      skipProcessing: true,
    });
    const clean = cleanB64(photo?.base64 ?? null);
    await finish(clean ? [await unmirror(clean)] : []);
  };

  const pickFromGallery = async () => {
    try {
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        base64: true,
        quality: 0.55,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const clean = cleanB64(res.assets[0].base64);
      await finish(clean ? [clean] : []);
    } catch {
      await finish(capturesRef.current);
    }
  };

  /* ————— geometrie ————— */
  const CONTENT_W = 36.8;
  const CONTENT_H = 44.5;
  const CENTER = { x: 32, y: 32.3 };
  const k = Math.min((stage.w * 0.78) / CONTENT_W, (stage.h * 0.74) / CONTENT_H);
  const tx = stage.w / 2 - CENTER.x * k;
  const ty = stage.h / 2 - CENTER.y * k;
  const stroke = k > 0 ? 2.6 / k : 0;
  const laid = stage.w > 0 && stage.h > 0;

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
        <Text style={styles.headerTitle}>
          {covered.length} / {ANGLES.length} angles
        </Text>
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
          // La marque data- est la cible de la regle CSS qui neutralise le
          // miroir : voir app/+html.tsx.
          <View
            style={StyleSheet.absoluteFill}
            {...(Platform.OS === "web" ? { dataSet: { skynCamera: "1" } } : {})}
          >
            <CameraView
              ref={cameraRef}
              style={StyleSheet.absoluteFill}
              facing="front"
              mirror={false}
              onCameraReady={() => setReady(true)}
            />
          </View>
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

            <Rect width={stage.w} height={stage.h} fill={colors.bg} mask="url(#skyn-window)" />

            <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
              {!canUseCamera ? <Path d={FACE_CLOSED} fill={colors.fg} opacity={0.05} /> : null}
              {/* Le contour en creux, puis la part couverte par-dessus. */}
              <AnimatedPath
                d={FACE_PATH}
                fill="none"
                stroke={colors.fg}
                strokeWidth={stroke}
                strokeLinecap="round"
                animatedProps={trackProps}
              />
              <AnimatedPath
                d={FACE_PATH}
                fill="none"
                stroke={colors.accent}
                strokeWidth={stroke}
                strokeLinecap="round"
                strokeDasharray={FACE_LENGTH}
                animatedProps={fillProps}
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
      </View>

      <View style={styles.guidance}>
        <Reveal key={guide} distance={6}>
          <Text
            style={[styles.guide, guide === "hold" && styles.guideOk]}
            testID="camera-guide"
          >
            {guideMessage(guide)}
          </Text>
        </Reveal>
        <Text style={styles.hint}>
          Tournez lentement la tête — les prises se font toutes seules.
        </Text>
      </View>

      <View style={styles.controls}>
        <AnimatedPressable
          testID="camera-gallery-btn"
          onPress={pickFromGallery}
          style={styles.secondaryBtn}
        >
          <Text style={styles.secondaryText}>Galerie</Text>
        </AnimatedPressable>

        {/* Repli : si le guidage n'a pas pu se charger, rien ne doit empecher
            de lancer une analyse simple. */}
        <AnimatedPressable
          testID="camera-capture-btn"
          onPress={manualCapture}
          style={styles.secondaryBtn}
          disabled={canUseCamera ? !ready : true}
          haptic="medium"
        >
          <Text style={styles.secondaryText}>Prendre maintenant</Text>
        </AnimatedPressable>
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
  headerTitle: { ...type.kicker, color: colors.fgDim, fontVariant: ["tabular-nums"] },

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

  guidance: { alignItems: "center", paddingHorizontal: spacing.l, paddingTop: spacing.m, gap: 6 },
  guide: { ...type.subtitle, color: colors.fg, textAlign: "center", minHeight: 26 },
  guideOk: { color: colors.accent },
  hint: { ...type.bodySmall, color: colors.fgDim, textAlign: "center" },

  controls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.m,
    paddingHorizontal: spacing.l,
    paddingTop: spacing.l,
    paddingBottom: spacing.m,
  },
  secondaryBtn: {
    paddingVertical: 13,
    paddingHorizontal: spacing.l,
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.pill,
    minHeight: 44,
    justifyContent: "center",
  },
  secondaryText: { ...type.kicker, color: colors.fgMuted },
});
