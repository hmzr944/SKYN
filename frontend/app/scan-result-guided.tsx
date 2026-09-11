import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { AmbientBackground } from "@/src/components/ui/AmbientBackground";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal, Stagger } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { FaceZoneMap } from "@/src/components/analysis/FaceZoneMap";
import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { SettlingLoader } from "@/src/components/skinMemory/SettlingLoader";
import { SkinChangePill } from "@/src/components/skinMemory/SkinChangePill";
import { ProductVisual } from "@/src/components/ProductVisual";
import { api } from "@/src/services/api";
import { attributionSentence, phaseAttributionSentence } from "@/src/services/skinMemory";
import { colors, fonts, radius, shadow, spacing, type } from "@/src/theme";
import { storage } from "@/src/utils/storage";
import {
  LESION_LABEL,
  SEVERITY_LABEL,
  SKIN_TYPE_LABEL,
  STEP_LABEL,
  ZONE_LABEL,
} from "@/src/types/analysis";
import type { Lesion, LesionType, ZoneKey } from "@/src/types/analysis";
import type { ActivePeriodView } from "@/src/types/skinMemory";
import type { GuidedLesion, GuidedScanResponse } from "@/src/types/guidedScan";

/**
 * Résultat du scan guidé — le parcours principal n'a plus deux écrans de
 * résultat déconnectés (voir l'audit qui a précédé ce chantier) : celui-ci
 * fusionne l'état immédiat (scan-result.tsx) et le suivi de Phase
 * (what-changed.tsx) en un seul récit, sans dupliquer leur logique —
 * les puces et phrases d'attribution viennent de skinMemory.ts, la carte
 * de FaceZoneMap, exactement comme sur les deux écrans d'origine.
 */

// Un identifiant de produit brut en attendant un vrai catalogue — même
// convention que what-changed.tsx.
const productLabel = (id: string) => id;

function toMapLesions(lesions: GuidedLesion[]): Lesion[] {
  // FaceZoneMap ne lit que x/y/radius/type sur chaque lésion (voir son
  // rendu SVG) — orchestrer_scan ne calcule pas radius/confidence/redness/
  // darkness (voir GuidedLesion) : un rayon par défaut suffit ici, sans
  // fabriquer de valeurs cliniques qui n'existent pas.
  return lesions.map((l) => ({
    type: l.type,
    x: l.x,
    y: l.y,
    radius: 0.03,
    diameter_mm: 0,
    zone: l.zone,
    confidence: l.evidence,
    redness: 0,
    darkness: 0,
  }));
}

function zoneAttentionRows(data: GuidedScanResponse) {
  const byZone = new Map<string, Set<LesionType>>();
  for (const l of data.lesions) {
    if (!byZone.has(l.zone)) byZone.set(l.zone, new Set());
    byZone.get(l.zone)!.add(l.type);
  }
  const zones = Object.keys(data.zone_scores) as ZoneKey[];
  return zones
    .map((zone) => {
      const types = byZone.get(zone);
      const attention = !!types && types.size > 0;
      const note = attention ? Array.from(types!).map((t) => LESION_LABEL[t]).join(", ") : "Stable";
      return { zone, note, attention };
    })
    .sort((a, b) => Number(b.attention) - Number(a.attention));
}

