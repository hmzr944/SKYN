import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { FaceZoneMap } from "@/src/components/analysis/FaceZoneMap";
import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { SkinChangePill, InsufficientPill } from "@/src/components/skinMemory/SkinChangePill";
import { api } from "@/src/services/api";
import { changeTone, latestScore, zoneConfidenceMap } from "@/src/services/skinMemory";
import { colors, fonts, radius, spacing, type } from "@/src/theme";
import type { ActivePeriodView } from "@/src/types/skinMemory";

/**
 * "Votre carte de peau" — écran expérimental (bêta), en parallèle du
 * dashboard.tsx par défaut. Répond à "où en est ma peau ?" par la carte de
 * zones et le Skin Change de la Phase active, pas par un score en gros —
 * voir le deck "SKYN Skin Memory" (recommandation : Personal Skin Map).
 */

const STATE_LABEL: Record<string, string> = {
  baseline: "Première mesure",
  tracking: "Tendance en construction",
  understanding: "Tendance établie",
};

function daysAgoLabel(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "aujourd'hui";
  if (days === 1) return "il y a 1 jour";
  return `il y a ${days} jours`;
}

export default function SkinMapScreen() {
  const router = useRouter();
  const [view, setView] = useState<ActivePeriodView | null | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setView(await api.getActivePeriod());
    } catch {
      setView(null);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const goScan = () => router.push("/camera-guided");
  const goHistory = () => router.push("/phase-history");

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={24} still />
        <Text style={styles.betaTag}>bêta</Text>
      </View>

      {view === undefined ? (
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : !view ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Reveal distance={12}>
            <Text style={styles.title}>Votre carte de peau</Text>
            <Text style={styles.lede}>
              Pas un diagnostic du jour — une mesure qui se construit à chaque scan, pour
              comprendre comment votre peau évolue, pas seulement où elle en est.
            </Text>
          </Reveal>
          <Reveal distance={12} delay={80}>
            <AnimatedPressable style={styles.cta} haptic="medium" onPress={goScan}>
              <Text style={styles.ctaText}>Commencer ma carte</Text>
            </AnimatedPressable>
          </Reveal>
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Reveal distance={10}>
            <Text style={styles.kicker}>VOTRE CARTE DE PEAU</Text>
            <Text style={styles.subline}>
              Dernière mesure · {daysAgoLabel(view.period.starts_at)} ·{" "}
              {STATE_LABEL[view.state] ?? view.state}
            </Text>
          </Reveal>

          <Reveal delay={80} style={styles.mapRow}>
            <View style={styles.mapSlot}>
              <FaceZoneMap
                zoneScores={view.scans[view.scans.length - 1]?.zone_scores ?? {}}
                zoneConfidence={zoneConfidenceMap(view.changes)}
                size={220}
              />
              <View style={styles.haloSlot}>
                <PhaseHalo
                  size={52}
                  tone={
                    view.changes.some((c) => changeTone(c.kind, c.direction) === "watch")
                      ? "watch"
                      : "calm"
                  }
                />
              </View>
            </View>
          </Reveal>

          <Reveal delay={140} style={styles.changesBlock}>
            <Text style={styles.sectionTitle}>Ce qui se dessine</Text>
            {view.state === "baseline" ? (
              <InsufficientPill label="Votre carte commence à se dessiner" />
            ) : view.changes.length === 0 ? (
              <InsufficientPill />
            ) : (
              <View style={styles.pillsWrap}>
                {view.changes.slice(0, 4).map((c) => (
                  <SkinChangePill key={`${c.kind}-${c.metric}`} item={c} />
                ))}
              </View>
            )}
          </Reveal>

          {(() => {
            const score = latestScore(view.scans);
            return score !== null ? (
              <Text style={styles.scoreCaption}>Score {score} · pour référence</Text>
            ) : null;
          })()}

          <Reveal delay={200}>
            <AnimatedPressable style={styles.cta} haptic="medium" onPress={goScan}>
              <Text style={styles.ctaText}>Nouveau scan</Text>
            </AnimatedPressable>
          </Reveal>
          <Reveal delay={240}>
            <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={goHistory}>
              <Text style={styles.linkText}>Voir mes Phases</Text>
            </AnimatedPressable>
          </Reveal>
        </ScrollView>
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
  scroll: { padding: spacing.l, gap: spacing.l, paddingBottom: spacing.xxl, alignItems: "center" },
  title: { ...type.title, color: colors.fg, textAlign: "center" },
  lede: { ...type.body, color: colors.fgMuted, textAlign: "center", marginTop: spacing.s },
  kicker: { ...type.kicker, color: colors.fgDim, alignSelf: "flex-start" },
  subline: { ...type.bodySmall, color: colors.fgMuted, alignSelf: "flex-start", marginTop: 4 },
  mapRow: { alignItems: "center" },
  mapSlot: { position: "relative" },
  haloSlot: { position: "absolute", top: 4, right: -8 },
  changesBlock: { width: "100%", gap: spacing.s },
  sectionTitle: { ...type.subtitle, color: colors.fg, alignSelf: "flex-start" },
  pillsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s },
  scoreCaption: { ...type.bodySmall, color: colors.fgDim },
  cta: {
    width: "100%",
    backgroundColor: colors.accent,
    paddingVertical: 16,
    alignItems: "center",
    borderRadius: radius.pill,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  linkBtn: { paddingVertical: spacing.s },
  linkText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
});
