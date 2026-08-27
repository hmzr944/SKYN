import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { syncPendingReports } from "@/src/services/api";
import { listScans, type ScanSummary } from "@/src/services/scanStore";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { Swap } from "@/src/components/ui/Swap";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { ProgressTimeline } from "@/src/components/analysis/ProgressTimeline";
import { SEVERITY_LABEL } from "@/src/types/analysis";
import { Segmented } from "@/src/components/ui/Segmented";

const FILTERS = [
  { label: "7j", days: 7 },
  { label: "30j", days: 30 },
  { label: "3 mois", days: 90 },
];

export default function HistoryScreen() {
  const router = useRouter();
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState(FILTERS[2].days);

  const load = useCallback(async () => {
    try {
      await syncPendingReports();
      setScans(await listScans());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => { load(); }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    load();
  };

  const filtered = useMemo(() => {
    const cutoff = Date.now() - filter * 24 * 60 * 60 * 1000;
    return scans.filter((r) => new Date(r.date).getTime() >= cutoff);
  }, [scans, filter]);

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <FadeIn distance={10}>
        <Text style={styles.title}>Historique</Text>
      </FadeIn>

      <FadeIn delay={60}>
        <Segmented
          testIDPrefix="history-filter"
          options={FILTERS.map((f) => ({ value: f.days, label: f.label }))}
          value={filter}
          onChange={(d) => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setFilter(d);
          }}
          style={styles.filterRow}
        />
      </FadeIn>

      {/* L'attente cede la place a la liste au lieu d'etre remplacee dans
          la meme image. `fill` garde la hauteur : sans elle la liste ne
          defilerait plus. */}
      <Swap etat={loading ? "attente" : "liste"} fill>
        {loading ? (
          <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.xxl }} />
        ) : (
          <FlatList
            data={filtered}
            keyExtractor={(item) => item.id}
            ListHeaderComponent={<ProgressTimeline />}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
            }
            renderItem={({ item, index }) => (
              <FadeIn delay={100 + Math.min(index, 6) * 50} distance={10}>
                <AnimatedPressable
                  testID={`history-item-${item.id}`}
                  style={styles.card}
                  scaleTo={0.98}
                  disabled={!item.detailed}
                  onPress={() => router.push(`/scan-result?id=${item.id}`)}
                >
                  <View style={styles.cardLeft}>
                    <Text style={styles.cardDate}>
                      {new Date(item.date).toLocaleDateString("fr-FR", {
                        day: "2-digit",
                        month: "long",
                        year: "numeric",
                      })}
                    </Text>
                    <View style={styles.metaRow}>
                      <View style={styles.metaPill}>
                        <Text style={styles.metaText}>{SEVERITY_LABEL[item.severity_level]}</Text>
                      </View>
                      <View style={styles.metaPill}>
                        <Text style={styles.metaText}>
                          {item.lesion_total} lésion{item.lesion_total > 1 ? "s" : ""}
                        </Text>
                      </View>
                      {/* Le detail est elague au-dela des douze dernieres analyses :
                          on le dit plutot que d'ouvrir un ecran vide. */}
                      {!item.detailed ? (
                        <View style={styles.metaPill}>
                          <Text style={styles.metaText}>Résumé seul</Text>
                        </View>
                      ) : null}
                    </View>
                  </View>
                  <Text style={styles.cardScore}>{item.global_score}</Text>
                </AnimatedPressable>
              </FadeIn>
            )}
            ListEmptyComponent={
              <FadeIn delay={120}>
                <View style={styles.emptyWrap}>
                  <Text style={styles.emptyTitle}>{"Pas encore d'analyse"}</Text>
                  <Text style={styles.emptyHint}>
                    Votre première analyse apparaîtra ici.
                  </Text>
                  <AnimatedPressable testID="history-start-btn" style={styles.emptyBtn} onPress={goScan}>
                    <Text style={styles.emptyBtnText}>Commencer</Text>
                  </AnimatedPressable>
                </View>
              </FadeIn>
            }
            contentContainerStyle={styles.listContent}
          />
        )}
      </Swap>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: spacing.xl },
  title: {
    fontFamily: fonts.display,
    fontSize: 24,
    color: colors.fg,
    letterSpacing: -0.3,
    marginTop: spacing.m,
    marginBottom: spacing.m,
  },
  filterRow: {
    marginBottom: spacing.l,
  },
  listContent: { paddingBottom: spacing.xxl },
  card: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    marginBottom: spacing.s,
    ...shadow.card,
  },
  cardLeft: { flex: 1, marginRight: spacing.m },
  cardDate: {
    fontFamily: fonts.heading,
    fontSize: 15,
    color: colors.fg,
    marginBottom: 6,
  },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  metaPill: {
    backgroundColor: colors.bg,
    borderRadius: radius.pill,
    paddingVertical: 3,
    paddingHorizontal: 8,
  },
  metaText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    color: colors.fg,
  },
  cardScore: {
    fontFamily: fonts.display,
    fontSize: 32,
    color: colors.accent,
    letterSpacing: -0.5,
  },
  emptyWrap: {
    alignItems: "center",
    paddingTop: spacing.xxl,
  },
  emptyTitle: {
    fontFamily: fonts.display,
    fontSize: 20,
    color: colors.fg,
    marginBottom: spacing.s,
  },
  emptyHint: {
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.fgMuted,
    textAlign: "center",
    marginBottom: spacing.l,
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
