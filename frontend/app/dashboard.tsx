import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  Dimensions,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Svg, { Polyline, Circle } from "react-native-svg";

import { colors, fonts, spacing, radius } from "@/src/theme";
import { api, syncPendingReports } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";

const { width: SCREEN_W } = Dimensions.get("window");
const CHART_W = SCREEN_W - spacing.xl * 2 - spacing.m * 2;
const CHART_H = 110;

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
  const points = scores
    .map(
      (s, i) =>
        `${padX + i * step},${padY + innerH - ((s - min) / range) * innerH}`,
    )
    .join(" ");
  return (
    <Svg width={CHART_W} height={CHART_H}>
      <Polyline
        points={points}
        fill="none"
        stroke={colors.fg}
        strokeWidth={1}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {scores.map((s, i) => (
        <Circle
          key={i}
          cx={padX + i * step}
          cy={padY + innerH - ((s - min) / range) * innerH}
          r={2.5}
          fill={colors.fg}
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
  const { user, signOut } = useAuth();
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
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
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useFocusEffect(
    useCallback(() => { load(); }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    load();
  };

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  const chartScores = [...reports].reverse().slice(-4).map((r) => r.global_score);
  const firstName = (user?.name || "Vous").split(" ")[0];

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Header */}
      <View style={styles.headerRow}>
        <View style={{ flexShrink: 1 }}>
          <Text style={styles.greeting} numberOfLines={1}>
            Bonjour, {firstName}.
          </Text>
          <Text style={styles.date}>{todayLabel()}</Text>
        </View>
        <TouchableOpacity
          testID="dashboard-signout-btn"
          style={styles.logoutBtn}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            signOut();
          }}
        >
          <Text style={styles.logout}>Déconnexion</Text>
        </TouchableOpacity>
      </View>

      {syncMsg ? (
        <Text style={styles.syncMsg} testID="dashboard-sync-msg">
          {syncMsg}
        </Text>
      ) : null}

      <FlatList
        data={reports}
        keyExtractor={(item) => item.id}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.fg}
          />
        }
        ListHeaderComponent={
          <View>
            {/* Chart section */}
            <View style={styles.chartCard}>
              <Text style={styles.chartLabel}>EVOLUTION — 4 DERNIERS SCANS</Text>
              {loading ? (
                <ActivityIndicator
                  color={colors.fgMuted}
                  style={{ marginTop: spacing.l, marginBottom: spacing.s }}
                />
              ) : (
                <View style={styles.chartWrap}>
                  <ScoreChart scores={chartScores} />
                </View>
              )}
            </View>

            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Historique</Text>
              <Text style={styles.sectionCount}>
                {reports.length} bilan{reports.length !== 1 ? "s" : ""}
              </Text>
            </View>
          </View>
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            testID={`history-item-${item.id}`}
            style={styles.historyCard}
            activeOpacity={0.65}
            onPress={() => router.push(`/report?id=${item.id}`)}
          >
            <View style={styles.historyLeft}>
              <Text style={styles.historyDate}>
                {new Date(item.created_at).toLocaleDateString("fr-FR", {
                  day: "2-digit",
                  month: "long",
                  year: "numeric",
                })}
              </Text>
              <View style={styles.metaRow}>
                <Text style={styles.metaChip}>Texture {item.texture}</Text>
                <Text style={styles.metaDot}>·</Text>
                <Text style={styles.metaChip}>Éclat {item.radiance}</Text>
                <Text style={styles.metaDot}>·</Text>
                <Text style={styles.metaChip}>Imperfections {item.imperfections}</Text>
              </View>
            </View>
            <View style={styles.scoreBadge}>
              <Text style={styles.historyScore}>{item.global_score}</Text>
            </View>
          </TouchableOpacity>
        )}
        ListEmptyComponent={
          !loading ? (
            <View style={styles.emptyWrap}>
              <Text style={styles.empty}>Aucun bilan enregistré.</Text>
              <Text style={styles.emptyHint}>
                Initiez votre premier scan pour commencer le suivi.
              </Text>
            </View>
          ) : null
        }
        contentContainerStyle={{
          paddingHorizontal: spacing.xl,
          paddingBottom: 160,
        }}
      />

      {/* CTA */}
      <View style={styles.ctaWrap} pointerEvents="box-none">
        <TouchableOpacity
          testID="dashboard-new-scan-btn"
          style={styles.cta}
          activeOpacity={0.85}
          onPress={goScan}
        >
          <Text style={styles.ctaText} numberOfLines={1} adjustsFontSizeToFit>
            Nouveau Scan
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-end",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.l,
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
    textTransform: "uppercase",
  },
  logoutBtn: {
    paddingVertical: 8,
    paddingLeft: spacing.m,
  },
  logout: {
    fontFamily: fonts.body,
    fontSize: 10,
    color: colors.fgDim,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  syncMsg: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    textAlign: "center",
    letterSpacing: 1.5,
    paddingBottom: 8,
  },
  chartCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: spacing.m,
    marginBottom: spacing.xl,
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
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    marginBottom: spacing.m,
  },
  sectionTitle: {
    fontFamily: fonts.heading,
    fontSize: 24,
    color: colors.fg,
    letterSpacing: -0.3,
  },
  sectionCount: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.fgMuted,
    letterSpacing: 1,
  },
  historyCard: {
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
  },
  historyLeft: { flex: 1, marginRight: spacing.m },
  historyDate: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 14,
    marginBottom: 6,
  },
  metaRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 4 },
  metaChip: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 0.3,
  },
  metaDot: {
    color: colors.fgDim,
    fontSize: 11,
  },
  scoreBadge: {
    width: 52,
    height: 52,
    borderRadius: 26,
    borderWidth: 1,
    borderColor: colors.borderActive,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  historyScore: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 22,
    letterSpacing: -0.5,
  },
  emptyWrap: {
    alignItems: "center",
    paddingTop: spacing.xxl,
    paddingHorizontal: spacing.xl,
  },
  empty: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 15,
    marginBottom: spacing.s,
  },
  emptyHint: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13,
    textAlign: "center",
    lineHeight: 20,
  },
  ctaWrap: {
    position: "absolute",
    bottom: 36,
    left: 0,
    right: 0,
    alignItems: "center",
  },
  cta: {
    backgroundColor: colors.fg,
    paddingHorizontal: 40,
    paddingVertical: 20,
    borderRadius: radius.pill,
  },
  ctaText: {
    fontFamily: fonts.bodyMedium,
    color: colors.bg,
    fontSize: 13,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
