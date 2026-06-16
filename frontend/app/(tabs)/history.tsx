import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api, syncPendingReports } from "@/src/services/api";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const FILTERS = [
  { label: "7j", days: 7 },
  { label: "30j", days: 30 },
  { label: "3 mois", days: 90 },
];

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
    return reports.filter((r) => new Date(r.created_at).getTime() >= cutoff);
  }, [reports, filter]);

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
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => item.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
          }
          renderItem={({ item, index }) => (
            <FadeIn delay={100 + Math.min(index, 6) * 50} distance={10}>
              <AnimatedPressable
                testID={`history-item-${item.id}`}
                style={styles.card}
                scaleTo={0.98}
                onPress={() => router.push(`/report?id=${item.id}`)}
              >
                <View style={styles.cardLeft}>
                  <Text style={styles.cardDate}>
                    {new Date(item.created_at).toLocaleDateString("fr-FR", {
                      day: "2-digit",
                      month: "long",
                      year: "numeric",
                    })}
                  </Text>
                  <View style={styles.metaRow}>
                    <View style={styles.metaPill}>
                      <Text style={styles.metaText}>Texture {item.texture}</Text>
                    </View>
                    <View style={styles.metaPill}>
                      <Text style={styles.metaText}>Éclat {item.radiance}</Text>
                    </View>
                    <View style={styles.metaPill}>
                      <Text style={styles.metaText}>Imperf. {item.imperfections}</Text>
                    </View>
                  </View>
                </View>
                <Text style={styles.cardScore}>{item.global_score}</Text>
              </AnimatedPressable>
            </FadeIn>
          )}
          ListEmptyComponent={
            <FadeIn delay={120}>
              <View style={styles.emptyWrap}>
                <Text style={styles.emptyTitle}>Pas encore d'analyse</Text>
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
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: spacing.xl },
  title: {
    fontFamily: fonts.heading,
    fontSize: 24,
    color: colors.fg,
    letterSpacing: -0.3,
    marginTop: spacing.m,
    marginBottom: spacing.m,
  },
  filterRow: {
    flexDirection: "row",
    gap: spacing.s,
    marginBottom: spacing.l,
  },
  filterPill: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: spacing.m,
  },
  filterPillActive: {
    backgroundColor: colors.accent,
  },
  filterText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    color: colors.fgMuted,
  },
  filterTextActive: {
    color: colors.onAccent,
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
    fontFamily: fonts.heading,
    fontSize: 32,
    color: colors.accent,
    letterSpacing: -0.5,
  },
  emptyWrap: {
    alignItems: "center",
    paddingTop: spacing.xxl,
  },
  emptyTitle: {
    fontFamily: fonts.heading,
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
