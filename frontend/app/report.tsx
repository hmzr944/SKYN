import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Dimensions,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Svg, { Circle } from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedProps,
  withTiming,
  Easing,
  withSpring,
  useAnimatedStyle,
  withDelay,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api } from "@/src/services/api";
import { storage } from "@/src/utils/storage";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);
const { width: SCREEN_W } = Dimensions.get("window");
const RING = Math.min(SCREEN_W - spacing.xl * 2, 240);
const STROKE = 6;
const R = (RING - STROKE) / 2;
const CIRC = 2 * Math.PI * R;

function ScoreRing({ value }: { value: number }) {
  const progress = useSharedValue(0);
  const display = useSharedValue(0);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    progress.value = withTiming(value / 100, {
      duration: 1800,
      easing: Easing.out(Easing.cubic),
    });
    display.value = withTiming(value, { duration: 1800 });
    const id = setInterval(() => setShown(Math.round(display.value)), 32);
    setTimeout(() => clearInterval(id), 2000);
    return () => clearInterval(id);
  }, [value, progress, display]);

  const animProps = useAnimatedProps(() => ({
    strokeDashoffset: CIRC * (1 - progress.value),
  }));

  return (
    <View style={{ width: RING, height: RING, alignItems: "center", justifyContent: "center" }}>
      <Svg width={RING} height={RING}>
        <Circle
          cx={RING / 2}
          cy={RING / 2}
          r={R}
          stroke={colors.borderSubtle}
          strokeWidth={STROKE}
          fill="transparent"
        />
        <AnimatedCircle
          cx={RING / 2}
          cy={RING / 2}
          r={R}
          stroke={colors.accent}
          strokeWidth={STROKE}
          fill="transparent"
          strokeDasharray={`${CIRC} ${CIRC}`}
          animatedProps={animProps}
          strokeLinecap="round"
          transform={`rotate(-90, ${RING / 2}, ${RING / 2})`}
        />
      </Svg>
      <View style={styles.ringCenter}>
        <Text style={styles.ringEyebrow}>SCORE GLOBAL</Text>
        <Text style={styles.ringValue} testID="report-global-score">
          {shown}
        </Text>
        <Text style={styles.ringUnit}>sur 100</Text>
      </View>
    </View>
  );
}

function MetricCell({
  label,
  value,
  variant,
  delay,
}: {
  label: string;
  value: number;
  variant: "tall" | "small";
  delay: number;
}) {
  const sv = useSharedValue(0);
  useEffect(() => {
    sv.value = withDelay(delay, withSpring(1, { damping: 16, stiffness: 90 }));
  }, [sv, delay]);
  const aStyle = useAnimatedStyle(() => ({
    opacity: sv.value,
    transform: [{ translateY: (1 - sv.value) * 12 }],
  }));
  return (
    <Animated.View style={[styles.metricCell, styles[variant], aStyle]}>
      <View
        style={[
          styles.metricDot,
          { backgroundColor: value > 70 ? colors.lime : colors.accent },
        ]}
      />
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </Animated.View>
  );
}

