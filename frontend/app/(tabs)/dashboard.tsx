import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Dimensions, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Svg, { Polyline, Circle, Defs, LinearGradient as SvgLinearGradient, Stop, Polygon } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api, syncPendingReports } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const { width: SCREEN_W } = Dimensions.get("window");
const CHART_W = SCREEN_W - spacing.xl * 2 - spacing.m * 2;
const CHART_H = 110;

const TIPS = [
  "Hydratez votre peau matin et soir avec une crème adaptée à votre type de peau.",
  "Appliquez une protection solaire SPF 30+ chaque matin, même par temps couvert.",
  "Buvez au moins 1,5L d'eau par jour pour soutenir l'hydratation cutanée.",
  "Évitez de toucher votre visage pour limiter le transfert de bactéries.",
  "Démaquillez-vous systématiquement avant de dormir.",
  "Privilégiez un nettoyant doux, sans sulfates agressifs.",
];

function ScoreChart({ scores }: { scores: number[] }) {
  if (scores.length === 0) {
    return (
      <View style={[styles.chartEmpty, { width: CHART_W, height: CHART_H }]}>
        <Text style={styles.chartEmptyText}>
          La courbe apparaîtra dès votre premier bilan.
        </Text>
      </View>
    );
  }
  const min = Math.min(...scores, 50);
  const max = Math.max(...scores, 100);
  const range = Math.max(1, max - min);
  const padX = 4;
  const padY = 16;
  const innerW = CHART_W - padX * 2;
  const innerH = CHART_H - padY * 2;
  const step = scores.length > 1 ? innerW / (scores.length - 1) : 0;
  const linePoints = scores
    .map(
      (s, i) =>
        `${padX + i * step},${padY + innerH - ((s - min) / range) * innerH}`,
    )
    .join(" ");
  const areaPoints =
    `${padX},${padY + innerH} ` +
    linePoints +
    ` ${padX + (scores.length - 1) * step},${padY + innerH}`;
  return (
    <Svg width={CHART_W} height={CHART_H}>
      <Defs>
        <SvgLinearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={colors.accent} stopOpacity={0.25} />
          <Stop offset="1" stopColor={colors.accent} stopOpacity={0} />
        </SvgLinearGradient>
      </Defs>
      <Polygon points={areaPoints} fill="url(#areaFill)" />
      <Polyline
        points={linePoints}
        fill="none"
        stroke={colors.accent}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {scores.map((s, i) => (
        <Circle
          key={i}
          cx={padX + i * step}
          cy={padY + innerH - ((s - min) / range) * innerH}
          r={3.5}
          fill={colors.surface}
          stroke={colors.accent}
          strokeWidth={2}
        />
      ))}
    </Svg>
  );
}

