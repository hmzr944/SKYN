import { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Pressable,
  Linking,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Svg, { Circle } from "react-native-svg";
import Animated, {
  withDelay,
  useSharedValue,
  useAnimatedProps,
  withTiming,
  withRepeat,
  useAnimatedStyle,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";

import { ease } from "@/src/animation/ease";
import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { getScan } from "@/src/services/scanStore";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { FaceZoneMap, ZoneLegend, scoreColor } from "@/src/components/analysis/FaceZoneMap";
import { ProductVisual } from "@/src/components/ProductVisual";
import {
  CONCERN_LABEL,
  LESION_LABEL,
  SEVERITY_LABEL,
  SKIN_TYPE_LABEL,
  STEP_LABEL,
  ZONE_LABEL,
} from "@/src/types/analysis";
import type {
  ConcernKey,
  FaceAnalysis,
  LesionType,
  ProductPick,
  ZoneKey,
} from "@/src/types/analysis";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/* ------------------------------------------------------------------ */
/* Anneau de score                                                     */
/* ------------------------------------------------------------------ */
function ScoreRing({ value, size = 168 }: { value: number; size?: number }) {
  const stroke = 10;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const p = useSharedValue(0);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    p.value = withTiming(value / 100, { duration: 1500, easing: ease.out });
    const start = Date.now();
    const id = setInterval(() => {
      const t = Math.min(1, (Date.now() - start) / 1500);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(value * eased));
      if (t >= 1) clearInterval(id);
    }, 32);
    return () => clearInterval(id);
  }, [value, p]);

  const animProps = useAnimatedProps(() => ({
    strokeDashoffset: circ * (1 - p.value),
  }));

  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <Svg width={size} height={size} style={{ transform: [{ rotate: "-90deg" }] }}>
        <Circle
          cx={size / 2} cy={size / 2} r={r}
          stroke={colors.fgFaint} strokeWidth={stroke} fill="none"
        />
        <AnimatedCircle
          cx={size / 2} cy={size / 2} r={r}
          stroke={scoreColor(value)} strokeWidth={stroke} fill="none"
          strokeLinecap="round" strokeDasharray={circ}
          animatedProps={animProps}
        />
      </Svg>
      <View style={StyleSheet.absoluteFillObject as any}>
        <View style={styles.ringCenter}>
          <Text style={styles.ringValue}>{shown}</Text>
          <Text style={styles.ringUnit}>sur 100</Text>
        </View>
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* Barre de préoccupation                                              */
/* ------------------------------------------------------------------ */
function ConcernRow({
  k,
  v,
  driver,
  index = 0,
}: {
  k: ConcernKey;
  v: number;
  driver?: string;
  index?: number;
}) {
  const w = useSharedValue(0);
  useEffect(() => {
    // Chaque barre part apres la precedente : on lit un calcul qui se deroule,
    // pas un tableau qui s'affiche.
    w.value = withDelay(
      index * 90,
      withTiming(v, { duration: 900, easing: ease.out }),
    );
  }, [v, w, index]);
  const barStyle = useAnimatedStyle(() => ({ width: `${w.value * 100}%` }));
  // Un axe très marqué doit se lire comme un point d'attention, donc en corail.
  const tone = scoreColor(Math.round((1 - v) * 100));

  return (
    <View style={styles.concernRow}>
      <View style={styles.concernHead}>
        <Text style={styles.concernName}>{CONCERN_LABEL[k] ?? k}</Text>
        <Text style={styles.concernVal}>{Math.round(v * 100)}</Text>
      </View>
      <View style={styles.concernTrack}>
        <Animated.View style={[styles.concernFill, barStyle, { backgroundColor: tone }]} />
      </View>
      {driver ? <Text style={styles.concernDriver}>{driver}</Text> : null}
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* Carte produit                                                       */
/* ------------------------------------------------------------------ */
function ProductCard({ p }: { p: ProductPick }) {
  const [open, setOpen] = useState(false);
  const actives = p.actives
    .map((a) => (a.pct ? `${a.common ?? a.inci} ${a.pct}%` : a.common ?? a.inci))
    .join(" · ");

  return (
    <Pressable
      style={styles.productCard}
      onPress={() => {
        Haptics.selectionAsync();
        setOpen((o) => !o);
      }}
      accessibilityRole="button"
      accessibilityLabel={`${p.brand} ${p.name}, adéquation ${p.match} pour cent`}
    >
      <View style={styles.productTop}>
        <ProductVisual product={p} size={52} />
        <View style={{ flex: 1 }}>
          <Text style={styles.productStep}>{STEP_LABEL[p.step] ?? p.step}</Text>
          <Text style={styles.productBrand}>{p.brand}</Text>
          <Text style={styles.productName} numberOfLines={2}>{p.name}</Text>
        </View>
        <View style={styles.matchPill}>
          <Text style={styles.matchVal}>{p.match}%</Text>
        </View>
      </View>

      {actives ? <Text style={styles.productActives}>{actives}</Text> : null}

      <View style={styles.productMeta}>
        {p.price_eur != null && (
          <Text style={styles.productPrice}>{p.price_eur.toFixed(2)} €</Text>
        )}
        {p.evidence?.level && (
          <View
            style={[
              styles.evBadge,
              p.evidence.level === "A" && { backgroundColor: colors.okSoft },
            ]}
          >
            <Text style={styles.evText}>
              Preuve {p.evidence.level}
            </Text>
          </View>
        )}
        {p.introduce_week > 1 && (
          <View style={styles.weekBadge}>
            <Text style={styles.weekText}>dès S{p.introduce_week}</Text>
          </View>
        )}
      </View>

      {open && (
        <View style={styles.productDetail}>
          {p.why.map((w, i) => (
            <Text key={i} style={styles.whyLine}>• {w}</Text>
          ))}
          {p.evidence?.note ? (
            <Text style={styles.evNote}>{p.evidence.note}</Text>
          ) : null}
          {p.evidence?.source ? (
            <Text style={styles.evSource}>Source : {p.evidence.source}</Text>
          ) : null}
          <View style={styles.buyRow}>
            {p.buy_url ? (
              <AnimatedPressable
                style={styles.buyBtn}
                haptic="medium"
                onPress={() => Linking.openURL(p.buy_url!)}
              >
                <Text style={styles.buyText}>Où l&apos;acheter</Text>
              </AnimatedPressable>
            ) : null}
            {/* Plus de lien profond vers le site de marque : sur les 28 liens
                distincts du catalogue, 8 renvoyaient deja une 404, et une page
                qui repond aujourd'hui peut disparaitre demain. Un lien mort au
                moment ou l'on demande d'acheter est le pire endroit pour
                echouer — on ne garde que la recherche, qui aboutit toujours. */}
          </View>
        </View>
      )}
    </Pressable>
  );
}

/* ------------------------------------------------------------------ */
/* Écran                                                               */
/* ------------------------------------------------------------------ */
export default function ScanResultScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { width } = useWindowDimensions();
  const [data, setData] = useState<FaceAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moment, setMoment] = useState<"am" | "pm">("am");
  const [zone, setZone] = useState<ZoneKey | null>(null);

  const pulse = useSharedValue(0);
  useEffect(() => {
    pulse.value = withRepeat(
      withTiming(1, { duration: 1400, easing: ease.sineInOut }),
      -1,
      true,
    );
  }, [pulse]);
  const pulseStyle = useAnimatedStyle(() => ({
    opacity: 0.45 + pulse.value * 0.55,
    transform: [{ scale: 0.97 + pulse.value * 0.06 }],
  }));

  // L'ecran ne calcule plus rien : l'analyse a ete faite et enregistree par
  // l'ecran d'analyse. On relit un scan par son identifiant, ce qui rend un
  // resultat consultable des semaines plus tard depuis l'historique.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!id) {
        router.replace("/camera");
        return;
      }
      const stored = await getScan(id);
      if (cancelled) return;
      if (!stored) {
        setError("Cette analyse n'est plus disponible sur cet appareil.");
        return;
      }
      setData(stored);
    })();
    return () => {
      cancelled = true;
    };
  }, [id, router]);

  const lesionTotal = useMemo(() => {
    if (!data) return 0;
    return Object.values(data.lesion_counts ?? {}).reduce((a, b) => a + b, 0);
  }, [data]);

  /* ---------- chargement ---------- */
  if (!data && !error) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingWrap}>
          <Animated.View style={[styles.loadingOrb, pulseStyle]} />
          <Text style={styles.loadingTitle}>Analyse en cours</Text>
          <Text style={styles.loadingHelper}>
            Segmentation du visage en 13 zones, détection des lésions et calcul
            de votre empreinte cutanée.
          </Text>
          <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.l }} />
        </View>
      </SafeAreaView>
    );
  }

  /* ---------- erreur ---------- */
  if (error || !data) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingWrap}>
          <Text style={styles.loadingTitle}>Analyse impossible</Text>
          <Text style={styles.loadingHelper}>{error}</Text>
          <AnimatedPressable
            style={styles.cta}
            onPress={() => router.replace("/camera")}
          >
            <Text style={styles.ctaText}>Reprendre une photo</Text>
          </AnimatedPressable>
        </View>
      </SafeAreaView>
    );
  }

  const zoneDetail = zone ? data.per_zone[zone] : null;
  const routine = data.routine[moment] ?? [];
  const mapSize = Math.min(width - spacing.xl * 2, 280);

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: spacing.xxxl }}
        showsVerticalScrollIndicator={false}
      >
        {/* En-tête */}
        <View style={styles.header}>
          <Pressable onPress={() => router.replace("/dashboard")} hitSlop={10}>
            <Text style={styles.headerBack}>← Tableau de bord</Text>
          </Pressable>
          <Text style={styles.headerDate}>
            {new Date().toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}
          </Text>
        </View>

        {/* Score + diagnostic */}
        <FadeIn>
          <View style={styles.hero}>
            <ScoreRing value={data.global_score} />
            <Text style={styles.diagnosis}>{data.diagnosis}</Text>
            <View style={styles.tagRow}>
              <View style={styles.tag}>
                <Text style={styles.tagText}>
                  Peau {SKIN_TYPE_LABEL[data.skin_type] ?? data.skin_type}
                </Text>
              </View>
              <View style={styles.tag}>
                <Text style={styles.tagText}>Phototype {data.phototype}</Text>
              </View>
              {data.severity_level > 0 && (
                <View style={[styles.tag, styles.tagAlert]}>
                  <Text style={[styles.tagText, styles.tagTextAlert]}>
                    {SEVERITY_LABEL[data.severity_level]}
                  </Text>
                </View>
              )}
            </View>
            <Text style={styles.summary}>{data.summary}</Text>
          </View>
        </FadeIn>

        {/* Cartographie */}
        <FadeIn delay={80}>
          <View style={styles.card}>
            <Text style={styles.cardEyebrow}>Cartographie · 13 zones</Text>
            <FaceZoneMap
              zoneScores={data.zone_scores}
              lesions={data.lesions}
              selected={zone}
              onSelectZone={(z) => {
                Haptics.selectionAsync();
                setZone(z);
              }}
              size={mapSize}
            />
            <ZoneLegend />
            {zoneDetail && zone ? (
              <View style={styles.zoneDetail}>
                <Text style={styles.zoneName}>{ZONE_LABEL[zone]}</Text>
                <Text style={styles.zoneStat}>
                  Note {data.zone_scores[zone]}/100 · {" "}
                  {Object.values(zoneDetail.lesions ?? {}).reduce((a, b) => a + b, 0)} lésions
                  {zoneDetail.hair_ratio > 0.25
                    ? ` · zone partiellement couverte par la pilosité (${Math.round(
                        zoneDetail.hair_ratio * 100,
                      )} %)`
                    : ""}
                </Text>
              </View>
            ) : (
              <Text style={styles.zoneHint}>Touchez une zone pour son détail</Text>
            )}
          </View>
        </FadeIn>

        {/* Lésions */}
        {lesionTotal > 0 && (
          <FadeIn delay={120}>
            <View style={styles.card}>
              <Text style={styles.cardEyebrow}>Lésions détectées · {lesionTotal}</Text>
              <View style={styles.lesionGrid}>
                {(Object.keys(data.lesion_counts) as LesionType[])
                  .filter((k) => data.lesion_counts[k] > 0)
                  .map((k) => (
                    <View key={k} style={styles.lesionChip}>
                      <Text style={styles.lesionCount}>{data.lesion_counts[k]}</Text>
                      <Text style={styles.lesionName}>{LESION_LABEL[k]}</Text>
                    </View>
                  ))}
              </View>
              {data.hormonal_pattern && (
                <Text style={styles.note}>
                  Répartition majoritairement mandibulaire, un profil souvent
                  associé à une composante hormonale. À évoquer avec un médecin
                  si les poussées suivent un cycle.
                </Text>
              )}
            </View>
          </FadeIn>
        )}

        {/* Empreinte cutanée */}
        <FadeIn delay={160}>
          <View style={styles.card}>
            <Text style={styles.cardEyebrow}>Votre empreinte cutanée</Text>
            {data.top_concerns.map((k, i) => (
              <ConcernRow key={k} k={k} v={data.concerns[k]} driver={data.drivers[k]} index={i} />
            ))}
          </View>
        </FadeIn>

        {/* Routine */}
        <FadeIn delay={200}>
          <View style={styles.card}>
            <View style={styles.routineHead}>
              <Text style={styles.cardEyebrow}>Votre routine</Text>
              <View style={styles.segment}>
                {(["am", "pm"] as const).map((m) => (
                  <Pressable
                    key={m}
                    onPress={() => {
                      Haptics.selectionAsync();
                      setMoment(m);
                    }}
                    style={[styles.segmentBtn, moment === m && styles.segmentActive]}
                  >
                    <Text
                      style={[styles.segmentText, moment === m && styles.segmentTextActive]}
                    >
                      {m === "am" ? "Matin" : "Soir"}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {routine.map((p) => (
              <ProductCard key={`${moment}-${p.id}`} p={p} />
            ))}

            <View style={styles.totalRow}>
              <Text style={styles.totalLabel}>Coût total de la routine</Text>
              <Text style={styles.totalValue}>
                {data.routine.total_price.toFixed(2)} €
              </Text>
            </View>
          </View>
        </FadeIn>

        {/* Plan d'introduction */}
        {data.routine.schedule?.length > 1 && (
          <FadeIn delay={240}>
            <View style={styles.card}>
              <Text style={styles.cardEyebrow}>{"Plan d'introduction"}</Text>
              <Text style={styles.scheduleIntro}>
                {"Introduire tous les actifs en même temps est la première cause " +
                  "d'échec d'une routine anti-acné : la peau réagit, et l'on " +
                  "abandonne. On y va progressivement."}
              </Text>
              {data.routine.schedule.map((s, i) => (
                <View key={i} style={styles.scheduleRow}>
                  <View style={styles.scheduleWeek}>
                    <Text style={styles.scheduleWeekText}>S{s.week}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.scheduleTitle}>{s.title}</Text>
                    <Text style={styles.scheduleDetail}>{s.detail}</Text>
                  </View>
                </View>
              ))}
            </View>
          </FadeIn>
        )}

        {/* Précautions */}
        {data.cautions?.length > 0 && (
          <FadeIn delay={280}>
            <View style={[styles.card, styles.cautionCard]}>
              <Text style={styles.cardEyebrow}>À savoir</Text>
              {data.cautions.map((c, i) => (
                <Text key={i} style={styles.cautionText}>{c}</Text>
              ))}
            </View>
          </FadeIn>
        )}

        <Text style={styles.disclaimer}>
          {"SKYN est un outil d'auto-suivi, pas un dispositif médical. Il ne pose " +
            "pas de diagnostic et ne remplace pas l'avis d'un dermatologue."}
        </Text>

        <AnimatedPressable
          style={styles.cta}
          onPress={() => router.replace("/routine")}
        >
          <Text style={styles.ctaText}>Commencer ma routine</Text>
        </AnimatedPressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  loadingWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
  },
  loadingOrb: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.accentSoft,
    marginBottom: spacing.l,
  },
  loadingTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    color: colors.fg,
    textAlign: "center",
  },
  loadingHelper: {
    fontFamily: fonts.body,
    fontSize: 14,
    lineHeight: 21,
    color: colors.fgMuted,
    textAlign: "center",
    marginTop: spacing.s,
  },

  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.l,
    paddingVertical: spacing.m,
  },
  headerBack: { fontFamily: fonts.body, fontSize: 13, color: colors.fgMuted },
  headerDate: { fontFamily: fonts.body, fontSize: 12, color: colors.fgDim },

  hero: { alignItems: "center", paddingHorizontal: spacing.xl, paddingTop: spacing.s },
  ringCenter: { flex: 1, alignItems: "center", justifyContent: "center" },
  ringValue: {
    fontFamily: fonts.display,
    fontSize: 46,
    color: colors.fg,
    letterSpacing: -2,
    lineHeight: 50,
  },
  ringUnit: { fontFamily: fonts.body, fontSize: 11, color: colors.fgDim, letterSpacing: 1 },

  diagnosis: {
    fontFamily: fonts.display,
    fontSize: 26,
    lineHeight: 31,
    color: colors.fg,
    textAlign: "center",
    marginTop: spacing.l,
    letterSpacing: -0.4,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.s,
    justifyContent: "center",
    marginTop: spacing.m,
  },
  tag: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.m,
    paddingVertical: 6,
  },
  tagAlert: { backgroundColor: colors.accentSofter },
  tagText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    color: colors.fg,
    textTransform: "capitalize",
  },
  tagTextAlert: { color: colors.accentDark },
  summary: {
    fontFamily: fonts.body,
    fontSize: 14,
    lineHeight: 22,
    color: colors.fgMuted,
    textAlign: "center",
    marginTop: spacing.m,
  },

  card: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    marginHorizontal: spacing.l,
    marginTop: spacing.l,
    padding: spacing.l,
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

  zoneHint: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fgDim,
    textAlign: "center",
    marginTop: spacing.m,
  },
  zoneDetail: {
    marginTop: spacing.m,
    padding: spacing.m,
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.md,
  },
  zoneName: { fontFamily: fonts.headingMedium, fontSize: 15, color: colors.fg },
  zoneStat: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 18,
    color: colors.fgMuted,
    marginTop: 2,
  },

  lesionGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s },
  lesionChip: {
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.md,
    paddingVertical: spacing.s,
    paddingHorizontal: spacing.m,
    minWidth: 84,
  },
  lesionCount: { fontFamily: fonts.display, fontSize: 22, color: colors.fg },
  lesionName: { fontFamily: fonts.body, fontSize: 11, color: colors.fgMuted },
  note: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 19,
    color: colors.fgMuted,
    marginTop: spacing.m,
  },

  concernRow: { marginBottom: spacing.m },
  concernHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: 6 },
  concernName: { fontFamily: fonts.bodyMedium, fontSize: 13, color: colors.fg },
  concernVal: { fontFamily: fonts.bodyMedium, fontSize: 13, color: colors.fgMuted },
  concernTrack: {
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.fgFaint,
    overflow: "hidden",
  },
  concernFill: { height: "100%", borderRadius: 4 },
  concernDriver: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.fgDim,
    marginTop: 5,
    lineHeight: 16,
  },

  routineHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.m,
  },
  segment: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.pill,
    padding: 3,
  },
  segmentBtn: {
    paddingHorizontal: spacing.m,
    paddingVertical: 6,
    borderRadius: radius.pill,
  },
  segmentActive: { backgroundColor: colors.fg },
  segmentText: { fontFamily: fonts.bodyMedium, fontSize: 12, color: colors.fgMuted },
  segmentTextActive: { color: colors.bg },

  productCard: {
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.md,
    padding: spacing.m,
    marginBottom: spacing.s,
  },
  buyRow: { flexDirection: "row", alignItems: "center", gap: spacing.m, marginTop: spacing.s },
  buyBtn: {
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 11,
    paddingHorizontal: spacing.l,
    minHeight: 44,
    justifyContent: "center",
  },
  buyText: {
    fontFamily: fonts.headingMedium,
    fontSize: 11,
    letterSpacing: 1.6,
    textTransform: "uppercase",
    color: colors.onAccent,
  },
  productTop: { flexDirection: "row", alignItems: "flex-start", gap: spacing.m },
  productStep: {
    fontFamily: fonts.bodyMedium,
    fontSize: 9,
    letterSpacing: 1.4,
    textTransform: "uppercase",
    color: colors.fgDim,
  },
  productBrand: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    color: colors.fgMuted,
    marginTop: 3,
  },
  productName: {
    fontFamily: fonts.headingMedium,
    fontSize: 15,
    color: colors.fg,
    lineHeight: 20,
  },
  matchPill: {
    backgroundColor: colors.ok,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.s,
    paddingVertical: 4,
  },
  matchVal: { fontFamily: fonts.headingMedium, fontSize: 13, color: colors.onOk },
  productActives: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.fgMuted,
    marginTop: spacing.s,
    lineHeight: 16,
  },
  productMeta: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    marginTop: spacing.s,
    flexWrap: "wrap",
  },
  productPrice: { fontFamily: fonts.bodyMedium, fontSize: 13, color: colors.fg },
  evBadge: {
    backgroundColor: colors.fgFaint,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.s,
    paddingVertical: 3,
  },
  evText: { fontFamily: fonts.body, fontSize: 10, color: colors.fg },
  weekBadge: {
    backgroundColor: colors.accentSofter,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.s,
    paddingVertical: 3,
  },
  weekText: { fontFamily: fonts.body, fontSize: 10, color: colors.accentDark },
  productDetail: {
    marginTop: spacing.m,
    paddingTop: spacing.m,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    gap: 4,
  },
  whyLine: { fontFamily: fonts.body, fontSize: 12, color: colors.fgMuted, lineHeight: 18 },
  evNote: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fg,
    lineHeight: 18,
    marginTop: 4,
  },
  evSource: { fontFamily: fonts.body, fontSize: 10, color: colors.fgDim, marginTop: 2 },
  link: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    color: colors.accent,
    marginTop: spacing.s,
  },

  totalRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.s,
    paddingTop: spacing.m,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
  },
  totalLabel: { fontFamily: fonts.body, fontSize: 13, color: colors.fgMuted },
  totalValue: { fontFamily: fonts.display, fontSize: 18, color: colors.fg },

  scheduleIntro: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 19,
    color: colors.fgMuted,
    marginBottom: spacing.m,
  },
  scheduleRow: { flexDirection: "row", gap: spacing.m, marginBottom: spacing.m },
  scheduleWeek: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: colors.okSofter,
    alignItems: "center",
    justifyContent: "center",
  },
  scheduleWeekText: { fontFamily: fonts.headingMedium, fontSize: 13, color: colors.fg },
  scheduleTitle: { fontFamily: fonts.headingMedium, fontSize: 14, color: colors.fg },
  scheduleDetail: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 18,
    color: colors.fgMuted,
    marginTop: 2,
  },

  cautionCard: { backgroundColor: colors.accentSofter },
  cautionText: {
    fontFamily: fonts.body,
    fontSize: 13,
    lineHeight: 20,
    color: colors.fg,
    marginBottom: spacing.s,
  },

  disclaimer: {
    fontFamily: fonts.body,
    fontSize: 11,
    lineHeight: 17,
    color: colors.fgDim,
    textAlign: "center",
    marginTop: spacing.l,
    paddingHorizontal: spacing.xl,
  },

  cta: {
    backgroundColor: colors.accent,
    marginHorizontal: spacing.l,
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
});
