import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal, Stagger } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { FaceZoneMap } from "@/src/components/analysis/FaceZoneMap";
import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { SkinChangePill, InsufficientPill } from "@/src/components/skinMemory/SkinChangePill";
import { api } from "@/src/services/api";
import { attributionSentence, changeTone, confidenceLabel, latestScore } from "@/src/services/skinMemory";
import { colors, fonts, radius, spacing, type } from "@/src/theme";
import type { ActivePeriodView } from "@/src/types/skinMemory";

/**
 * What Changed? — l'écran le plus important du deck "SKYN Skin Memory" :
 * ce qui donne envie de revenir. Jamais de causalité affirmée — voir
 * `attributionSentence()`, câblé mot pour mot sur ce que le backend
 * retourne (corrélationnel, jamais "X a amélioré votre peau").
 */

// Un identifiant de produit brut en attendant un vrai catalogue — voir la
// décision produit du chantier 2 : pas de grande base de produits pour
// l'instant, juste "ce que j'utilise" en texte libre.
const productLabel = (id: string) => id;

function periodDateLabel(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
}

export default function WhatChangedScreen() {
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

  if (view === undefined) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={colors.accent} />
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
          <Text style={styles.emptyTitle}>{"Rien à montrer pour l'instant"}</Text>
          <Text style={styles.emptyNote}>Faites un premier scan guidé pour démarrer votre carte.</Text>
          <AnimatedPressable style={styles.cta} haptic="medium" onPress={() => router.replace("/camera-guided")}>
            <Text style={styles.ctaText}>Faire un scan</Text>
          </AnimatedPressable>
        </View>
      </SafeAreaView>
    );
  }

  const worstTone = view.changes.some((c) => changeTone(c.kind, c.direction) === "watch") ? "watch" : "calm";
  const score = latestScore(view.scans);

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={26} still />
        <Text style={styles.betaTag}>bêta</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Reveal distance={12}>
          <Text style={styles.kicker}>DEPUIS LE {periodDateLabel(view.period.starts_at).toUpperCase()}</Text>
          <Text style={styles.title}>What Changed?</Text>
        </Reveal>

        {view.state === "baseline" ? (
          <>
            <Reveal delay={80} style={styles.haloRow}>
              <PhaseHalo size={72} tone={worstTone} />
            </Reveal>
            <Reveal delay={140}>
              <InsufficientPill label="Première mesure — rien à comparer encore" />
              <Text style={styles.note}>
                Revenez après votre prochain scan pour voir ce qui a changé.
              </Text>
            </Reveal>
          </>
        ) : view.changes.length === 0 ? (
          <>
            <Reveal delay={80} style={styles.haloRow}>
              <PhaseHalo size={72} tone={worstTone} />
            </Reveal>
            <Reveal delay={140}>
              <InsufficientPill />
            </Reveal>
          </>
        ) : (
          <>
            {/* Le coeur de l'ecran : la carte se resout depuis la baseline
                de la Phase vers la derniere mesure — le changement EST le
                visuel, pas une liste a cote d'une forme statique. */}
            <Reveal delay={80} style={styles.mapRow}>
              <View style={styles.mapSlot}>
                <FaceZoneMap
                  zoneScores={view.scans[view.scans.length - 1].zone_scores}
                  previousZoneScores={view.scans[0].zone_scores}
                  size={200}
                />
                <View style={styles.haloSlot}>
                  <PhaseHalo size={48} tone={worstTone} />
                </View>
              </View>
            </Reveal>
            <Reveal delay={160}>
              <Text style={styles.mapCaption}>Avant → maintenant, sur cette Phase</Text>
            </Reveal>
          </>
        )}

        {view.state !== "baseline" && view.changes.length > 0 && (
          <Stagger style={styles.list} delay={140} distance={14}>
            {view.changes.map((c) => {
              const note = attributionSentence(c, productLabel);
              return (
                <View key={`${c.kind}-${c.metric}`} style={styles.row}>
                  <SkinChangePill item={c} />
                  {note ? <Text style={styles.attribution}>{note}</Text> : null}
                </View>
              );
            })}
          </Stagger>
        )}

        {view.changes.length > 0 ? (
          <Reveal delay={260}>
            <Text style={styles.caveat}>
              {confidenceLabel(view.changes[0]?.confidence ?? "low")} · {view.scans.length} scan
              {view.scans.length > 1 ? "s" : ""} sur cette Phase.{" "}
              {"Plusieurs facteurs peuvent contribuer à une évolution — SKYN observe, il ne diagnostique pas."}
            </Text>
          </Reveal>
        ) : null}

        {score !== null ? <Text style={styles.scoreCaption}>Score {score} · pour référence</Text> : null}

        <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.replace("/skin-map")}>
          <Text style={styles.linkText}>Retour à ma carte</Text>
        </AnimatedPressable>
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
  betaTag: { ...type.kicker, color: colors.fgDim },
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: spacing.l, gap: spacing.m, paddingBottom: spacing.xxl },
  kicker: { ...type.kicker, color: colors.fgDim },
  title: { ...type.title, color: colors.fg, marginTop: 6 },
  haloRow: { alignItems: "flex-start", marginVertical: spacing.s },
  mapRow: { alignItems: "center", marginTop: spacing.s },
  mapSlot: { position: "relative" },
  haloSlot: { position: "absolute", top: 0, right: -6 },
  mapCaption: {
    ...type.bodySmall,
    color: colors.fgDim,
    textAlign: "center",
    marginTop: -spacing.s,
  },
  note: { ...type.bodySmall, color: colors.fgMuted, marginTop: spacing.s },
  list: { gap: spacing.m },
  row: { gap: 6 },
  attribution: {
    fontFamily: fonts.displayRegular,
    fontStyle: "italic",
    fontSize: 13,
    color: colors.fgMuted,
    paddingLeft: 2,
  },
  caveat: {
    ...type.bodySmall,
    color: colors.fgDim,
    marginTop: spacing.s,
    lineHeight: 19,
  },
  scoreCaption: { ...type.bodySmall, color: colors.fgDim },
  linkBtn: { paddingVertical: spacing.m, alignItems: "center" },
  linkText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.m, paddingHorizontal: spacing.l },
  emptyTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  emptyNote: { ...type.body, color: colors.fgMuted, textAlign: "center" },
  cta: {
    backgroundColor: colors.accent,
    paddingVertical: 15,
    paddingHorizontal: spacing.xl,
    borderRadius: radius.pill,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
});
