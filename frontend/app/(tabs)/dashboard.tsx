import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Dimensions, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Svg, { Polyline, Circle, Defs, LinearGradient as SvgLinearGradient, Stop, Polygon, Path } from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  withDelay,
  withRepeat,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api, syncPendingReports } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const { width: SCREEN_W } = Dimensions.get("window");
const CHART_W = SCREEN_W - spacing.xl * 2;
const CHART_H = 96;

// Accompagnement : un focus concret selon la métrique la plus faible du dernier bilan
const FOCUS_INFO: Record<string, { label: string; tip: string }> = {
  texture: {
    label: "Votre grain de peau",
    tip: "C'est votre point le plus perfectible en ce moment. Une exfoliation douce (AHA/PHA) deux soirs par semaine affinera progressivement la surface.",
  },
  radiance: {
    label: "Votre éclat",
    tip: "C'est votre point le plus perfectible en ce moment. Vitamine C le matin, hydratation renforcée et sommeil régulier raviveront votre teint.",
  },
  imperfections: {
    label: "Vos imperfections",
    tip: "C'est votre point le plus perfectible en ce moment. Niacinamide le soir, et surtout de la constance : les résultats se voient en 4 à 6 semaines.",
  },
};

const TIPS = [
  "Hydratez votre peau matin et soir avec une crème adaptée à votre type de peau.",
  "Appliquez une protection solaire SPF 30+ chaque matin, même par temps couvert.",
  "Buvez au moins 1,5L d'eau par jour pour soutenir l'hydratation cutanée.",
  "Évitez de toucher votre visage pour limiter le transfert de bactéries.",
  "Démaquillez-vous systématiquement avant de dormir.",
  "Privilégiez un nettoyant doux, sans sulfates agressifs.",
];

/** Grand chiffre animé — le score compte de 0 jusqu'à sa valeur, comme un
 * compteur de tableau de bord, pour un vrai effet de "révélation" au lieu
 * d'un texte statique. */
function CountUpNumber({
  value,
  style,
  testID,
}: {
  value: number;
  style?: any;
  testID?: string;
}) {
  const [shown, setShown] = useState(0);
  const sv = useSharedValue(0);
  useEffect(() => {
    sv.value = 0;
    sv.value = withTiming(value, { duration: 1100, easing: Easing.out(Easing.cubic) });
    const id = setInterval(() => setShown(Math.round(sv.value)), 30);
    const stop = setTimeout(() => {
      clearInterval(id);
      setShown(value);
    }, 1200);
    return () => {
      clearInterval(id);
      clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Text style={style} testID={testID}>
      {shown}
    </Text>
  );
}

function ScoreChart({ scores }: { scores: number[] }) {
  const padX = 6;
  const padY = 14;
  const innerW = CHART_W - padX * 2;
  const innerH = CHART_H - padY * 2;
  if (scores.length === 0) {
    return (
      <View style={[styles.chartEmpty, { width: CHART_W, height: CHART_H }]}>
        <View style={styles.chartEmptyDots}>
          {[0, 1, 2, 3].map((i) => (
            <View key={i} style={styles.chartEmptyDot} />
          ))}
        </View>
        <Text style={styles.chartEmptyText}>La courbe apparaîtra dès votre 2ᵉ bilan.</Text>
      </View>
    );
  }
  const min = Math.min(...scores, 50);
  const max = Math.max(...scores, 100);
  const range = Math.max(1, max - min);
  const step = scores.length > 1 ? innerW / (scores.length - 1) : 0;
  const pt = (s: number, i: number) => ({
    x: padX + i * step,
    y: padY + innerH - ((s - min) / range) * innerH,
  });
  const points = scores.map(pt);
  const linePoints = points.map((p) => `${p.x},${p.y}`).join(" ");
  const areaPoints =
    `${padX},${padY + innerH} ` + linePoints + ` ${padX + (scores.length - 1) * step},${padY + innerH}`;
  return (
    <Svg width={CHART_W} height={CHART_H}>
      <Defs>
        <SvgLinearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={colors.lime} stopOpacity={0.4} />
          <Stop offset="1" stopColor={colors.lime} stopOpacity={0} />
        </SvgLinearGradient>
      </Defs>
      <Polygon points={areaPoints} fill="url(#areaFill)" />
      <Polyline
        points={linePoints}
        fill="none"
        stroke={colors.fg}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {points.map((p, i) => (
        <Circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={i === points.length - 1 ? 5 : 3.5}
          fill={i === points.length - 1 ? colors.accent : colors.surfaceRaised}
          stroke={i === points.length - 1 ? colors.surfaceRaised : colors.fg}
          strokeWidth={2}
        />
      ))}
    </Svg>
  );
}

/** Bandeau décoratif du haut — un lavis chaud, signature visuelle propre au
 * Dashboard (aucun autre écran ne réutilise cette composition). */
function HeaderWash() {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withRepeat(withTiming(1, { duration: 7000, easing: Easing.inOut(Easing.sin) }), -1, true);
  }, [t]);
  const style = useAnimatedStyle(() => ({
    transform: [{ translateX: t.value * 14 }, { translateY: t.value * -8 }],
  }));
  return (
    <View style={styles.headerWash} pointerEvents="none">
      <Animated.View style={[styles.washBlobA, style]} />
      <View style={styles.washBlobB} />
    </View>
  );
}

