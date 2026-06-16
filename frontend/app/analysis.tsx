import React, { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Dimensions, Image } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";
import Svg, { Circle, Ellipse, Line, Path } from "react-native-svg";

import { colors, fonts, spacing } from "@/src/theme";
import { api, queuePendingReport } from "@/src/services/api";
import { pushReportToSupabase } from "@/src/services/supabase";
import { storage } from "@/src/utils/storage";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";

const { width: SCREEN_W } = Dimensions.get("window");
const FRAME = SCREEN_W * 0.58;

const PHASES = [
  "Scan de surface",
  "Mapping des zones",
  "Analyse des micro-patterns",
  "Génération du rapport",
];

const STEP_LABELS = ["SURFACE", "ZONES", "PATTERNS", "RAPPORT"];

type Detection = { type: string; x: number; y: number; confidence: number; radius: number };

export default function AnalysisScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [phase, setPhase] = useState(0);
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [blackOut, setBlackOut] = useState(false);
  const scanY = useSharedValue(0);
  const thermalT = useSharedValue(0);
  const microT = useSharedValue(0);
  const compileT = useSharedValue(0);
  const hapticInt = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef<number>(Date.now());
  const analysisRef = useRef<any>(null);
  useEffect(() => {
    analysisRef.current = analysis;
  }, [analysis]);

  // Fire the analyze request as soon as we mount — runs in parallel with the
  // 7s cinematic. By phase 4 the real data is virtually always already back.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const b = (await storage.getItem("skyn_last_capture_b64", "")) as string;
      if (cancelled) return;
      if (b) setImageB64(b);
      if (b) {
        try {
          const data = await api.analyze(b);
          if (!cancelled) setAnalysis(data);
        } catch {
          /* keep null → fallback path */
        }
      }
    })();

    // Phase 1 (0-2s): surface scan + continuous gentle haptic
    scanY.value = withRepeat(
      withTiming(1, { duration: 1100, easing: Easing.inOut(Easing.ease) }),
      -1,
      true,
    );
    hapticInt.current = setInterval(() => Haptics.selectionAsync(), 240);

    const t1 = setTimeout(() => {
      if (hapticInt.current) clearInterval(hapticInt.current);
      setPhase(1);
      thermalT.value = withTiming(1, { duration: 900 });
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      setTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium), 350);
      setTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy), 700);
    }, 2000);

    const t2 = setTimeout(() => {
      setPhase(2);
      microT.value = withTiming(1, { duration: 1100 });
    }, 4000);

    const t3 = setTimeout(() => {
      setPhase(3);
      compileT.value = withRepeat(withTiming(1, { duration: 500 }), -1, true);
    }, 6000);

    const finalize = async () => {
      const a = analysisRef.current;

      // No face detected — don't fabricate a report, send the user back to retake.
      if (a && a.detected === false) {
        router.replace({ pathname: "/camera", params: { retake: "no_face" } });
        return;
      }

      setBlackOut(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

      // Safety fallback if SKYN Engine failed entirely
      const scores = a
        ? {
            global_score: a.global_score,
            texture: a.texture,
            radiance: a.radiance,
            imperfections: a.imperfections,
          }
        : { global_score: 70, texture: 72, radiance: 68, imperfections: 70 };

      const recs = a?.recommendations || [
        "Maintenez une protection solaire SPF 50 quotidienne.",
        "Hydratez matin et soir avec un sérum à l'acide hyaluronique.",
        "Affinez progressivement le grain de peau avec une exfoliation douce hebdomadaire.",
      ];

      const payload = {
        ...scores,
        recommendations: recs,
        diagnosis: a?.diagnosis || "",
        detections: a?.detections || [],
      };

      await storage.setItem("skyn_last_low_light", a?.low_light ? "1" : "");

      try {
        const report = await api.createReport(payload);
        pushReportToSupabase({
          id: report.id,
          user_id: user?.user_id || "",
          global_score: report.global_score,
          texture: report.texture,
          radiance: report.radiance,
          imperfections: report.imperfections,
          recommendations: report.recommendations,
          created_at: report.created_at,
        });
        router.replace(`/report?id=${report.id}`);
      } catch {
        await queuePendingReport(payload as any);
        router.replace("/dashboard");
      }
    };

    // Wait for analysis to complete OR 6.5s timeout, whichever later
    const t4 = setTimeout(() => {
      const elapsed = Date.now() - startedAt.current;
      const wait = Math.max(0, 6500 - elapsed);
      setTimeout(finalize, wait);
    }, 6500);

    return () => {
      cancelled = true;
      if (hapticInt.current) clearInterval(hapticInt.current);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Trigger random haptics when detections become available during phase 2
  useEffect(() => {
    if (phase !== 2 || !analysis?.detections?.length) return;
    analysis.detections.forEach((_: Detection, i: number) => {
      setTimeout(
        () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light),
        i * 320 + 80,
      );
    });
  }, [phase, analysis]);

  const scanStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: scanY.value * FRAME }],
  }));
  const thermalStyle = useAnimatedStyle(() => ({ opacity: thermalT.value }));
  const microStyle = useAnimatedStyle(() => ({ opacity: microT.value }));
  const compileStyle = useAnimatedStyle(() => ({
    opacity: 0.4 + compileT.value * 0.6,
  }));

  const detections: Detection[] = analysis?.detections || [];

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <FadeIn distance={10}>
        <View style={styles.header}>
          <Text style={styles.eyebrow}>ANALYSE EN COURS</Text>
          <Text style={styles.phaseText} testID={`analysis-phase-${phase}`}>
            {PHASES[phase]}
          </Text>
        </View>
      </FadeIn>

      <View style={styles.body}>
      <FadeIn delay={80} distance={12}>
        <View style={styles.stepsList}>
          {STEP_LABELS.map((label, i) => {
            const done = i < phase;
            const active = i === phase;
            return (
              <View key={label} style={styles.stepRow}>
                <View
                  style={[
                    styles.stepDot,
                    done && styles.stepDotDone,
                    active && styles.stepDotActive,
                  ]}
                >
                  {done ? (
                    <Svg width={10} height={10} viewBox="0 0 10 10">
                      <Path
                        d="M2 5 L4.2 7.2 L8 2.5"
                        stroke={colors.onLime}
                        strokeWidth={1.5}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    </Svg>
                  ) : null}
                </View>
                <Text
                  style={[
                    styles.stepLabel,
                    done && styles.stepLabelDone,
                    active && styles.stepLabelActive,
                  ]}
                >
                  {label}
                </Text>
              </View>
            );
          })}
        </View>
      </FadeIn>

      <FadeIn delay={120} distance={20}>
      <View style={[styles.frame, { width: FRAME, height: FRAME }]}>
        {imageB64 ? (
          <Image
            source={{ uri: `data:image/jpeg;base64,${imageB64}` }}
            style={[StyleSheet.absoluteFill, styles.bwImage]}
            resizeMode="cover"
          />
        ) : (
          <View style={[StyleSheet.absoluteFill, styles.placeholder]} />
        )}
        <View style={[StyleSheet.absoluteFill, styles.bwTint]} pointerEvents="none" />

        <Svg width={FRAME} height={FRAME} style={StyleSheet.absoluteFill}>
          <Ellipse
            cx={FRAME / 2}
            cy={FRAME / 2}
            rx={FRAME * 0.42}
            ry={FRAME * 0.48}
            stroke={colors.accent}
            strokeWidth={1.5}
            strokeDasharray="3 6"
            fill="transparent"
          />
        </Svg>

        {phase === 0 ? (
          <Animated.View style={[styles.scanLine, scanStyle]}>
            <View style={styles.scanLineBar} />
          </Animated.View>
        ) : null}

        {phase === 1 ? (
          <Animated.View style={[StyleSheet.absoluteFill, thermalStyle]} pointerEvents="none">
            <Svg width={FRAME} height={FRAME}>
              <Line x1={FRAME * 0.3} y1={FRAME * 0.32} x2={FRAME * 0.7} y2={FRAME * 0.32} stroke={colors.accent} strokeWidth={1} />
              <Line x1={FRAME * 0.5} y1={FRAME * 0.32} x2={FRAME * 0.5} y2={FRAME * 0.62} stroke={colors.accent} strokeWidth={1} />
              <Line x1={FRAME * 0.42} y1={FRAME * 0.78} x2={FRAME * 0.58} y2={FRAME * 0.78} stroke={colors.accent} strokeWidth={1} />
              <Ellipse cx={FRAME * 0.3} cy={FRAME * 0.58} rx={FRAME * 0.1} ry={FRAME * 0.08} stroke={colors.accent} strokeWidth={1} fill="transparent" />
              <Ellipse cx={FRAME * 0.7} cy={FRAME * 0.58} rx={FRAME * 0.1} ry={FRAME * 0.08} stroke={colors.accent} strokeWidth={1} fill="transparent" />
            </Svg>
          </Animated.View>
        ) : null}

        {phase === 2 ? (
          <Animated.View style={[StyleSheet.absoluteFill, microStyle]} pointerEvents="none">
            <Svg width={FRAME} height={FRAME}>
              {(detections.length > 0
                ? detections
                : // Fallback dummy positions if analysis not back yet
                  [
                    { x: 0.32, y: 0.32, radius: 0.05 },
                    { x: 0.66, y: 0.34, radius: 0.04 },
                    { x: 0.5, y: 0.55, radius: 0.05 },
                    { x: 0.6, y: 0.7, radius: 0.035 },
                  ]
              ).map((d: any, i: number) => {
                const cx = d.x * FRAME;
                const cy = d.y * FRAME;
                const r = Math.max(6, (d.radius || 0.04) * FRAME * 1.4);
                return (
                  <React.Fragment key={i}>
                    <Circle cx={cx} cy={cy} r={r} stroke={colors.accent} strokeWidth={1} fill="transparent" />
                    <Circle cx={cx} cy={cy} r={1.5} fill={colors.accent} />
                  </React.Fragment>
                );
              })}
            </Svg>
          </Animated.View>
        ) : null}

        {phase === 3 ? (
          <Animated.View style={[styles.compile, compileStyle]}>
            <Text style={styles.compileText}>Compilation…</Text>
          </Animated.View>
        ) : null}
      </View>
      </FadeIn>
      </View>

      <View style={styles.footer}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${((phase + 1) / 4) * 100}%` }]} />
        </View>
        <Text style={styles.progressLabel}>
          0{phase + 1} / 04 — Veuillez ne pas bouger
        </Text>
      </View>

      {blackOut ? (
        <View style={styles.blackOut} pointerEvents="auto" testID="analysis-blackout" />
      ) : null}
    </SafeAreaView>
  );
}

// React import for Fragment

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "space-between",
    alignItems: "center",
    paddingTop: spacing.xl,
  },
  header: { alignItems: "center", paddingTop: spacing.l },
  body: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.l,
    paddingHorizontal: spacing.l,
  },
  stepsList: { gap: spacing.l },
  stepRow: { flexDirection: "row", alignItems: "center", gap: spacing.s },
  stepDot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 1.5,
    borderColor: "rgba(45,31,26,0.2)",
    alignItems: "center",
    justifyContent: "center",
  },
  stepDotActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accent,
  },
  stepDotDone: {
    borderColor: colors.lime,
    backgroundColor: colors.lime,
  },
  stepLabel: {
    fontFamily: fonts.bodyMedium,
    color: "rgba(45,31,26,0.2)",
    fontSize: 11,
    letterSpacing: 2,
  },
  stepLabelActive: { color: colors.accent },
  stepLabelDone: { color: colors.fg },
  eyebrow: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgMuted,
    fontSize: 10,
    letterSpacing: 4,
  },
  phaseText: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 26,
    marginTop: spacing.s,
    letterSpacing: -0.5,
    textAlign: "center",
  },
  frame: {
    position: "relative",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  bwImage: { opacity: 0.6 },
  bwTint: { backgroundColor: "rgba(45,31,26,0.25)" },
  placeholder: { backgroundColor: colors.surfaceSunken },
  scanLine: { position: "absolute", left: 0, right: 0, top: 0, alignItems: "center" },
  scanLineBar: { width: "94%", height: 2, backgroundColor: colors.accent, opacity: 0.95 },
  compile: { position: "absolute" },
  compileText: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 20,
    letterSpacing: 1,
  },
  footer: { width: "100%", paddingHorizontal: spacing.xl, paddingBottom: spacing.xl, alignItems: "center" },
  progressTrack: { width: "100%", height: 2, backgroundColor: colors.borderSubtle, borderRadius: 1 },
  progressFill: { height: 2, backgroundColor: colors.accent, borderRadius: 1 },
  progressLabel: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 10,
    letterSpacing: 2,
    marginTop: spacing.m,
    textTransform: "uppercase",
  },
  blackOut: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.bg },
});