export default function ReportScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [lowLight, setLowLight] = useState(false);

  const sheetY = useSharedValue(1);

  useEffect(() => {
    (async () => {
      try {
        if (id) {
          const r = await api.getReport(id);
          setReport(r);
        } else {
          const list = await api.listReports();
          setReport(list[0] || null);
        }
      } finally {
        setLoading(false);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      }
    })();

    (async () => {
      const flag = (await storage.getItem("skyn_last_low_light", "")) as string;
      if (flag === "1") {
        setLowLight(true);
        await storage.setItem("skyn_last_low_light", "");
      }
    })();
  }, [id]);

  const toggleSheet = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    sheetY.value = withTiming(sheetOpen ? 1 : 0, {
      duration: 420,
      easing: Easing.out(Easing.cubic),
    });
    setSheetOpen((s) => !s);
  };

  const sheetStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: sheetY.value * 480 }],
  }));

  const handleFinish = () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    router.replace("/dashboard");
  };

  if (loading) {
    return (
      <SafeAreaView style={[styles.container, styles.center]} edges={["top", "bottom"]}>
        <ActivityIndicator color={colors.fgMuted} />
      </SafeAreaView>
    );
  }

  if (!report) {
    return (
      <SafeAreaView style={[styles.container, styles.center]} edges={["top", "bottom"]}>
        <Text style={styles.empty}>Aucun rapport disponible.</Text>
        <TouchableOpacity onPress={() => router.replace("/dashboard")} style={styles.linkBackBtn}>
          <Text style={styles.linkBack}>← Retour au tableau de bord</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Top bar */}
      <View style={styles.topBar}>
        <TouchableOpacity onPress={handleFinish} style={styles.topBackBtn}>
          <Text style={styles.topBackText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>Bilan Clinique</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <FadeIn>
          <Text style={styles.dateTop}>
            {new Date(report.created_at).toLocaleDateString("fr-FR", {
              day: "2-digit",
              month: "long",
              year: "numeric",
            })}
          </Text>
        </FadeIn>

        {lowLight ? (
          <FadeIn distance={6}>
            <View style={styles.lowLightBanner} testID="report-low-light-notice">
              <Text style={styles.lowLightText}>
                Luminosité faible détectée lors de la prise de vue — pour un bilan plus précis, refaites le test dans un environnement bien éclairé.
              </Text>
            </View>
          </FadeIn>
        ) : null}

        {report.diagnosis ? (
          <FadeIn delay={60}>
            <Text style={styles.diagnosis} testID="report-diagnosis">
              {report.diagnosis}
            </Text>
          </FadeIn>
        ) : null}

        <FadeIn delay={100} distance={20}>
          <View style={styles.ringWrap}>
            <ScoreRing value={report.global_score} />
          </View>
        </FadeIn>

        {/* Asymmetric metric grid */}
        <View style={styles.gridWrap}>
          <View style={styles.row1}>
            <MetricCell
              label="Texture"
              value={report.texture}
              variant="tall"
              delay={150}
            />
            <View style={styles.column}>
              <MetricCell
                label="Éclat"
                value={report.radiance}
                variant="small"
                delay={300}
              />
              <MetricCell
                label="Imperfections"
                value={report.imperfections}
                variant="small"
                delay={450}
              />
            </View>
          </View>
        </View>

        {/* Recommendations trigger */}
        <AnimatedPressable
          testID="report-recos-toggle"
          style={styles.recoTrigger}
          onPress={toggleSheet}
          scaleTo={0.98}
        >
          <Text style={styles.recoTriggerText}>
            {sheetOpen ? "Masquer les recommandations" : "Voir les recommandations"}
          </Text>
          <Text style={styles.recoArrow}>{sheetOpen ? "↓" : "↑"}</Text>
        </AnimatedPressable>

        <View style={{ height: 120 }} />
      </ScrollView>

      {/* Finish button */}
      <AnimatedPressable
        testID="report-finish-btn"
        style={styles.finishBtn}
        onPress={handleFinish}
      >
        <Text style={styles.finishText}>Terminer et Sauvegarder</Text>
      </AnimatedPressable>

      {/* Recommendations sheet */}
      <Animated.View
        style={[styles.sheet, sheetStyle]}
        pointerEvents={sheetOpen ? "auto" : "none"}
      >
        <View style={styles.sheetHandleWrap}>
          <View style={styles.handleBar} />
        </View>
        <Text style={styles.sheetTitle}>Recommandations</Text>
        <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
          {(report.recommendations || []).map((r: string, i: number) => (
            <FadeIn key={i} delay={i * 60} distance={8}>
              <View style={styles.recoItem} testID={`reco-item-${i}`}>
                <Text style={styles.recoIdx}>0{i + 1}</Text>
                <Text style={styles.recoText}>{r}</Text>
              </View>
            </FadeIn>
          ))}
        </ScrollView>
        <AnimatedPressable
          onPress={toggleSheet}
          style={styles.sheetClose}
          testID="report-sheet-close"
          scaleTo={0.96}
        >
          <Text style={styles.sheetCloseText}>Fermer</Text>
        </AnimatedPressable>
      </Animated.View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  empty: {
    color: colors.fgMuted,
    fontFamily: fonts.body,
    fontSize: 15,
    marginBottom: spacing.m,
  },
  linkBackBtn: { marginTop: spacing.s },
  linkBack: {
    color: colors.fgMuted,
    fontFamily: fonts.body,
    fontSize: 13,
    letterSpacing: 0.5,
  },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.m,
  },
  topBackBtn: { width: 40, paddingVertical: 4 },
  topBackText: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 20,
  },
  topTitle: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    letterSpacing: 3,
    fontSize: 11,
    textTransform: "uppercase",
  },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxl },
  dateTop: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 2,
    textAlign: "center",
    textTransform: "uppercase",
    marginTop: spacing.s,
  },
  diagnosis: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 18,
    textAlign: "center",
    marginTop: spacing.m,
    paddingHorizontal: spacing.l,
    letterSpacing: 0.5,
    lineHeight: 26,
  },
  lowLightBanner: {
    marginTop: spacing.m,
    marginHorizontal: spacing.l,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: 12,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.accentSofter,
    borderRadius: radius.sm,
  },
  lowLightText: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    lineHeight: 18,
    letterSpacing: 0.3,
    textAlign: "center",
  },
  ringWrap: {
    alignItems: "center",
    marginTop: spacing.l,
    marginBottom: spacing.xl,
  },
  ringCenter: { position: "absolute", alignItems: "center" },
  ringEyebrow: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 9,
    letterSpacing: 3,
    textTransform: "uppercase",
  },
  ringValue: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 80,
    letterSpacing: -3,
    lineHeight: 86,
  },
  ringUnit: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  gridWrap: { marginTop: spacing.m },
  row1: { flexDirection: "row", gap: spacing.s },
  column: { flex: 1, gap: spacing.s },
  metricCell: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.md,
    padding: spacing.m,
    justifyContent: "space-between",
    ...shadow.card,
  },
  metricDot: {
    position: "absolute",
    top: spacing.m,
    right: spacing.m,
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  tall: { flex: 1, minHeight: 200 },
  small: { flex: 1, minHeight: 96 },
  metricLabel: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 10,
    letterSpacing: 3,
    textTransform: "uppercase",
  },
  metricValue: {
    fontFamily: fonts.heading,
    color: colors.accent,
    fontSize: 48,
    letterSpacing: -1,
  },
  recoTrigger: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.s,
    paddingVertical: spacing.l,
    marginTop: spacing.m,
  },
  recoTriggerText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  recoArrow: {
    color: colors.fgMuted,
    fontSize: 16,
  },
  finishBtn: {
    position: "absolute",
    bottom: 28,
    left: spacing.xl,
    right: spacing.xl,
    backgroundColor: colors.bg,
    paddingVertical: 18,
    alignItems: "center",
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.accent,
  },
  finishText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 13,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  sheet: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    height: 480,
    backgroundColor: colors.surfaceRaised,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.l,
    ...shadow.raised,
  },
  sheetHandleWrap: { alignItems: "center", marginBottom: spacing.m },
  handleBar: {
    width: 36,
    height: 4,
    backgroundColor: colors.borderMid,
    borderRadius: 2,
  },
  sheetTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 26,
    letterSpacing: -0.5,
    marginBottom: spacing.m,
  },
  recoItem: {
    flexDirection: "row",
    paddingVertical: spacing.m,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
    gap: spacing.m,
  },
  recoIdx: {
    fontFamily: fonts.heading,
    color: colors.accent,
    opacity: 0.2,
    fontSize: 32,
    width: 40,
    lineHeight: 36,
  },
  recoText: {
    flex: 1,
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 14,
    lineHeight: 22,
  },
  sheetClose: {
    marginTop: spacing.m,
    alignSelf: "center",
    paddingVertical: 12,
    paddingHorizontal: 32,
    borderWidth: 1.5,
    borderColor: colors.accent,
    borderRadius: radius.pill,
  },
  sheetCloseText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
