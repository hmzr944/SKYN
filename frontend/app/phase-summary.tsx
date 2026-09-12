import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal, Stagger } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { SettlingLoader } from "@/src/components/skinMemory/SettlingLoader";
import { SkinChangePill, InsufficientPill } from "@/src/components/skinMemory/SkinChangePill";
import { api } from "@/src/services/api";
import {
  PHASE_VERDICT_LABEL,
  attributionSentence,
  metricLabel,
  phaseAttributionSentence,
  phaseVerdict,
  topImprovedZones,
  upcomingCheckpoint,
} from "@/src/services/skinMemory";
import { colors, fonts, radius, shadow, spacing, type } from "@/src/theme";
import type { ActivePeriodView } from "@/src/types/skinMemory";

/**
 * Le Bilan d'une Phase — "je commence un traitement aujourd'hui, et 30
 * jours plus tard j'obtiens un bilan fiable" (voir la demande produit).
 * Marche pour n'importe quelle Phase, active ou déjà close : la Phase
 * active d'un traitement en cours se consulte tout autant qu'un traitement
 * terminé, avec exactement le même calcul — voir get_period_view côté
 * serveur, qui factorise avec get_active_period_view.
 */

const productLabel = (id: string) => id;

function title(period: ActivePeriodView["period"]): string {
  if (period.label) return period.label;
  if (period.opened_by === "baseline") return "Baseline";
  const d = new Date(period.starts_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
  return `Changement de routine du ${d}`;
}

function durationLabel(period: ActivePeriodView["period"]): string {
  const start = new Date(period.starts_at).getTime();
  const end = period.ends_at ? new Date(period.ends_at).getTime() : Date.now();
  const days = Math.max(0, Math.round((end - start) / 86400000));
  const n = `${days} jour${days > 1 ? "s" : ""}`;
  return period.ends_at ? n : `${n} · en cours`;
}

export default function PhaseSummaryScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const [view, setView] = useState<ActivePeriodView | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!id) {
        setView(null);
        return;
      }
      try {
        setView(await api.getPeriod(id));
      } catch {
        if (!cancelled) setView(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (view === undefined) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.loadingWrap}>
          <SettlingLoader />
        </View>
      </SafeAreaView>
    );
  }

  if (!view) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
        </View>
        <View style={styles.emptyWrap}>
          <Text style={styles.emptyTitle}>Bilan introuvable</Text>
          <Text style={styles.emptyNote}>Cette Phase n&apos;existe plus ou n&apos;est pas accessible.</Text>
          <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.replace("/phase-history")}>
            <Text style={styles.linkText}>Retour à mes Phases</Text>
          </AnimatedPressable>
        </View>
      </SafeAreaView>
    );
  }

  const active = !view.period.ends_at;
  const improvedZones = topImprovedZones(view.changes);
  const verdict = view.state !== "baseline" ? phaseVerdict(view.changes) : "insufficient";
  const tone = verdict === "watch" ? "watch" : "calm";
  const next = upcomingCheckpoint(view.period);

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={26} still />
      </View>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Reveal bouncy distance={12}>
          <Text style={styles.kicker}>BILAN DE PHASE</Text>
          <Text style={styles.title}>{title(view.period)}</Text>
          {view.period.goal ? <Text style={styles.goal}>{view.period.goal}</Text> : null}
          <Text style={styles.duration}>{durationLabel(view.period)}</Text>
        </Reveal>

        {next ? (
          <Reveal delay={40}>
            <View style={styles.nextPill}>
              <Text style={styles.nextPillText}>
                Prochain scan conseillé · J+{next.day} ·{" "}
                {next.date.toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}
              </Text>
            </View>
          </Reveal>
        ) : null}

        {view.state === "baseline" ? (
          <>
            <Reveal delay={80} style={styles.haloRow}>
              <PhaseHalo size={64} tone="calm" />
            </Reveal>
            <Reveal delay={140}>
              <InsufficientPill label="Pas assez de données pour comparer" />
              <Text style={styles.note}>
                {active
                  ? "Refaites un scan pendant cette Phase pour obtenir un premier bilan."
                  : "Cette Phase s'est terminée sans deuxième scan pour comparer."}
              </Text>
            </Reveal>
          </>
        ) : (
          <>
            <Reveal delay={80} style={styles.verdictRow}>
              <PhaseHalo size={64} tone={tone} />
              <Text style={styles.verdict}>{PHASE_VERDICT_LABEL[verdict]}</Text>
            </Reveal>

            {improvedZones.length > 0 ? (
              <Reveal delay={120}>
                <View style={styles.card}>
                  <Text style={styles.cardEyebrow}>Zones les plus améliorées</Text>
                  <Text style={styles.zonesText}>
                    {improvedZones.map((c) => metricLabel(c)).join(", ")}
                  </Text>
                </View>
              </Reveal>
            ) : null}

            <Reveal delay={160}>
              <Text style={styles.sectionTitle}>{`Depuis le début de cette Phase, voici ce qui a changé`}</Text>
            </Reveal>
            <Stagger style={styles.list} delay={180} distance={14}>
              {view.changes.map((c) => {
                const note = attributionSentence(c, productLabel) ?? phaseAttributionSentence(c, view.period);
                return (
                  <View key={`${c.kind}-${c.metric}`} style={styles.row}>
                    <SkinChangePill item={c} />
                    {note ? <Text style={styles.attribution}>{note}</Text> : null}
                  </View>
                );
              })}
            </Stagger>
          </>
        )}

        {active ? (
          <>
            <AnimatedPressable style={styles.cta} haptic="medium" onPress={() => router.push("/camera-guided")}>
              <Text style={styles.ctaText}>Faire un nouveau scan</Text>
            </AnimatedPressable>
            <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.push("/what-changed")}>
              <Text style={styles.linkText}>Voir le détail scan par scan</Text>
            </AnimatedPressable>
          </>
        ) : (
          <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.replace("/phase-history")}>
            <Text style={styles.linkText}>Retour à mes Phases</Text>
          </AnimatedPressable>
        )}
      </ScrollView>
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
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: spacing.l, gap: spacing.m, paddingBottom: spacing.xxl },
  kicker: { ...type.kicker, color: colors.fgDim },
  title: { ...type.title, color: colors.fg, marginTop: 6 },
  goal: { ...type.bodySmall, color: colors.accent, marginTop: 4 },
  duration: { ...type.bodySmall, color: colors.fgDim, marginTop: 4 },
  nextPill: {
    alignSelf: "flex-start",
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: spacing.m,
    marginTop: spacing.m,
  },
  nextPillText: { fontFamily: fonts.bodyMedium, fontSize: 12, color: colors.fg },

  haloRow: { alignItems: "flex-start", marginVertical: spacing.s },
  note: { ...type.bodySmall, color: colors.fgMuted, marginTop: spacing.s },

  verdictRow: { flexDirection: "row", alignItems: "center", gap: spacing.m, marginTop: spacing.m },
  verdict: { ...type.body, color: colors.fg, flex: 1, lineHeight: 22 },

  card: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginTop: spacing.m,
    ...shadow.card,
  },
  cardEyebrow: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: colors.fgDim,
    marginBottom: spacing.s,
  },
  zonesText: { ...type.body, color: colors.fg, textTransform: "capitalize" },

  sectionTitle: {
    fontFamily: fonts.display,
    fontSize: 18,
    color: colors.fg,
    marginTop: spacing.l,
    marginBottom: spacing.s,
  },
  list: { gap: spacing.m },
  row: { gap: 6 },
  attribution: {
    fontFamily: fonts.displayRegular,
    fontStyle: "italic",
    fontSize: 13,
    color: colors.fgMuted,
    paddingLeft: 2,
  },

  cta: {
    backgroundColor: colors.accent,
    marginTop: spacing.l,
    paddingVertical: 17,
    borderRadius: radius.pill,
    alignItems: "center",
    ...shadow.button,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: "uppercase",
    color: colors.onAccent,
  },
  linkBtn: { paddingVertical: spacing.m, alignItems: "center" },
  linkText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },

  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.m, paddingHorizontal: spacing.l },
  emptyTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  emptyNote: { ...type.body, color: colors.fgMuted, textAlign: "center" },
});
