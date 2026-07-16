import { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Dimensions,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import Svg, { Ellipse, Defs, Mask, Rect, Circle, Path } from "react-native-svg";
import Animated, {
  useAnimatedStyle,
  useAnimatedProps,
  useSharedValue,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius } from "@/src/theme";
import { storage } from "@/src/utils/storage";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get("window");

const AnimatedCircle = Animated.createAnimatedComponent(Circle);
const CAPTURE_RING_SIZE = 96;
const CAPTURE_RING_R = (CAPTURE_RING_SIZE - 3) / 2;
const CAPTURE_RING_CIRC = 2 * Math.PI * CAPTURE_RING_R;

const GRAIN_DOTS = Array.from({ length: 80 }).map((_, i) => {
  const x = ((i * 73) % 100) / 100;
  const y = ((i * 131) % 100) / 100;
  const r = (i % 3) * 0.4 + 0.4;
  return { x, y, r };
});

// Guidage temps réel (web) : états de cadrage du visage
type GuideState =
  | "searching" | "too_far" | "too_close" | "off_center"
  | "turn_more" | "turn_other" | "perfect";

const GUIDE_MSG: Record<GuideState, string> = {
  searching: "Placez votre visage\ndans l'ovale.",
  too_far: "Rapprochez-vous\ndoucement.",
  too_close: "Éloignez-vous\nun peu.",
  off_center: "Centrez votre visage\ndans l'ovale.",
  turn_more: "Tournez un peu plus\nla tête.",
  turn_other: "Tournez de\nl'autre côté.",
  perfect: "Parfait —\nne bougez plus…",
};

// Scan en 3 prises : face, puis profils pour couvrir joues et tempes
const STEPS = [
  { label: "Face", instruction: "Placez votre visage\nau centre de l'ovale." },
  { label: "Profil droit", instruction: "Tournez la tête\nvers la droite." },
  { label: "Profil gauche", instruction: "Tournez la tête\nvers la gauche." },
];

const SCAN_TIPS = [
  { icon: "☀", title: "Lumière naturelle", text: "Placez-vous face à une fenêtre, sans contre-jour ni lampe directe." },
  { icon: "⌖", title: "30 cm de distance", text: "Le visage remplit l'ovale, regard vers l'objectif, cheveux dégagés." },
  { icon: "↻", title: "3 prises : face, droite, gauche", text: "Tournez la tête entre chaque photo — les profils révèlent joues et tempes pour un résultat optimal." },
  { icon: "✧", title: "Peau nue", text: "Sans maquillage ni crème fraîchement appliquée, pour une analyse fidèle." },
];

export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const [showTips, setShowTips] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  // Séquence multi-angles : 0 = face, 1 = profil droit, 2 = profil gauche
  const [step, setStep] = useState(0);
  const stepRef = useRef(0);
  useEffect(() => { stepRef.current = step; }, [step]);
  const capturesRef = useRef<string[]>([]);
  const yawRef = useRef(0);        // orientation courante de la tête (-1..1)
  const sideSignRef = useRef(0);   // signe du yaw enregistré au profil droit

  // Coaching photo : affiché automatiquement au premier scan
  useEffect(() => {
    (async () => {
      const seen = (await storage.getItem("skyn_scan_tips_seen", "")) as string;
      if (seen !== "1") setShowTips(true);
    })();
  }, []);

  const closeTips = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    await storage.setItem("skyn_scan_tips_seen", "1");
    setShowTips(false);
  };

  // Guidage live (web) : MediaPipe FaceDetector sur le flux vidéo, ~5 fps.
  // Règles : visage absent → chercher ; hauteur <30% → trop loin ;
  // >62% → trop près ; décentré → recentrer ; sinon → parfait.
  const [guide, setGuide] = useState<GuideState>("searching");
  useEffect(() => {
    if (Platform.OS !== "web" || !permission?.granted) return;
    let stopped = false;
    let raf = 0;
    let lastTs = 0;
    let detector: any = null;
    (async () => {
      try {
        // Import ESM natif du navigateur (hors bundler Metro, fichiers locaux)
        const vision: any = await new Function("u", "return import(u)")(
          "/mediapipe/vision_bundle.mjs",
        );
        const { FaceDetector, FilesetResolver } = vision;
        const fileset = await FilesetResolver.forVisionTasks("/mediapipe");
        detector = await FaceDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: "/mediapipe/blaze_face_short_range.tflite" },
          runningMode: "VIDEO",
        });
        const loop = () => {
          if (stopped) return;
          const v = document.querySelector("video");
          const now = performance.now();
          if (v && v.readyState >= 2 && v.videoWidth > 0 && now - lastTs > 180) {
            lastTs = now;
            try {
              const res = detector.detectForVideo(v, now);
              const d = res?.detections?.[0];
              if (!d) {
                setGuide("searching");
              } else {
                const bb = d.boundingBox;
                const hRatio = bb.height / v.videoHeight;
                const cx = (bb.originX + bb.width / 2) / v.videoWidth;
                const cy = (bb.originY + bb.height / 2) / v.videoHeight;
                // Yaw : position du nez entre les deux yeux (-1 = profil, 0 = face)
                const k = d.keypoints || [];
                let yaw = 0;
                if (k.length >= 3) {
                  const eyeMid = (k[0].x + k[1].x) / 2;
                  const inter = Math.abs(k[1].x - k[0].x) || 0.001;
                  yaw = (k[2].x - eyeMid) / inter;
                }
                yawRef.current = yaw;

                const st = stepRef.current;
                if (st === 0) {
                  // Face : cadrage strict, tête droite
                  if (hRatio < 0.3) setGuide("too_far");
                  else if (hRatio > 0.62) setGuide("too_close");
                  else if (Math.abs(cx - 0.5) > 0.14 || Math.abs(cy - 0.5) > 0.16)
                    setGuide("off_center");
                  else if (Math.abs(yaw) > 0.22) setGuide("off_center");
                  else setGuide("perfect");
                } else {
                  // Profils : la tête doit être tournée (≥ 0.25), et au profil
                  // gauche dans le sens opposé au profil droit
                  if (hRatio < 0.24) setGuide("too_far");
                  else if (Math.abs(yaw) < 0.25) setGuide("turn_more");
                  else if (
                    st === 2 &&
                    sideSignRef.current !== 0 &&
                    Math.sign(yaw) === sideSignRef.current
                  )
                    setGuide("turn_other");
                  else setGuide("perfect");
                }
              }
            } catch {
              /* frame suivante */
            }
          }
          raf = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        /* guidage optionnel : sans détecteur, l'écran reste utilisable */
      }
    })();
    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      try { detector?.close?.(); } catch { /* noop */ }
    };
  }, [permission?.granted]);

  const isPerfect = guide === "perfect";

  // Auto-capture : dès que le cadrage est "parfait" pendant ~900ms sans
  // interruption, la photo se déclenche seule. Un anneau lumineux autour du
  // bouton visualise le compte à rebours ; l'appui manuel reste toujours
  // possible en secours (utile en cas de doute ou sur les appareils sans
  // guidage live, où l'anneau ne se déclenche simplement jamais).
  const AUTO_CAPTURE_MS = 900;
  const perfectSinceRef = useRef<number | null>(null);
  const capturingRef = useRef(false);
  const countdown = useSharedValue(0);
  const ringAnimatedProps = useAnimatedProps(() => ({
    strokeDashoffset: CAPTURE_RING_CIRC * (1 - countdown.value),
  }));

  // Flash plein écran au moment exact de la capture — signal fort et bref,
  // indispensable maintenant que la prise de vue peut être silencieuse (auto).
  const flash = useSharedValue(0);
  const flashStyle = useAnimatedStyle(() => ({ opacity: flash.value }));
  const triggerFlash = () => {
    flash.value = withTiming(1, { duration: 60 }, () => {
      flash.value = withTiming(0, { duration: 260 });
    });
  };

  useEffect(() => {
    // Une nouvelle étape (face → profil…) repart avec un compteur neutre
    perfectSinceRef.current = null;
    capturingRef.current = false;
    countdown.value = 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    let raf = 0;
    const tick = () => {
      if (guide === "perfect" && !showTips && !capturingRef.current) {
        if (perfectSinceRef.current === null) perfectSinceRef.current = Date.now();
        const elapsed = Date.now() - perfectSinceRef.current;
        const progress = Math.min(1, elapsed / AUTO_CAPTURE_MS);
        countdown.value = progress;
        if (progress >= 1) {
          countdown.value = 0;
          perfectSinceRef.current = null;
          // eslint-disable-next-line @typescript-eslint/no-use-before-define
          capture();
        }
      } else {
        perfectSinceRef.current = null;
        countdown.value = withTiming(0, { duration: 200 });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guide, showTips]);

  const pulse = useSharedValue(0);
  useEffect(() => {
    pulse.value = withRepeat(
      withTiming(1, { duration: 1800, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [pulse]);
  const pulseStyle = useAnimatedStyle(() => ({
    opacity: 0.55 + pulse.value * 0.45,
  }));

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  const cleanB64 = (base64: string | null) =>
    base64?.startsWith("data:") ? base64.split(",", 2)[1] : base64;

  const finalizeAll = async (captures: string[]) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    await storage.setItem("skyn_last_capture_b64", captures[0] || "");
    await storage.setItem("skyn_last_captures", JSON.stringify(captures));
    router.replace("/analysis");
  };

  // Une image (galerie ou échec caméra) : analyse simple, sans profils
  const finalize = async (base64: string | null) => {
    const clean = cleanB64(base64);
    await finalizeAll(clean ? [clean] : []);
  };

  const onCaptured = async (base64: string | null) => {
    const clean = cleanB64(base64);
    if (!clean) {
      // Capture impossible : on termine avec ce qu'on a
      await finalizeAll(capturesRef.current);
      return;
    }
    capturesRef.current.push(clean);
    const st = stepRef.current;
    if (st === 1) sideSignRef.current = Math.sign(yawRef.current) || 1;
    if (st < 2) {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setStep(st + 1);
    } else {
      await finalizeAll(capturesRef.current);
    }
  };

  // La caméra frontale capture en miroir : on remet la photo à l'endroit
  // (l'aperçu, lui, reste en miroir — comportement selfie naturel).
  const unmirror = (b64: string): Promise<string> => {
    if (Platform.OS !== "web") return Promise.resolve(b64);
    return new Promise((resolve) => {
      const img = new window.Image();
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = img.width;
          c.height = img.height;
          const g = c.getContext("2d")!;
          g.translate(img.width, 0);
          g.scale(-1, 1);
          g.drawImage(img, 0, 0);
          resolve(c.toDataURL("image/jpeg", 0.85));
        } catch {
          resolve(b64);
        }
      };
      img.onerror = () => resolve(b64);
      img.src = b64.startsWith("data:") ? b64 : `data:image/jpeg;base64,${b64}`;
    });
  };

  const capture = async () => {
    if (capturingRef.current) return; // évite un double déclenchement auto+manuel
    capturingRef.current = true;
    if (!cameraRef.current) {
      capturingRef.current = false;
      finalize(null);
      return;
    }
    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.55,
        skipProcessing: true,
      });
      triggerFlash();
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
      // Web : selon les versions, l'image est dans .base64 ou dans .uri (data-URI)
      let b64 = photo?.base64 || null;
      if (!b64 && photo?.uri?.startsWith("data:")) b64 = photo.uri;
      if (!b64 && photo?.uri?.startsWith("blob:")) {
        const blob = await (await fetch(photo.uri)).blob();
        b64 = await new Promise<string>((resolve) => {
          const fr = new FileReader();
          fr.onloadend = () => resolve(String(fr.result || ""));
          fr.readAsDataURL(blob);
        });
      }
      await onCaptured(b64 ? await unmirror(b64) : null);
    } catch {
      await onCaptured(null);
    } finally {
      capturingRef.current = false;
    }
  };

  const pickFromGallery = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) return;
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: "images",
        quality: 0.55,
        base64: true,
        allowsEditing: true,
        aspect: [3, 4],
      });
      if (res.canceled || !res.assets?.[0]) return;
      finalize(res.assets[0].base64 || null);
    } catch {
      finalize(null);
    }
  };

  // expo-camera fonctionne aussi sur le web (getUserMedia) — HTTPS requis
  const canUseCamera = !!permission?.granted;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Camera / placeholder */}
      <View style={styles.cameraWrap}>
        {canUseCamera ? (
          <CameraView
            ref={cameraRef}
            style={StyleSheet.absoluteFill}
            facing="front"
            onCameraReady={() => setReady(true)}
          />
        ) : (
          <View style={[StyleSheet.absoluteFill, styles.placeholder]}>
            <Text style={styles.placeholderText}>
              Permission caméra requise — autorisez l'accès ou choisissez une
              photo depuis la galerie.
            </Text>
            {!permission?.granted ? (
              <TouchableOpacity style={styles.permBtn} onPress={requestPermission}>
                <Text style={styles.permBtnText}>Autoriser</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        )}

        {/* Oval mask overlay */}
        <Svg
          width={SCREEN_W}
          height={SCREEN_H}
          style={StyleSheet.absoluteFill}
          pointerEvents="none"
        >
          <Defs>
            <Mask id="ovalMask">
              <Rect width={SCREEN_W} height={SCREEN_H} fill="white" />
              <Ellipse
                cx={SCREEN_W / 2}
                cy={SCREEN_H / 2 - 40}
                rx={SCREEN_W * 0.36}
                ry={SCREEN_H * 0.26}
                fill="black"
              />
            </Mask>
          </Defs>
          <Rect
            width={SCREEN_W}
            height={SCREEN_H}
            fill={colors.fg}
            opacity={0.78}
            mask="url(#ovalMask)"
          />
          {/* Oval contour — fin, presque effacé : le cadrage est surtout
              porté par les repères d'angle ci-dessous, plus abstraits
              qu'un simple pointillé de forme */}
          <Ellipse
            cx={SCREEN_W / 2}
            cy={SCREEN_H / 2 - 40}
            rx={SCREEN_W * 0.36}
            ry={SCREEN_H * 0.26}
            stroke={isPerfect ? colors.lime : "rgba(255,255,255,0.25)"}
            strokeWidth={isPerfect ? 2 : 1}
            fill="transparent"
          />
          {/* Repères d'angle façon viseur technique — identité propre à cet
              écran, plus graphique qu'un contour uni */}
          {(() => {
            const cx = SCREEN_W / 2;
            const cy = SCREEN_H / 2 - 40;
            const rx = SCREEN_W * 0.36 + 14;
            const ry = SCREEN_H * 0.26 + 14;
            const len = 20;
            const c = isPerfect ? colors.lime : colors.accent;
            const w = isPerfect ? 3 : 2;
            return (
              <>
                <Path d={`M ${cx - rx},${cy - ry + len} L ${cx - rx},${cy - ry} L ${cx - rx + len},${cy - ry}`} stroke={c} strokeWidth={w} fill="none" strokeLinecap="round" />
                <Path d={`M ${cx + rx - len},${cy - ry} L ${cx + rx},${cy - ry} L ${cx + rx},${cy - ry + len}`} stroke={c} strokeWidth={w} fill="none" strokeLinecap="round" />
                <Path d={`M ${cx - rx},${cy + ry - len} L ${cx - rx},${cy + ry} L ${cx - rx + len},${cy + ry}`} stroke={c} strokeWidth={w} fill="none" strokeLinecap="round" />
                <Path d={`M ${cx + rx - len},${cy + ry} L ${cx + rx},${cy + ry} L ${cx + rx},${cy + ry - len}`} stroke={c} strokeWidth={w} fill="none" strokeLinecap="round" />
              </>
            );
          })()}
          {GRAIN_DOTS.map((g, i) => (
            <Circle
              key={i}
              cx={g.x * SCREEN_W}
              cy={g.y * SCREEN_H}
              r={g.r}
              fill={colors.white}
              opacity={0.04}
            />
          ))}
        </Svg>

        {/* Pulsing accent ring */}
        <Animated.View style={[StyleSheet.absoluteFill, pulseStyle]} pointerEvents="none">
          <Svg width={SCREEN_W} height={SCREEN_H}>
            <Ellipse
              cx={SCREEN_W / 2}
              cy={SCREEN_H / 2 - 40}
              rx={SCREEN_W * 0.36 + 6}
              ry={SCREEN_H * 0.26 + 6}
              stroke={isPerfect ? colors.lime : colors.accent}
              strokeWidth={1}
              fill="transparent"
            />
          </Svg>
        </Animated.View>
      </View>

      {/* Top bar */}
      <View style={styles.topBar} pointerEvents="box-none">
        <AnimatedPressable
          testID="camera-close-btn"
          onPress={() => router.back()}
          style={styles.closeBtn}
          scaleTo={0.9}
        >
          <Text style={styles.closeText}>✕</Text>
        </AnimatedPressable>
        <View style={styles.liveBadge}>
          <View style={styles.liveDot} />
          <Text style={styles.topTitle}>SCAN</Text>
        </View>
        <AnimatedPressable
          testID="camera-tips-btn"
          onPress={() => setShowTips(true)}
          style={styles.closeBtn}
          scaleTo={0.9}
        >
          <Text style={styles.closeText}>?</Text>
        </AnimatedPressable>
      </View>

      {/* Retake notice */}
      {retake === "no_face" ? (
        <FadeIn distance={6}>
          <View style={styles.notice} testID="camera-retake-notice">
            <Text style={styles.noticeText}>
              Aucun visage détecté — placez votre visage dans l'ovale et reprenez la photo.
            </Text>
          </View>
        </FadeIn>
      ) : null}

      {/* Bottom controls */}
      <View style={styles.bottomBar} pointerEvents="box-none">
        <FadeIn distance={10}>
          <View style={styles.stepper} testID="camera-step">
            {STEPS.map((s, i) => (
              <View key={s.label} style={styles.stepperItem}>
                <View
                  style={[
                    styles.stepperSegment,
                    i < step && styles.stepperSegmentDone,
                    i === step && styles.stepperSegmentActive,
                  ]}
                />
                <Text
                  style={[styles.stepperLabel, i === step && styles.stepperLabelActive]}
                >
                  {s.label}
                </Text>
              </View>
            ))}
          </View>
          <Text
            style={[styles.guide, isPerfect && { color: colors.lime }]}
            testID="camera-guide"
          >
            {Platform.OS === "web" && guide !== "searching" && step === 0
              ? GUIDE_MSG[guide]
              : Platform.OS === "web" && step > 0 && (guide === "turn_more" || guide === "turn_other" || guide === "perfect" || guide === "too_far")
                ? GUIDE_MSG[guide]
                : STEPS[step].instruction}
          </Text>
          <Text style={styles.conditions}>
            Lumière naturelle · Distance 30 cm
          </Text>
        </FadeIn>

        <View style={styles.bottomRow}>
          <AnimatedPressable
            testID="camera-gallery-btn"
            onPress={pickFromGallery}
            style={styles.galleryBtn}
          >
            <Text style={styles.galleryText}>GALERIE</Text>
          </AnimatedPressable>

          <View style={styles.captureRingWrap}>
            <Svg width={CAPTURE_RING_SIZE} height={CAPTURE_RING_SIZE} style={StyleSheet.absoluteFill}>
              <AnimatedCircle
                cx={CAPTURE_RING_SIZE / 2}
                cy={CAPTURE_RING_SIZE / 2}
                r={CAPTURE_RING_R}
                stroke={colors.lime}
                strokeWidth={3}
                fill="transparent"
                strokeDasharray={`${CAPTURE_RING_CIRC} ${CAPTURE_RING_CIRC}`}
                animatedProps={ringAnimatedProps}
                strokeLinecap="round"
                transform={`rotate(-90, ${CAPTURE_RING_SIZE / 2}, ${CAPTURE_RING_SIZE / 2})`}
              />
            </Svg>
            <AnimatedPressable
              testID="camera-capture-btn"
              onPress={capture}
              style={[styles.captureOuter, isPerfect && styles.captureOuterPerfect]}
              disabled={canUseCamera ? !ready : false}
              scaleTo={0.92}
            >
              <View style={[styles.captureInner, isPerfect && styles.captureInnerPerfect]} />
            </AnimatedPressable>
          </View>

          <View style={{ width: 72 }} />
        </View>

        <Text style={styles.hint}>
          {Platform.OS === "web"
            ? "Capture automatique dès le bon cadrage — ou appuyez"
            : "Appuyez pour capturer"}
        </Text>
      </View>

      {/* Coaching photo — premier scan ou via "?" */}
      {showTips ? (
        <View style={styles.tipsOverlay} testID="camera-tips-sheet">
          <View style={styles.tipsCard}>
            <Text style={styles.tipsTitle}>Réussir votre scan</Text>
            <Text style={styles.tipsSubtitle}>
              Trois gestes pour une analyse précise :
            </Text>
            {SCAN_TIPS.map((t) => (
              <View key={t.title} style={styles.tipRow}>
                <Text style={styles.tipIcon}>{t.icon}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.tipTitle}>{t.title}</Text>
                  <Text style={styles.tipBody}>{t.text}</Text>
                </View>
              </View>
            ))}
            <AnimatedPressable
              testID="camera-tips-ok"
              onPress={closeTips}
              style={styles.tipsBtn}
            >
              <Text style={styles.tipsBtnText}>C'est compris</Text>
            </AnimatedPressable>
          </View>
        </View>
      ) : null}

      {/* Flash — signal bref au moment exact de la capture */}
      <Animated.View
        style={[styles.flashOverlay, flashStyle]}
        pointerEvents="none"
        testID="camera-flash"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.fg },
  cameraWrap: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.fg },
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#13110D",
  },
  placeholderText: {
    fontFamily: fonts.body,
    color: "rgba(255,255,255,0.7)",
    fontSize: 14,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
    lineHeight: 22,
  },
  permBtn: {
    marginTop: spacing.l,
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: 28,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  permBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.accent,
    letterSpacing: 2,
    fontSize: 12,
    textTransform: "uppercase",
  },
  topBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
  },
  closeBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.14)",
  },
  closeText: { color: colors.white, fontSize: 16, fontFamily: fonts.body },
  topTitle: {
    fontFamily: fonts.bodyMedium,
    color: colors.white,
    letterSpacing: 3,
    fontSize: 11,
    textTransform: "uppercase",
  },
  liveBadge: { flexDirection: "row", alignItems: "center", gap: 6 },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.lime,
  },
  flashOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.white,
  },
  notice: {
    position: "absolute",
    top: 80,
    left: spacing.xl,
    right: spacing.xl,
    borderWidth: 1,
    borderColor: colors.accent,
    paddingVertical: 12,
    paddingHorizontal: spacing.m,
    backgroundColor: "rgba(45,31,26,0.85)",
    borderRadius: radius.sm,
  },
  noticeText: {
    fontFamily: fonts.body,
    color: colors.white,
    fontSize: 12,
    lineHeight: 18,
    letterSpacing: 0.3,
    textAlign: "center",
  },
  bottomBar: {
    position: "absolute",
    bottom: 36,
    left: 0,
    right: 0,
    alignItems: "center",
  },
  stepper: {
    flexDirection: "row",
    gap: spacing.s,
    marginBottom: spacing.m,
    paddingHorizontal: spacing.l,
  },
  stepperItem: { flex: 1, alignItems: "center", gap: 6 },
  stepperSegment: {
    width: "100%",
    height: 3,
    borderRadius: 1.5,
    backgroundColor: "rgba(255,255,255,0.2)",
  },
  stepperSegmentDone: { backgroundColor: colors.lime },
  stepperSegmentActive: { backgroundColor: colors.accent },
  stepperLabel: {
    fontFamily: fonts.bodyMedium,
    color: "rgba(255,255,255,0.45)",
    fontSize: 9,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  stepperLabelActive: { color: colors.white },
  guide: {
    fontFamily: fonts.heading,
    color: colors.white,
    fontSize: 18,
    textAlign: "center",
    marginBottom: spacing.s,
    lineHeight: 26,
    opacity: 0.95,
  },
  conditions: {
    fontFamily: fonts.body,
    color: colors.white,
    fontSize: 12,
    textAlign: "center",
    marginBottom: spacing.l,
    opacity: 0.6,
  },
  bottomRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    width: "100%",
    paddingHorizontal: spacing.xl,
  },
  galleryBtn: {
    width: 72,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.25)",
    borderRadius: radius.pill,
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.08)",
  },
  galleryText: {
    fontFamily: fonts.bodyMedium,
    color: colors.white,
    fontSize: 9,
    letterSpacing: 2,
  },
  captureRingWrap: {
    width: CAPTURE_RING_SIZE,
    height: CAPTURE_RING_SIZE,
    alignItems: "center",
    justifyContent: "center",
  },
  captureOuter: {
    width: 80,
    height: 80,
    borderRadius: 40,
    borderWidth: 2,
    borderColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  captureOuterPerfect: { borderColor: colors.lime },
  captureInner: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: colors.accent,
  },
  captureInnerPerfect: { backgroundColor: colors.lime },
  hint: {
    marginTop: spacing.m,
    fontFamily: fonts.body,
    color: "rgba(255,255,255,0.6)",
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  tipsOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(19,17,13,0.72)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.l,
    zIndex: 30,
  },
  tipsCard: {
    backgroundColor: colors.bg,
    borderRadius: radius.lg,
    padding: spacing.l,
    width: "100%",
    maxWidth: 420,
  },
  tipsTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 26,
    letterSpacing: -0.5,
  },
  tipsSubtitle: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13,
    marginTop: 4,
    marginBottom: spacing.m,
  },
  tipRow: {
    flexDirection: "row",
    gap: spacing.m,
    paddingVertical: spacing.s,
    alignItems: "flex-start",
  },
  tipIcon: {
    fontFamily: fonts.heading,
    color: colors.accent,
    fontSize: 22,
    width: 30,
    textAlign: "center",
  },
  tipTitle: {
    fontFamily: fonts.headingMedium,
    color: colors.fg,
    fontSize: 15,
  },
  tipBody: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 2,
  },
  tipsBtn: {
    marginTop: spacing.m,
    backgroundColor: colors.accent,
    paddingVertical: 15,
    alignItems: "center",
    borderRadius: radius.pill,
  },
  tipsBtnText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