export default function ScanResultGuidedScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [data, setData] = useState<GuidedScanResponse | null | undefined>(undefined);
  const [view, setView] = useState<ActivePeriodView | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const raw = (await storage.getItem("skyn_last_guided_result", "null")) as string;
      if (cancelled) return;
      const parsed = raw ? (JSON.parse(raw) as GuidedScanResponse | null) : null;
      setData(parsed);
      await storage.setItem("skyn_last_guided_result", "null");
      try {
        setView(await api.getActivePeriod());
      } catch {
        setView(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (data === undefined) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.loadingWrap}>
          <SettlingLoader />
        </View>
      </SafeAreaView>
    );
  }

  if (!data) {
    router.replace("/camera-guided");
    return null;
  }

  const attentionRows = zoneAttentionRows(data);
  const lesionTotal = data.lesions.length;
  const worstTone = data.severity_level && data.severity_level > 0 ? "watch" : attentionRows.some((r) => r.attention) ? "watch" : "calm";
  const hasComparison = !!view && view.state !== "baseline" && view.changes.length > 0;
  const previousZoneScores = view && view.scans.length > 1 ? view.scans[0].zone_scores : undefined;
  const mapSize = Math.min(width - spacing.xl * 2, 260);

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <AmbientBackground />
      <View style={styles.header}>
        <SkynLockup size={26} still />
      </View>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Ton état aujourd'hui */}
        <Reveal bouncy distance={12}>
          <Text style={styles.kicker}>RÉSULTAT DU SCAN</Text>
          <Text style={styles.title}>Ton état aujourd&apos;hui</Text>
        </Reveal>
        <Reveal delay={80} style={styles.heroRow}>
          <PhaseHalo size={64} tone={worstTone} />
          <View style={{ flex: 1 }}>
            <Text style={styles.diagnosis}>
              {data.diagnosis ?? (worstTone === "watch" ? "Quelques zones méritent votre attention." : "Ta peau semble globalement stable.")}
            </Text>
          </View>
        </Reveal>
        {(data.skin_type || data.phototype || (data.severity_level ?? 0) > 0) && (
          <Reveal delay={120} style={styles.tagRow}>
            {data.skin_type ? (
              <View style={styles.tag}>
                <Text style={styles.tagText}>Peau {SKIN_TYPE_LABEL[data.skin_type] ?? data.skin_type}</Text>
              </View>
            ) : null}
            {data.phototype_label ? (
              <View style={styles.tag}>
                <Text style={styles.tagText}>{data.phototype_label}</Text>
              </View>
            ) : null}
            {data.severity_level ? (
              <View style={[styles.tag, styles.tagAlert]}>
                <Text style={[styles.tagText, styles.tagTextAlert]}>{SEVERITY_LABEL[data.severity_level]}</Text>
              </View>
            ) : null}
          </Reveal>
        )}
        {data.summary ? (
          <Reveal delay={160}>
            <Text style={styles.summary}>{data.summary}</Text>
          </Reveal>
        ) : null}

        {/* Ce qui mérite ton attention */}
        <Reveal delay={200}>
          <View style={styles.card}>
            <Text style={styles.cardEyebrow}>
              Ce qui mérite ton attention{lesionTotal > 0 ? ` · ${lesionTotal} lésion${lesionTotal > 1 ? "s" : ""}` : ""}
            </Text>
            <Stagger delay={40} distance={8}>
              {attentionRows.map(({ zone, note, attention }) => (
                <View key={zone} style={styles.attentionRow}>
                  <Text style={styles.attentionZone}>{ZONE_LABEL[zone]}</Text>
                  <Text style={[styles.attentionNote, attention && styles.attentionNoteWatch]}>{note}</Text>
                </View>
              ))}
            </Stagger>
            {attentionRows.length === 0 ? <Text style={styles.mutedNote}>Aucune zone couverte sur cette série.</Text> : null}
          </View>
        </Reveal>

        {/* Ta carte */}
        <Reveal delay={240}>
          <View style={styles.card}>
            <Text style={styles.cardEyebrow}>Ta carte</Text>
            <View style={styles.mapWrap}>
              <FaceZoneMap
                zoneScores={data.zone_scores}
                previousZoneScores={previousZoneScores}
                lesions={toMapLesions(data.lesions)}
                size={mapSize}
              />
            </View>
          </View>
        </Reveal>

        {/* Ce qui a changé — seulement si une comparaison existe */}
        {hasComparison && view ? (
          <Reveal delay={280}>
            <View style={styles.card}>
              <Text style={styles.cardEyebrow}>Ce qui a changé</Text>
              <Stagger delay={60} distance={10}>
                {view.changes.slice(0, 4).map((c) => {
                  const note = attributionSentence(c, productLabel) ?? phaseAttributionSentence(c, view.period);
                  return (
                    <View key={`${c.kind}-${c.metric}`} style={styles.changeRow}>
                      <SkinChangePill item={c} />
                      {note ? <Text style={styles.attribution}>{note}</Text> : null}
                    </View>
                  );
                })}
              </Stagger>
              <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.push("/what-changed")}>
                <Text style={styles.linkText}>Voir le détail complet</Text>
              </AnimatedPressable>
            </View>
          </Reveal>
        ) : null}

        {/* Ta routine */}
        <Reveal delay={320}>
          <View style={styles.card}>
            <Text style={styles.cardEyebrow}>Ta routine</Text>
            {data.routine && (data.routine.am.length > 0 || data.routine.pm.length > 0) ? (
              <>
                {(["am", "pm"] as const).map((moment) =>
                  data.routine![moment].length ? (
                    <View key={moment} style={styles.routineGroup}>
                      <Text style={styles.routineMoment}>{moment === "am" ? "Matin" : "Soir"}</Text>
                      {data.routine![moment].map((p) => (
                        <View key={`${moment}-${p.id}`} style={styles.productRow}>
                          <ProductVisual product={p} size={40} />
                          <View style={{ flex: 1 }}>
                            <Text style={styles.productStep}>{STEP_LABEL[p.step] ?? p.step}</Text>
                            <Text style={styles.productName} numberOfLines={1}>
                              {p.brand} · {p.name}
                            </Text>
                          </View>
                        </View>
                      ))}
                    </View>
                  ) : null,
                )}
              </>
            ) : (
              <Text style={styles.mutedNote}>
                Routine indisponible pour cette série de vues — reprenez un scan avec un cadrage plus net.
              </Text>
            )}
          </View>
        </Reveal>

        <Text style={styles.disclaimer}>
          {"SKYN est un outil d'auto-suivi, pas un dispositif médical. Il ne pose pas de diagnostic et ne remplace pas l'avis d'un dermatologue."}
        </Text>

        <AnimatedPressable style={styles.cta} haptic="medium" onPress={() => router.replace("/skin-map")}>
          <Text style={styles.ctaText}>Voir ma mémoire de peau</Text>
        </AnimatedPressable>
        <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.push("/phase-history")}>
          <Text style={styles.linkText}>Voir mes Phases</Text>
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
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: spacing.l, gap: spacing.m, paddingBottom: spacing.xxl },
  kicker: { ...type.kicker, color: colors.fgDim },
  title: { ...type.title, color: colors.fg, marginTop: 6 },
  heroRow: { flexDirection: "row", alignItems: "center", gap: spacing.m, marginTop: spacing.m },
  diagnosis: { ...type.body, color: colors.fg, lineHeight: 22 },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s, marginTop: spacing.s },
  tag: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.m,
    paddingVertical: 6,
  },
  tagAlert: { backgroundColor: colors.accentSofter },
  tagText: { fontFamily: fonts.bodyMedium, fontSize: 12, color: colors.fg },
  tagTextAlert: { color: colors.accentDark },
  summary: { ...type.bodySmall, color: colors.fgMuted, marginTop: spacing.s, lineHeight: 20 },

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
    marginBottom: spacing.m,
  },
  attentionRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 7,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
  },
  attentionZone: { fontFamily: fonts.bodyMedium, fontSize: 13, color: colors.fg },
  attentionNote: { ...type.bodySmall, color: colors.fgDim },
  attentionNoteWatch: { color: colors.accentDark },
  mutedNote: { ...type.bodySmall, color: colors.fgDim },

  mapWrap: { alignItems: "center" },

  changeRow: { gap: 6, marginBottom: spacing.m },
  attribution: {
    fontFamily: fonts.displayRegular,
    fontStyle: "italic",
    fontSize: 13,
    color: colors.fgMuted,
    paddingLeft: 2,
  },

  routineGroup: { marginBottom: spacing.m },
  routineMoment: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.fgDim,
    marginBottom: spacing.s,
  },
  productRow: { flexDirection: "row", alignItems: "center", gap: spacing.m, marginBottom: spacing.s },
  productStep: {
    fontFamily: fonts.bodyMedium,
    fontSize: 9,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.fgDim,
  },
  productName: { fontFamily: fonts.headingMedium, fontSize: 13, color: colors.fg, marginTop: 2 },

  disclaimer: {
    fontFamily: fonts.body,
    fontSize: 11,
    lineHeight: 17,
    color: colors.fgDim,
    textAlign: "center",
    marginTop: spacing.l,
    paddingHorizontal: spacing.m,
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
  linkBtn: { paddingVertical: spacing.s, alignItems: "center" },
  linkText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
});
