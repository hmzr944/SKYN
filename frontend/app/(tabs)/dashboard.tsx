import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Dimensions, ActivityIndicator } from "react-native";
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedScrollHandler,
  useAnimatedStyle,
  useSharedValue,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Svg, { Polyline, Circle, Defs, LinearGradient as SvgLinearGradient, Stop, Polygon } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { syncPendingReports } from "@/src/services/api";
import { listScans, type ScanSummary } from "@/src/services/scanStore";
import { CONCERN_LABEL, SEVERITY_LABEL, SKIN_TYPE_LABEL } from "@/src/types/analysis";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { Swap } from "@/src/components/ui/Swap";
import { Stagger } from "@/src/components/ui/Reveal";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { SkynMarkStill } from "@/src/components/brand/SkynMark";
import { AnimatedNumber } from "@/src/components/ui/AnimatedNumber";
import { accord, useGenre } from "@/src/services/gender";

const { width: SCREEN_W } = Dimensions.get("window");
const CHART_W = SCREEN_W - spacing.xl * 2 - spacing.m * 2;
const CHART_H = 110;

/** Hauteur de la barre compacte : elle sort d'exactement sa propre hauteur. */
const COMPACT_H = 48;

const TIPS = [
  "Hydratez votre peau matin et soir avec une crème adaptée à votre type de peau.",
  "Appliquez une protection solaire SPF 30+ chaque matin, même par temps couvert.",
  "Buvez au moins 1,5L d'eau par jour pour soutenir l'hydratation cutanée.",
  "Évitez de toucher votre visage pour limiter le transfert de bactéries.",
  "Démaquillez-vous systématiquement avant de dormir.",
  "Privilégiez un nettoyant doux, sans sulfates agressifs.",
];

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
  const linePoints = scores
    .map(
      (s, i) =>
        `${padX + i * step},${padY + innerH - ((s - min) / range) * innerH}`,
    )
    .join(" ");
  const areaPoints =
    `${padX},${padY + innerH} ` +
    linePoints +
    ` ${padX + (scores.length - 1) * step},${padY + innerH}`;
  return (
    <Svg width={CHART_W} height={CHART_H}>
      <Defs>
        <SvgLinearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={colors.accent} stopOpacity={0.25} />
          <Stop offset="1" stopColor={colors.accent} stopOpacity={0} />
        </SvgLinearGradient>
      </Defs>
      <Polygon points={areaPoints} fill="url(#areaFill)" />
      <Polyline
        points={linePoints}
        fill="none"
        stroke={colors.accent}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {scores.map((s, i) => (
        <Circle
          key={i}
          cx={padX + i * step}
          cy={padY + innerH - ((s - min) / range) * innerH}
          r={3.5}
          fill={colors.surface}
          stroke={colors.accent}
          strokeWidth={2}
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
  const { user } = useAuth();
  const genre = useGenre();
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const synced = await syncPendingReports();
      if (synced > 0) {
        setSyncMsg(`${synced} bilan${synced > 1 ? "s" : ""} synchronisé${synced > 1 ? "s" : ""}.`);
        setTimeout(() => setSyncMsg(null), 3000);
      }
      // Les scans locaux sont la source unique : le miroir serveur peut etre
      // en retard ou absent, l'accueil ne doit pas en dependre pour exister.
      setScans(await listScans());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useFocusEffect(
    useCallback(() => { load(); }, [load]),
  );

  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera");
  };

  // Entree experimentale vers la memoire persistante (chantier 5) : carte
  // de peau -> scan guide -> What Changed?, en parallele du scan 3 angles
  // ci-dessus qui reste le parcours par defaut. Volontairement discrete :
  // c'est un mode beta, pas une alternative mise en avant tant qu'il n'a
  // pas ete verifie sur de vrais scans.
  const goSkinMap = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.push("/skin-map");
  };

  // La position de defilement pilote la barre compacte. Elle vit sur le thread
  // d'animation : la barre suit le doigt image par image, sans passer par React.
  const scrollY = useSharedValue(0);
  const onScroll = useAnimatedScrollHandler((e) => {
    scrollY.value = e.contentOffset.y;
  });

  const compactStyle = useAnimatedStyle(() => {
    const p = interpolate(scrollY.value, [56, 116], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: p,
      transform: [{ translateY: -COMPACT_H * (1 - p) }],
    };
  });

  const last = scans[0];
  const previous = scans[1];
  const delta = last && previous ? last.global_score - previous.global_score : null;
  const chartScores = [...scans].reverse().slice(-4).map((r) => r.global_score);
  const firstName = (user?.name || "Vous").split(" ")[0];
  const dayIndex = new Date().getDate();
  const tips = [TIPS[dayIndex % TIPS.length], TIPS[(dayIndex + 1) % TIPS.length]];

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      {/* La barre compacte descend quand la grande salutation est passee : le
          contexte ne disparait pas, il change de forme. C'est un objet qui se
          deplace en reponse au doigt, pas une apparition decidee a l'avance. */}
      <Animated.View style={[styles.compact, compactStyle]} pointerEvents="none">
        <SkynMarkStill size={20} />
        <Text style={styles.compactText} numberOfLines={1}>
          Bonjour, {firstName}.
        </Text>
      </Animated.View>

      <Animated.ScrollView
        onScroll={onScroll}
        scrollEventThrottle={16}
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        {/* Le logotype est deja en place, sans entree a lui : la marque de
            l'ouverture vient de s'y poser, et une entree ici la ferait bouger
            sous elle au moment de l'echange. Le reste de l'en-tete se depose. */}
        <View style={styles.headerRow}>
          <SkynLockup size={24} still />
        </View>
        <FadeIn distance={10}>
          <Text style={styles.greeting} numberOfLines={1}>
            Bonjour, {firstName}.
          </Text>
          <Text style={styles.date}>{todayLabel()}</Text>
        </FadeIn>

        {syncMsg ? (
          <FadeIn distance={6}>
            <View style={styles.syncBanner}>
              <Text style={styles.syncMsg} testID="dashboard-sync-msg">
                {syncMsg}
              </Text>
            </View>
          </FadeIn>
        ) : null}

        {/* L'attente ne disparait pas : elle cede la place. Le rond s'efface
            vers le haut pendant que la carte arrive par en dessous, et la
            hauteur du bloc ne saute pas entre les deux. Le Swap porte seul
            cette entree : un FadeIn en plus dedans multiplierait les deux. */}
        <Swap etat={loading ? "attente" : !last ? "vide" : "rempli"}>
          {loading ? (
            <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.xxl }} />
          ) : !last ? (
            <View style={styles.heroCard}>
              <Text style={styles.heroTitle}>
                {accord(genre, {
                  f: "Prête pour votre\npremière analyse ?",
                  m: "Prêt pour votre\npremière analyse ?",
                  n: "On commence par\nune première analyse ?",
                })}
              </Text>
              <Text style={styles.heroSubtitle}>
                {"Découvrez l'état réel de votre peau."}
              </Text>
              <AnimatedPressable
                testID="dashboard-start-btn"
                style={styles.heroBtn}
                onPress={goScan}
              >
                <Text style={styles.heroBtnText}>{"Lancer l'analyse"}</Text>
              </AnimatedPressable>
            </View>
          ) : (
            <AnimatedPressable
              testID="dashboard-last-scan-card"
              style={styles.scoreCard}
              scaleTo={0.985}
              onPress={() => router.push(`/scan-result?id=${last.id}`)}
            >
              <Text style={styles.scoreLabel}>
                DERNIER SCAN ·{" "}
                {new Date(last.date).toLocaleDateString("fr-FR", {
                  day: "2-digit",
                  month: "long",
                })}
              </Text>
              <View style={styles.scoreRow}>
                <AnimatedNumber
                  value={last.global_score}
                  // Un TextInput ne se retrecit pas au contenu : il faut lui
                  // donner sa largeur. Le score va de 0 a 100, donc deux cas.
                  style={[styles.scoreValue, { width: last.global_score >= 100 ? 112 : 78 }]}
                />
                <View style={styles.scoreUnit}>
                  <Text style={styles.scoreMax} numberOfLines={1}>
                    / 100
                  </Text>
                  {delta !== null && delta !== 0 ? (
                    <Text
                      style={[styles.delta, delta > 0 ? styles.deltaUp : styles.deltaDown]}
                      numberOfLines={1}
                    >
                      {delta > 0 ? `+${delta}` : delta}
                    </Text>
                  ) : null}
                </View>
              </View>
              <Stagger
                style={styles.pillsRow}
                direction="left"
                distance={18}
                delay={220}
                amount={140}
              >
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>{SEVERITY_LABEL[last.severity_level]}</Text>
                </View>
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>Peau</Text>
                  <Text style={styles.pillValue}>{SKIN_TYPE_LABEL[last.skin_type]}</Text>
                </View>
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>Lésions</Text>
                  <Text style={styles.pillValue}>{last.lesion_total}</Text>
                </View>
              </Stagger>
              {last.top_concerns.length > 0 ? (
                <Text style={styles.scoreConcerns} numberOfLines={1}>
                  {last.top_concerns.slice(0, 3).map((c) => CONCERN_LABEL[c]).join(" · ")}
                </Text>
              ) : null}
            </AnimatedPressable>
          )}
        </Swap>

        {/* Chart */}
        {!loading && scans.length > 0 ? (
          <FadeIn delay={140}>
            <View style={styles.chartCard}>
              <Text style={styles.chartLabel}>EVOLUTION SUR 4 SCANS</Text>
              <View style={styles.chartWrap}>
                <ScoreChart scores={chartScores} />
              </View>
            </View>
          </FadeIn>
        ) : null}

        {/* Conseils du jour */}
        <FadeIn delay={200}>
          <Text style={styles.sectionTitle}>Conseils du jour</Text>
        </FadeIn>
        <FadeIn delay={240}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.tipsRow}
          >
            {tips.map((tip, i) => (
              <View key={i} style={styles.tipCard}>
                <Text style={styles.tipNumber}>{String(i + 1).padStart(2, "0")}</Text>
                <Text style={styles.tipText}>{tip}</Text>
              </View>
            ))}
          </ScrollView>
        </FadeIn>

        {last ? (
          <FadeIn delay={300}>
            <AnimatedPressable
              testID="dashboard-new-scan-btn"
              style={styles.cta}
              onPress={goScan}
            >
              <Text style={styles.ctaText}>Analyser ma peau</Text>
            </AnimatedPressable>
          </FadeIn>
        ) : null}

        <FadeIn delay={340}>
          <AnimatedPressable
            testID="dashboard-guided-scan-link"
            style={styles.guidedLink}
            haptic={false}
            onPress={goSkinMap}
          >
            <Text style={styles.guidedLinkText}>Découvrir votre carte de peau (bêta)</Text>
          </AnimatedPressable>
        </FadeIn>
      </Animated.ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  compact: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 5,
    height: COMPACT_H,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    paddingHorizontal: spacing.xl,
    backgroundColor: colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
  },
  compactText: {
    fontFamily: fonts.headingMedium,
    fontSize: 15,
    color: colors.fg,
    letterSpacing: -0.2,
  },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.xxl,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.l,
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 22,
    color: colors.accent,
    letterSpacing: 4,
  },
  greeting: {
    fontFamily: fonts.display,
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
    marginBottom: spacing.l,
    textTransform: "uppercase",
  },
  syncBanner: {
    marginBottom: spacing.s,
    backgroundColor: colors.okSoft,
    borderRadius: radius.sm,
    paddingVertical: 8,
  },
  syncMsg: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 11,
    textAlign: "center",
    letterSpacing: 1.5,
  },
  heroCard: {
    backgroundColor: colors.accent,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginBottom: spacing.xl,
  },
  heroTitle: {
    fontFamily: fonts.display,
    fontSize: 28,
    color: colors.onAccent,
    lineHeight: 34,
    marginBottom: spacing.s,
  },
  heroSubtitle: {
    fontFamily: fonts.body,
    fontSize: 14,
    // Sur le corail, une demi-teinte tombe a 3,7:1 : le sous-titre est en
    // terre plein, comme le titre. La hierarchie passe par la taille.
    color: colors.onAccent,
    marginBottom: spacing.l,
  },
  heroBtn: {
    alignSelf: "flex-start",
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.l,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  heroBtnText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  scoreCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.l,
    marginBottom: spacing.xl,
  },
  scoreLabel: {
    fontFamily: fonts.body,
    fontSize: 10,
    letterSpacing: 1.5,
    color: colors.fgDim,
    textTransform: "uppercase",
    marginBottom: spacing.s,
  },
  scoreRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    marginBottom: spacing.l,
  },
  // Le "/ 100" et l'ecart se serrent contre le score au lieu d'etre pousses
  // au bord de la carte. Le score est un TextInput, et un TextInput s'etale
  // jusqu'a la place disponible : sans cette boite, il repoussait le reste
  // jusqu'a le faire passer a la ligne, ce qui donnait un "/" seul au-dessus
  // de "100".
  scoreUnit: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: spacing.s,
    flexShrink: 0,
    paddingBottom: 12,
  },
  scoreValue: {
    fontFamily: fonts.display,
    fontSize: 64,
    color: colors.accent,
    letterSpacing: -1,
    // Le TextInput porte des marges natives qu'il faut neutraliser pour
    // qu'il s'aligne exactement comme le Text qu'il remplace.
    padding: 0,
    margin: 0,
    fontVariant: ["tabular-nums"],
  },
  delta: { fontFamily: fonts.heading, fontSize: 15, marginLeft: spacing.s },
  deltaUp: { color: colors.accent },
  deltaDown: { color: colors.fgDim },
  scoreConcerns: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fgMuted,
    marginTop: spacing.s,
  },
  scoreMax: { fontFamily: fonts.body, fontSize: 16, color: colors.fgDim },
  pillsRow: {
    flexDirection: "row",
    // Trois pastilles ne tiennent pas sur une ligne de 320 px : elles passent
    // a la ligne au lieu d'etre rognees par le bord de la carte.
    flexWrap: "wrap",
    gap: spacing.s,
  },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: spacing.s,
  },
  pillDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.ok,
  },
  pillLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    color: colors.fg,
  },
  pillValue: {
    fontFamily: fonts.headingMedium,
    fontSize: 13,
    color: colors.accent,
  },
  chartCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: spacing.m,
    marginBottom: spacing.xl,
    ...shadow.card,
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
  sectionTitle: {
    fontFamily: fonts.display,
    fontSize: 20,
    color: colors.fg,
    letterSpacing: -0.3,
    marginBottom: spacing.m,
  },
  tipsRow: {
    gap: spacing.s,
    paddingBottom: spacing.xl,
  },
  tipCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.m,
    minWidth: 220,
    maxWidth: 240,
  },
  tipNumber: {
    fontFamily: fonts.display,
    fontSize: 28,
    color: colors.accentSoft,
    marginBottom: spacing.xs,
  },
  tipText: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fg,
    lineHeight: 19,
  },
  cta: {
    backgroundColor: colors.accent,
    paddingVertical: 18,
    alignItems: "center",
    borderRadius: radius.pill,
    ...shadow.button,
  },
  ctaText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  guidedLink: {
    alignItems: "center",
    paddingVertical: spacing.m,
  },
  guidedLinkText: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgDim,
    textDecorationLine: "underline",
  },
});