const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function todayLabel() {
  const d = new Date();
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function DashboardScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const synced = await syncPendingReports();
      if (synced > 0) {
        setSyncMsg(`${synced} bilan${synced > 1 ? "s" : ""} synchronisé${synced > 1 ? "s" : ""}.`);
        setTimeout(() => setSyncMsg(null), 3000);
      }
      const data = await api.listReports();
      setReports(data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useFocusEffect(
    useCallback(() => { load(); }, [load]),
  );

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  const last = reports[0];
  const chartScores = [...reports].reverse().slice(-4).map((r) => r.global_score);
  const firstName = (user?.name || "Vous").split(" ")[0];
  const dayIndex = new Date().getDate();
  const tips = [TIPS[dayIndex % TIPS.length], TIPS[(dayIndex + 1) % TIPS.length]];

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Header */}
        <FadeIn distance={10}>
          <View style={styles.headerRow}>
            <Text style={styles.logo}>SKYN</Text>
          </View>
          <Text style={styles.greeting} numberOfLines={1}>
            Bonjour, {firstName}.
          </Text>
          <Text style={styles.date}>{todayLabel()}</Text>
        </FadeIn>

        {syncMsg ? (
          <FadeIn distance={6}>
            <View style={styles.syncBanner}>
              <Text style={styles.syncMsg} testID="dashboard-sync-msg">
                {syncMsg}
              </Text>
            </View>
          </FadeIn>
        ) : null}

        {loading ? (
          <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.xxl }} />
        ) : !last ? (
          <FadeIn delay={80}>
            <View style={styles.heroCard}>
              <Text style={styles.heroTitle}>{"Prête pour votre\npremière analyse ?"}</Text>
              <Text style={styles.heroSubtitle}>
                Découvrez l'état réel de votre peau.
              </Text>
              <AnimatedPressable
                testID="dashboard-start-btn"
                style={styles.heroBtn}
                onPress={goScan}
              >
                <Text style={styles.heroBtnText}>Lancer l'analyse</Text>
              </AnimatedPressable>
            </View>
          </FadeIn>
        ) : (
          <FadeIn delay={80}>
            <View style={styles.scoreCard}>
              <Text style={styles.scoreLabel}>
                DERNIER SCAN ·{" "}
                {new Date(last.created_at).toLocaleDateString("fr-FR", {
                  day: "2-digit",
                  month: "long",
                })}
              </Text>
              <View style={styles.scoreRow}>
                <Text style={styles.scoreValue}>{last.global_score}</Text>
                <Text style={styles.scoreMax}>/ 100</Text>
              </View>
              <View style={styles.pillsRow}>
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>Texture</Text>
                  <Text style={styles.pillValue}>{last.texture}</Text>
                </View>
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>Éclat</Text>
                  <Text style={styles.pillValue}>{last.radiance}</Text>
                </View>
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>Imperf.</Text>
                  <Text style={styles.pillValue}>{last.imperfections}</Text>
                </View>
              </View>
            </View>
          </FadeIn>
        )}

        {/* Chart */}
        {!loading && reports.length > 0 ? (
          <FadeIn delay={140}>
            <View style={styles.chartCard}>
              <Text style={styles.chartLabel}>EVOLUTION — 4 DERNIERS SCANS</Text>
              <View style={styles.chartWrap}>
                <ScoreChart scores={chartScores} />
              </View>
            </View>
          </FadeIn>
        ) : null}

        {/* Conseils du jour */}
        <FadeIn delay={200}>
          <Text style={styles.sectionTitle}>Conseils du jour</Text>
        </FadeIn>
        <FadeIn delay={240}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.tipsRow}
          >
            {tips.map((tip, i) => (
              <View key={i} style={styles.tipCard}>
                <Text style={styles.tipNumber}>{String(i + 1).padStart(2, "0")}</Text>
                <Text style={styles.tipText}>{tip}</Text>
              </View>
            ))}
          </ScrollView>
        </FadeIn>

        {last ? (
          <FadeIn delay={300}>
            <AnimatedPressable
              testID="dashboard-new-scan-btn"
              style={styles.cta}
              onPress={goScan}
            >
              <Text style={styles.ctaText}>Analyser ma peau</Text>
            </AnimatedPressable>
          </FadeIn>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.xxl,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.l,
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 22,
    color: colors.accent,
    letterSpacing: 4,
  },
  greeting: {
    fontFamily: fonts.heading,
    fontSize: 32,
    color: colors.fg,
    letterSpacing: -0.5,
  },
  date: {
    fontFamily: fonts.body,
    fontSize: 11,
    letterSpacing: 2,
    color: colors.fgMuted,
    marginTop: 6,
    marginBottom: spacing.l,
    textTransform: "uppercase",
  },
  syncBanner: {
    marginBottom: spacing.s,
    backgroundColor: colors.limeSoft,
    borderRadius: radius.sm,
    paddingVertical: 8,
  },
  syncMsg: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 11,
    textAlign: "center",
    letterSpacing: 1.5,
  },
  heroCard: {
    backgroundColor: colors.accent,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginBottom: spacing.xl,
  },
  heroTitle: {
    fontFamily: fonts.heading,
    fontSize: 28,
    color: colors.onAccent,
    lineHeight: 34,
    marginBottom: spacing.s,
  },
  heroSubtitle: {
    fontFamily: fonts.body,
    fontSize: 14,
    color: "rgba(255,248,242,0.8)",
    marginBottom: spacing.l,
  },
  heroBtn: {
    alignSelf: "flex-start",
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.l,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  heroBtnText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  scoreCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginBottom: spacing.xl,
  },
  scoreLabel: {
    fontFamily: fonts.body,
    fontSize: 10,
    letterSpacing: 1.5,
    color: colors.fgDim,
    textTransform: "uppercase",
    marginBottom: spacing.s,
  },
  scoreRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    marginBottom: spacing.l,
  },
  scoreValue: {
    fontFamily: fonts.heading,
    fontSize: 64,
    color: colors.accent,
    letterSpacing: -1,
  },
  scoreMax: {
    fontFamily: fonts.body,
    fontSize: 16,
    color: colors.fgDim,
    marginLeft: spacing.xs,
    marginBottom: 10,
  },
  pillsRow: {
    flexDirection: "row",
    gap: spacing.s,
  },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: spacing.s,
  },
  pillDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.lime,
  },
  pillLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    color: colors.fg,
  },
  pillValue: {
    fontFamily: fonts.headingMedium,
    fontSize: 13,
    color: colors.accent,
  },
  chartCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: spacing.m,
    marginBottom: spacing.xl,
    ...shadow.card,
  },
  chartLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 3,
    color: colors.fgDim,
    marginBottom: spacing.m,
  },
  chartWrap: { alignItems: "flex-start" },
  chartEmpty: {
    justifyContent: "center",
    alignItems: "center",
    paddingVertical: spacing.l,
  },
  chartEmptyText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 12,
    textAlign: "center",
    lineHeight: 18,
  },
  sectionTitle: {
    fontFamily: fonts.heading,
    fontSize: 20,
    color: colors.fg,
    letterSpacing: -0.3,
    marginBottom: spacing.m,
  },
  tipsRow: {
    gap: spacing.s,
    paddingBottom: spacing.xl,
  },
  tipCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.m,
    minWidth: 220,
    maxWidth: 240,
  },
  tipNumber: {
    fontFamily: fonts.heading,
    fontSize: 28,
    color: colors.accentSoft,
    marginBottom: spacing.xs,
  },
  tipText: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fg,
    lineHeight: 19,
  },
  cta: {
    backgroundColor: colors.accent,
    paddingVertical: 18,
    alignItems: "center",
    borderRadius: radius.pill,
    ...shadow.button,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
