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

import { colors, fonts, spacing, radius } from "@/src/theme";
import { storage } from "@/src/utils/storage";

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
            fill={colors.bg}
            opacity={0.78}
            mask="url(#ovalMask)"
          />
          {/* Oval contour — 1px ecru stroke, sparse dash */}
          <Ellipse
            cx={SCREEN_W / 2}
            cy={SCREEN_H / 2 - 40}
            rx={SCREEN_W * 0.36}
            ry={SCREEN_H * 0.26}
            stroke={colors.fg}
            strokeWidth={1}
            strokeDasharray="3 8"
            fill="transparent"
            opacity={0.55}
          />
          {GRAIN_DOTS.map((g, i) => (
            <Circle
              key={i}
              cx={g.x * SCREEN_W}
              cy={g.y * SCREEN_H}
              r={g.r}
              fill={colors.fg}
              opacity={0.025}
            />
          ))}
        </Svg>
      </View>

      {/* Top bar */}
      <View style={styles.topBar} pointerEvents="box-none">
        <TouchableOpacity
          testID="camera-close-btn"
          onPress={() => router.back()}
          style={styles.closeBtn}
        >
          <Text style={styles.closeText}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>Bilan</Text>
        <View style={{ width: 36 }} />
      </View>

      {/* Retake notice */}
      {retake === "no_face" ? (
        <View style={styles.notice} testID="camera-retake-notice">
          <Text style={styles.noticeText}>
            Aucun visage détecté — placez votre visage dans l'ovale et reprenez la photo.
          </Text>
        </View>
      ) : null}

      {/* Bottom controls */}
      <View style={styles.bottomBar} pointerEvents="box-none">
        <Text style={styles.guide}>
          {"Placez votre visage\nau centre de l'ovale."}
        </Text>

        <View style={styles.bottomRow}>
          <TouchableOpacity
            testID="camera-gallery-btn"
            onPress={pickFromGallery}
            style={styles.galleryBtn}
            activeOpacity={0.7}
          >
            <Text style={styles.galleryText}>GALERIE</Text>
          </TouchableOpacity>

          <TouchableOpacity
            testID="camera-capture-btn"
            activeOpacity={0.7}
            onPress={capture}
            style={styles.captureOuter}
            disabled={canUseCamera ? !ready : false}
          >
            <View style={styles.captureInner} />
          </TouchableOpacity>

          <View style={{ width: 72 }} />
        </View>

        <Text style={styles.hint}>Appuyez pour démarrer l'analyse</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  cameraWrap: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.bg },
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#111111",
  },
  placeholderText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
    lineHeight: 22,
  },
  permBtn: {
    marginTop: spacing.l,
    borderWidth: 1,
    borderColor: colors.borderActive,
    paddingHorizontal: 28,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  permBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
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
  closeBtn: { padding: 4, width: 36 },
  closeText: { color: colors.fg, fontSize: 20, fontFamily: fonts.body },
  topTitle: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
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
    borderColor: colors.borderMid,
    paddingVertical: 12,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.fgFaint,
    borderRadius: radius.sm,
  },
  noticeText: {
    fontFamily: fonts.body,
    color: colors.fg,
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
    fontFamily: fonts.headingItalic,
    color: colors.fg,
    fontSize: 18,
    textAlign: "center",
    marginBottom: spacing.l,
    lineHeight: 26,
    opacity: 0.9,
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
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    alignItems: "center",
    backgroundColor: "rgba(20, 18, 16, 0.7)",
  },
  galleryText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 9,
    letterSpacing: 2,
  },
  captureOuter: {
    width: 80,
    height: 80,
    borderRadius: 40,
    borderWidth: 1,
    borderColor: colors.fg,
    alignItems: "center",
    justifyContent: "center",
  },
  captureInner: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: colors.fg,
  },
  hint: {
    marginTop: spacing.m,
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