const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function todayLabel() {
  const d = new Date();
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
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
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  const last = reports[0];
  const prev = reports[1];
  const chartScores = [...reports].reverse().slice(-5).map((r) => r.global_score);
  const firstName = (user?.name || "Vous").split(" ")[0];
  const dayIndex = new Date().getDate();
  const tips = [TIPS[dayIndex % TIPS.length], TIPS[(dayIndex + 1) % TIPS.length]];

  const delta = last && prev ? last.global_score - prev.global_score : null;
  const focusKey = last
    ? (["texture", "radiance", "imperfections"] as const).reduce((a, b) =>
        last[a] <= last[b] ? a : b,
      )
    : null;
  const daysSinceScan = last
    ? Math.floor((Date.now() - new Date(last.created_at).getTime()) / 86400000)
    : null;
  const nextScanIn = daysSinceScan !== null ? Math.max(0, 7 - daysSinceScan) : null;

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <HeaderWash />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Header — signature du Dashboard : logo discret, prénom en très grand */}
        <FadeIn distance={10}>
          <Text style={styles.logo}>SKYN</Text>
          <Text style={styles.greeting} numberOfLines={1}>
            Bonjour {firstName}
          </Text>
          <View style={styles.dateStamp}>
            <View style={styles.dateStampDot} />
            <Text style={styles.date}>{todayLabel()}</Text>
          </View>
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
              <View style={styles.heroGlyph}>
                <Svg width={44} height={44} viewBox="0 0 44 44">
                  <Circle cx={22} cy={18} r={13} stroke={colors.onAccent} strokeWidth={1.4} fill="none" />
                  <Path d="M12 34 C12 26 32 26 32 34" stroke={colors.onAccent} strokeWidth={1.4} fill="none" strokeLinecap="round" />
                </Svg>
              </View>
              <Text style={styles.heroTitle}>{"Prête pour votre\npremière analyse ?"}</Text>
              <Text style={styles.heroSubtitle}>
                Découvrez l'état réel de votre peau en 3 prises guidées.
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
          <>
            {/* Score — moment éditorial : le chiffre EST la mise en page,
                pas enfermé dans une carte comme le reste de l'app. */}
            <FadeIn delay={80}>
              <View style={styles.scoreZone}>
                <Text style={styles.scoreLabel}>
                  DERNIER SCAN · {new Date(last.created_at).toLocaleDateString("fr-FR", {
                    day: "2-digit",
                    month: "long",
                  })}
                </Text>
                <View style={styles.scoreRow}>
                  <CountUpNumber value={last.global_score} style={styles.scoreValue} testID="dashboard-score" />
                  <View style={styles.scoreRightCol}>
                    <Text style={styles.scoreMax}>/ 100</Text>
                    {delta !== null && delta !== 0 ? (
                      <View style={[styles.trendChip, delta > 0 ? styles.trendUp : styles.trendDown]}>
                        <Text style={styles.trendText} testID="dashboard-trend">
                          {delta > 0 ? "↑" : "↓"} {delta > 0 ? "+" : ""}{delta}
                        </Text>
                      </View>
                    ) : null}
                  </View>
                </View>
                <View style={styles.metricsRow}>
                  <View style={styles.metricItem}>
                    <Text style={styles.metricValue}>{last.texture}</Text>
                    <Text style={styles.metricLabel}>Texture</Text>
                  </View>
                  <View style={styles.metricDivider} />
                  <View style={styles.metricItem}>
                    <Text style={styles.metricValue}>{last.radiance}</Text>
                    <Text style={styles.metricLabel}>Éclat</Text>
                  </View>
                  <View style={styles.metricDivider} />
                  <View style={styles.metricItem}>
                    <Text style={styles.metricValue}>{last.imperfections}</Text>
                    <Text style={styles.metricLabel}>Imperf.</Text>
                  </View>
                </View>
              </View>
            </FadeIn>

            {/* Focus — traité comme une note surlignée au marqueur, pas une carte */}
            {focusKey ? (
              <FadeIn delay={140}>
                <View style={styles.focusZone} testID="dashboard-focus">
                  <View style={styles.focusMarkerWrap}>
                    <View style={styles.focusMarker} />
                    <Text style={styles.focusEyebrow}>VOTRE FOCUS</Text>
                  </View>
                  <Text style={styles.focusTitle}>
                    {FOCUS_INFO[focusKey].label} <Text style={styles.focusScore}>· {last[focusKey]}/100</Text>
                  </Text>
                  <Text style={styles.focusTip}>{FOCUS_INFO[focusKey].tip}</Text>
                </View>
              </FadeIn>
            ) : null}

            {/* Évolution */}
            {reports.length > 0 ? (
              <FadeIn delay={200}>
                <View style={styles.chartZone}>
                  <View style={styles.chartHeaderRow}>
                    <Text style={styles.chartLabel}>ÉVOLUTION</Text>
                    <View style={styles.chartLegendDot} />
                  </View>
                  <ScoreChart scores={chartScores} />
                  {nextScanIn !== null ? (
                    <Text style={styles.nextScan} testID="dashboard-next-scan">
                      {nextScanIn === 0
                        ? "C'est le moment idéal pour un nouveau bilan."
                        : `Prochain bilan conseillé dans ${nextScanIn} jour${nextScanIn > 1 ? "s" : ""}.`}
                    </Text>
                  ) : null}
                </View>
              </FadeIn>
            ) : null}
          </>
        )}

        {/* Conseils du jour — pile de fiches légèrement tournées */}
        <FadeIn delay={260}>
          <Text style={styles.sectionTitle}>Conseils du jour</Text>
        </FadeIn>
        <FadeIn delay={300}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.tipsRow}
          >
            {tips.map((tip, i) => (
              <View
                key={i}
                style={[
                  styles.tipCard,
                  { transform: [{ rotate: i % 2 === 0 ? "-1.2deg" : "1deg" }] },
                ]}
              >
                <Text style={styles.tipNumber}>{String(i + 1).padStart(2, "0")}</Text>
                <Text style={styles.tipText}>{tip}</Text>
              </View>
            ))}
          </ScrollView>
        </FadeIn>

        {last ? (
          <FadeIn delay={340}>
            <AnimatedPressable
              testID="dashboard-new-scan-btn"
              style={styles.cta}
              onPress={goScan}
            >
              <Text style={styles.ctaText}>Analyser ma peau</Text>
              <Text style={styles.ctaArrow}>→</Text>
            </AnimatedPressable>
          </FadeIn>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  headerWash: { position: "absolute", top: 0, left: 0, right: 0, height: 260, overflow: "hidden" },
  washBlobA: {
    position: "absolute",
    top: -70,
    right: -60,
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: colors.accentSofter,
  },
  washBlobB: {
    position: "absolute",
    top: 40,
    left: -80,
    width: 160,
    height: 160,
    borderRadius: 80,
    backgroundColor: colors.limeSofter,
  },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.xxl,
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 14,
    color: colors.accent,
    letterSpacing: 5,
  },
  greeting: {
    fontFamily: fonts.heading,
    fontSize: 40,
    lineHeight: 44,
    color: colors.fg,
    letterSpacing: -1,
    marginTop: spacing.xs,
  },
  dateStamp: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 8,
    marginBottom: spacing.l,
  },
  dateStampDot: { width: 5, height: 5, borderRadius: 2.5, backgroundColor: colors.lime },
  date: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    letterSpacing: 2,
    color: colors.fgMuted,
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
    ...shadow.button,
  },
  heroGlyph: {
    width: 44,
    height: 44,
    marginBottom: spacing.m,
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
    color: "rgba(255,248,242,0.82)",
    marginBottom: spacing.l,
    lineHeight: 20,
  },
  heroBtn: {
    alignSelf: "flex-start",
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.l,
    height: 44,
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

  // Score — pas de carte : le chiffre porte la mise en page
  scoreZone: { marginBottom: spacing.xl },
  scoreLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 2,
    color: colors.fgDim,
    textTransform: "uppercase",
    marginBottom: 4,
  },
  scoreRow: { flexDirection: "row", alignItems: "flex-end" },
  scoreValue: {
    fontFamily: fonts.heading,
    fontSize: 92,
    lineHeight: 92,
    color: colors.fg,
    letterSpacing: -3,
  },
  scoreRightCol: { marginLeft: spacing.s, marginBottom: 14, gap: 6 },
  scoreMax: {
    fontFamily: fonts.body,
    fontSize: 15,
    color: colors.fgDim,
  },
  trendChip: {
    borderRadius: radius.pill,
    paddingVertical: 3,
    paddingHorizontal: 10,
    alignSelf: "flex-start",
  },
  trendUp: { backgroundColor: colors.limeSoft },
  trendDown: { backgroundColor: colors.accentSofter },
  trendText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 11,
  },
  metricsRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: spacing.m,
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.md,
    paddingVertical: spacing.m,
    ...shadow.card,
  },
  metricItem: { flex: 1, alignItems: "center" },
  metricDivider: { width: 1, height: 28, backgroundColor: colors.borderSubtle },
  metricValue: {
    fontFamily: fonts.heading,
    fontSize: 22,
    color: colors.accent,
    letterSpacing: -0.5,
  },
  metricLabel: {
    fontFamily: fonts.body,
    fontSize: 10,
    color: colors.fgMuted,
    marginTop: 2,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },

  // Focus — note surlignée, pas une carte
  focusZone: { marginBottom: spacing.xl },
  focusMarkerWrap: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 },
  focusMarker: { width: 12, height: 12, borderRadius: 3, backgroundColor: colors.lime, transform: [{ rotate: "8deg" }] },
  focusEyebrow: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 10,
    letterSpacing: 2.5,
  },
  focusTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 20,
    letterSpacing: -0.3,
    marginBottom: 6,
  },
  focusScore: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 16,
  },
  focusTip: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13.5,
    lineHeight: 20,
  },

  // Évolution
  chartZone: {
    marginBottom: spacing.xl,
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    padding: spacing.m,
    ...shadow.card,
  },
  chartHeaderRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.s },
  chartLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 2.5,
    color: colors.fgDim,
  },
  chartLegendDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.accent },
  chartWrap: { alignItems: "flex-start" },
  chartEmpty: {
    justifyContent: "center",
    alignItems: "center",
    paddingVertical: spacing.l,
    gap: spacing.s,
  },
  chartEmptyDots: { flexDirection: "row", gap: 6 },
  chartEmptyDot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: colors.borderMid,
  },
  chartEmptyText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 12,
    textAlign: "center",
    lineHeight: 18,
  },
  nextScan: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    lineHeight: 16,
    marginTop: spacing.s,
  },

  sectionTitle: {
    fontFamily: fonts.heading,
    fontSize: 20,
    color: colors.fg,
    letterSpacing: -0.3,
    marginBottom: spacing.m,
  },
  tipsRow: {
    gap: spacing.m,
    paddingBottom: spacing.xl,
    paddingRight: spacing.m,
    paddingTop: 4,
  },
  tipCard: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.md,
    padding: spacing.m,
    minWidth: 220,
    maxWidth: 240,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    ...shadow.card,
  },
  tipNumber: {
    fontFamily: fonts.heading,
    fontSize: 26,
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
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.fg,
    paddingVertical: 18,
    borderRadius: radius.pill,
    ...shadow.button,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    color: colors.bg,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  ctaArrow: { color: colors.lime, fontSize: 15 },
});
