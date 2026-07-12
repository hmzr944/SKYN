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
import Svg, { Ellipse, Defs, Mask, Rect, Circle } from "react-native-svg";
import Animated, {
  useAnimatedStyle,
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

const GRAIN_DOTS = Array.from({ length: 80 }).map((_, i) => {
  const x = ((i * 73) % 100) / 100;
  const y = ((i * 131) % 100) / 100;
  const r = (i % 3) * 0.4 + 0.4;
  return { x, y, r };
});

const SCAN_TIPS = [
  { icon: "☀", title: "Lumière naturelle", text: "Placez-vous face à une fenêtre, sans contre-jour ni lampe directe." },
  { icon: "⌖", title: "30 cm de distance", text: "Le visage remplit l'ovale, regard vers l'objectif, cheveux dégagés." },
  { icon: "✧", title: "Peau nue", text: "Sans maquillage ni crème fraîchement appliquée, pour une analyse fidèle." },
];

export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const [showTips, setShowTips] = useState(false);
  const cameraRef = useRef<CameraView>(null);

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

  const finalize = async (base64: string | null) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    // Sur le web, expo-camera/image-picker peuvent renvoyer une data-URI complète
    const clean = base64?.startsWith("data:") ? base64.split(",", 2)[1] : base64;
    await storage.setItem("skyn_last_capture_b64", clean || "");
    router.replace("/analysis");
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
    if (!cameraRef.current) {
      finalize(null);
      return;
    }
    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.55,
        skipProcessing: true,
      });
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
      finalize(b64 ? await unmirror(b64) : null);
    } catch {
      finalize(null);
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
          {/* Oval contour — accent solid stroke */}
          <Ellipse
            cx={SCREEN_W / 2}
            cy={SCREEN_H / 2 - 40}
            rx={SCREEN_W * 0.36}
            ry={SCREEN_H * 0.26}
            stroke={colors.accent}
            strokeWidth={2}
            fill="transparent"
          />
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
              stroke={colors.accent}
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
        <Text style={styles.topTitle}>Bilan</Text>
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
          <Text style={styles.guide}>
            {"Placez votre visage\nau centre de l'ovale."}
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

          <AnimatedPressable
            testID="camera-capture-btn"
            onPress={capture}
            style={styles.captureOuter}
            disabled={canUseCamera ? !ready : false}
            scaleTo={0.92}
          >
            <View style={styles.captureInner} />
          </AnimatedPressable>

          <View style={{ width: 72 }} />
        </View>

        <Text style={styles.hint}>Appuyez pour démarrer l'analyse</Text>
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
  captureOuter: {
    width: 80,
    height: 80,
    borderRadius: 40,
    borderWidth: 2,
    borderColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  captureInner: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: colors.accent,
  },
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
