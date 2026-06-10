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

export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);

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
    await storage.setItem("skyn_last_capture_b64", base64 || "");
    router.replace("/analysis");
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
      finalize(photo?.base64 || null);
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

  const canUseCamera = permission?.granted && Platform.OS !== "web";

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
              {Platform.OS === "web"
                ? "Aperçu caméra non disponible sur le web."
                : "Permission caméra requise."}
            </Text>
            {!permission?.granted && Platform.OS !== "web" ? (
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
        <View style={{ width: 36 }} />
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
});
