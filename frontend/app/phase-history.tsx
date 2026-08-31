import { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal, Stagger } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { api } from "@/src/services/api";
import { colors, fonts, radius, spacing, type } from "@/src/theme";
import type { Period } from "@/src/types/skinMemory";

/**
 * Historique / Phase — des chapitres, pas une liste plate de bilans datés
 * (voir l'audit du deck "SKYN Skin Memory" sur history.tsx). Volontairement
 * minimal : ni scans ni changements par Phase close ne sont encore
 * exposés par l'API (seul GET /api/periods/active les donne) — construire
 * cet enrichissement est un chantier séparé, pas fait ici en silence.
 */

function rangeLabel(p: Period): string {
  const start = new Date(p.starts_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
  if (!p.ends_at) return `Depuis le ${start}`;
  const end = new Date(p.ends_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
  return `${start} → ${end}`;
}

function chapterName(p: Period, index: number, total: number): string {
  if (p.opened_by === "baseline") return "Baseline";
  return `Phase ${total - index}`;
}

function ProgressLine({ single }: { single: boolean }) {
  return (
    <View style={styles.progressRow}>
      <View style={styles.progressDot} />
      <View style={styles.progressBar} />
      <View style={[styles.progressDot, single && styles.progressDotFaint]} />
    </View>
  );
}

export default function PhaseHistoryScreen() {
  const router = useRouter();
  const [periods, setPeriods] = useState<Period[] | null>(null);

  const load = useCallback(async () => {
    try {
      setPeriods(await api.listPeriods());
    } catch {
      setPeriods([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={26} still />
        <Text style={styles.betaTag}>bêta</Text>
      </View>

      {periods === null ? (
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : periods.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Text style={styles.emptyTitle}>Pas encore de Phase</Text>
          <Text style={styles.emptyNote}>Vos Phases apparaîtront ici après votre premier scan.</Text>
        </View>
      ) : (
        <FlatList
          data={periods}
          keyExtractor={(p) => p.id}
          contentContainerStyle={styles.list}
          ListHeaderComponent={
            <Reveal distance={10}>
              <Text style={styles.title}>Vos Phases</Text>
              <Text style={styles.lede}>
                Chaque Phase raconte une période — pas une liste de scans datés.
              </Text>
            </Reveal>
          }
          renderItem={({ item, index }) => {
            const active = !item.ends_at;
            const single = item.baseline_scan_id === item.latest_scan_id;
            const card = (
              <View style={[styles.card, active && styles.cardActive]}>
                <View style={styles.cardHead}>
                  <Text style={styles.chapter}>{chapterName(item, index, periods.length)}</Text>
                  {active ? <View style={styles.activeTag}><Text style={styles.activeTagText}>En cours</Text></View> : null}
                </View>
                <Text style={styles.range}>{rangeLabel(item)}</Text>
                <ProgressLine single={single} />
                <Text style={styles.count}>{single ? "1 mesure" : "Plusieurs mesures"}</Text>
              </View>
            );
            return (
              <Stagger delay={80 + index * 10} distance={12}>
                {active ? (
                  <AnimatedPressable
                    testID="phase-history-active-card"
                    scaleTo={0.985}
                    onPress={() => router.push("/what-changed")}
                  >
                    {card}
                  </AnimatedPressable>
                ) : (
                  card
                )}
              </Stagger>
            );
          }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.m,
  },
  betaTag: { ...type.kicker, color: colors.fgDim },
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.s, paddingHorizontal: spacing.l },
  emptyTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  emptyNote: { ...type.body, color: colors.fgMuted, textAlign: "center" },
  list: { padding: spacing.l, gap: spacing.m, paddingBottom: spacing.xxl },
  title: { ...type.title, color: colors.fg, marginBottom: 4 },
  lede: { ...type.bodySmall, color: colors.fgMuted, marginBottom: spacing.l },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginBottom: spacing.m,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  cardActive: { borderColor: colors.accentLine, backgroundColor: colors.accentSofter },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  chapter: { fontFamily: fonts.display, fontSize: 19, color: colors.fg },
  activeTag: { backgroundColor: colors.accent, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  activeTagText: { fontFamily: fonts.bodyMedium, fontSize: 10, color: colors.onAccent, textTransform: "uppercase", letterSpacing: 0.6 },
  range: { ...type.bodySmall, color: colors.fgMuted, marginTop: 4 },
  progressRow: { flexDirection: "row", alignItems: "center", marginTop: spacing.m, marginBottom: spacing.xs },
  progressDot: { width: 7, height: 7, borderRadius: 3.5, backgroundColor: colors.fg },
  progressDotFaint: { backgroundColor: colors.fgFaint },
  progressBar: { flex: 1, height: 1, backgroundColor: colors.borderMid, marginHorizontal: 6 },
  count: { ...type.bodySmall, color: colors.fgDim },
});
