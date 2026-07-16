import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Svg, { Path } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api, syncPendingReports } from "@/src/services/api";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const FILTERS = [
  { label: "7j", days: 7 },
  { label: "30j", days: 30 },
  { label: "3 mois", days: 90 },
];

function scoreColor(score: number) {
  if (score >= 75) return colors.lime;
  if (score >= 55) return colors.accent;
  return colors.fgDim;
}

export default function HistoryScreen() {
  const router = useRouter();
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState(FILTERS[2].days);

  const load = useCallback(async () => {
    try {
      await syncPendingReports();
      const data = await api.listReports();
      setReports(data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = () => {
    setRefreshing(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    load();
  };

  const filtered = useMemo(() => {
    const cutoff = Date.now() - filter * 24 * 60 * 60 * 1000;
    return reports.filter((r) => new Date(r.created_at).getTime() >= cutoff);
  }, [reports, filter]);

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  const best = filtered.length ? Math.max(...filtered.map((r) => r.global_score)) : null;
  const avg = filtered.length
    ? Math.round(filtered.reduce((s, r) => s + r.global_score, 0) / filtered.length)
    : null;

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
      >
        <FadeIn distance={10}>
          <Text style={styles.title}>Votre parcours</Text>
        </FadeIn>

        <FadeIn delay={60}>
          <View style={styles.filterRow}>
            {FILTERS.map((f) => {
              const active = filter === f.days;
              return (
                <AnimatedPressable
                  key={f.label}
                  testID={`history-filter-${f.days}`}
                  style={[styles.filterPill, active && styles.filterPillActive]}
                  scaleTo={0.96}
                  onPress={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setFilter(f.days);
                  }}
                >
                  <Text style={[styles.filterText, active && styles.filterTextActive]}>
                    {f.label}
                  </Text>
                </AnimatedPressable>
              );
            })}
          </View>
        </FadeIn>

        {loading ? (
          <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.xxl }} />
        ) : filtered.length === 0 ? (
          <FadeIn delay={120}>
            <View style={styles.emptyWrap}>
              <Svg width={72} height={72} viewBox="0 0 72 72">
                <Path
                  d="M12 54 C12 30 60 30 60 54"
                  stroke={colors.borderMid}
                  strokeWidth={2}
                  fill="none"
                  strokeLinecap="round"
                  strokeDasharray="1 8"
                />
                <Path
                  d="M20 40 L32 50 L52 20"
                  stroke={colors.accent}
                  strokeWidth={2.5}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </Svg>
              <Text style={styles.emptyTitle}>Pas encore d'analyse</Text>
              <Text style={styles.emptyHint}>
                Chaque bilan viendra dessiner ici le fil de votre peau.
              </Text>
              <AnimatedPressable testID="history-start-btn" style={styles.emptyBtn} onPress={goScan}>
                <Text style={styles.emptyBtnText}>Commencer</Text>
              </AnimatedPressable>
            </View>
          </FadeIn>
        ) : (
          <>
            {/* Résumé de période — remplit l'espace avec du sens, pas du vide */}
            <FadeIn delay={90}>
              <View style={styles.summaryRow}>
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{filtered.length}</Text>
                  <Text style={styles.summaryLabel}>Bilans</Text>
                </View>
                <View style={styles.summaryDivider} />
                <View style={styles.summaryItem}>
                  <Text style={[styles.summaryValue, { color: colors.lime }]}>{best}</Text>
                  <Text style={styles.summaryLabel}>Meilleur</Text>
                </View>
                <View style={styles.summaryDivider} />
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{avg}</Text>
                  <Text style={styles.summaryLabel}>Moyenne</Text>
                </View>
              </View>
            </FadeIn>

            {/* Timeline verticale — identité propre à cet écran */}
            <View style={styles.timeline}>
              <View style={styles.timelineLine} pointerEvents="none" />
              {filtered.map((item, index) => (
                <FadeIn
                  key={item.id}
                  delay={140 + Math.min(index, 8) * 60}
                  distance={index % 2 === 0 ? -10 : 10}
                >
                  <AnimatedPressable
                    testID={`history-item-${item.id}`}
                    style={styles.timelineRow}
                    scaleTo={0.98}
                    onPress={() => router.push(`/report?id=${item.id}`)}
                  >
                    <View style={styles.timelineNodeWrap}>
                      <View
                        style={[
                          styles.timelineNode,
                          { borderColor: scoreColor(item.global_score) },
                        ]}
                      >
                        <Text style={styles.timelineNodeScore}>{item.global_score}</Text>
                      </View>
                    </View>
                    <View style={styles.timelineCard}>
                      <Text style={styles.cardDate}>
                        {new Date(item.created_at).toLocaleDateString("fr-FR", {
                          day: "2-digit",
                          month: "long",
                          year: "numeric",
                        })}
                      </Text>
                      <View style={styles.metaRow}>
                        <Text style={styles.metaText}>Texture {item.texture}</Text>
                        <Text style={styles.metaSep}>·</Text>
                        <Text style={styles.metaText}>Éclat {item.radiance}</Text>
                        <Text style={styles.metaSep}>·</Text>
                        <Text style={styles.metaText}>Imperf. {item.imperfections}</Text>
                      </View>
                      {item.diagnosis ? (
                        <Text style={styles.diagnosis} numberOfLines={1}>{item.diagnosis}</Text>
                      ) : null}
                    </View>
                  </AnimatedPressable>
                </FadeIn>
              ))}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.m, paddingBottom: spacing.xxl },
  title: {
    fontFamily: fonts.heading,
    fontSize: 32,
    lineHeight: 36,
    color: colors.fg,
    letterSpacing: -0.8,
    marginTop: spacing.m,
    marginBottom: spacing.m,
  },
  filterRow: { flexDirection: "row", gap: spacing.s, marginBottom: spacing.l },
  filterPill: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: spacing.m,
  },
  filterPillActive: { backgroundColor: colors.accent },
  filterText: { fontFamily: fonts.bodyMedium, fontSize: 12, color: colors.fgMuted },
  filterTextActive: { color: colors.onAccent },

  summaryRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.md,
    paddingVertical: spacing.m,
    marginBottom: spacing.xl,
    ...shadow.card,
  },
  summaryItem: { flex: 1, alignItems: "center" },
  summaryDivider: { width: 1, height: 30, backgroundColor: colors.borderSubtle },
  summaryValue: {
    fontFamily: fonts.heading,
    fontSize: 26,
    color: colors.fg,
    letterSpacing: -0.5,
  },
  summaryLabel: {
    fontFamily: fonts.body,
    fontSize: 10,
    color: colors.fgMuted,
    marginTop: 2,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },

  timeline: { position: "relative", paddingBottom: spacing.xl },
  timelineLine: {
    position: "absolute",
    left: 23,
    top: 4,
    bottom: 20,
    width: 1.5,
    backgroundColor: colors.borderMid,
  },
  timelineRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.m,
    marginBottom: spacing.m,
  },
  timelineNodeWrap: { width: 48, alignItems: "center" },
  timelineNode: {
    width: 48,
    height: 48,
    borderRadius: 24,
    borderWidth: 2,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
    ...shadow.card,
  },
  timelineNodeScore: {
    fontFamily: fonts.headingMedium,
    fontSize: 14,
    color: colors.fg,
  },
  timelineCard: {
    flex: 1,
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    marginTop: 2,
  },
  cardDate: {
    fontFamily: fonts.headingMedium,
    fontSize: 14,
    color: colors.fg,
    marginBottom: 4,
  },
  metaRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center" },
  metaText: { fontFamily: fonts.body, fontSize: 11, color: colors.fgMuted },
  metaSep: { fontFamily: fonts.body, fontSize: 11, color: colors.borderMid, marginHorizontal: 5 },
  diagnosis: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.accent,
    marginTop: 4,
    fontStyle: "italic",
  },

  emptyWrap: { alignItems: "center", paddingTop: spacing.xxl, gap: spacing.s },
  emptyTitle: { fontFamily: fonts.heading, fontSize: 20, color: colors.fg, marginTop: spacing.s },
  emptyHint: {
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.fgMuted,
    textAlign: "center",
    marginBottom: spacing.m,
    paddingHorizontal: spacing.l,
  },
  emptyBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: spacing.xl,
    paddingVertical: 16,
    borderRadius: radius.pill,
    ...shadow.button,
  },
  emptyBtnText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
});
