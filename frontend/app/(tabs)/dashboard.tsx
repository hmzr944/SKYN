import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, useWindowDimensions, ActivityIndicator } from "react-native";
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
import { useTranslation } from "@/src/i18n";
import { api, syncPendingReports } from "@/src/services/api";
import { listUnifiedScans, type UnifiedScan } from "@/src/services/scanHistory";
import {
  isTreatmentCheckpointOverdue,
  phaseVerdict,
  PHASE_VERDICT_LABEL,
  upcomingCheckpoint,
} from "@/src/services/skinMemory";
import { CONCERN_LABEL, SEVERITY_LABEL, SKIN_TYPE_LABEL } from "@/src/types/analysis";
import type { ActivePeriodView } from "@/src/types/skinMemory";
import { useAuth } from "@/src/contexts/AuthContext";
import { AmbientBackground } from "@/src/components/ui/AmbientBackground";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { Swap } from "@/src/components/ui/Swap";
import { Reveal, Stagger } from "@/src/components/ui/Reveal";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { SkynMarkStill } from "@/src/components/brand/SkynMark";
import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { SkinChangePill } from "@/src/components/skinMemory/SkinChangePill";
import { AnimatedNumber } from "@/src/components/ui/AnimatedNumber";
import { accord, useGenre } from "@/src/services/gender";

/** Hauteur de la barre compacte : elle sort d'exactement sa propre hauteur. */
const COMPACT_H = 48;

function ScoreChart({ scores, width, height }: { scores: number[]; width: number; height: number }) {
  const { t } = useTranslation();
  if (scores.length === 0) {
    return (
      <View style={[styles.chartEmpty, { width, height }]}>
        <Text style={styles.chartEmptyText}>{t("dashboard.chartEmpty")}</Text>
      </View>
    );
  }
  const min = Math.min(...scores, 50);
  const max = Math.max(...scores, 100);
  const range = Math.max(1, max - min);
  const padX = 4;
  const padY = 16;
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;
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
    <Svg width={width} height={height}>
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

function todayLabel(locale: string) {
  return new Date().toLocaleDateString(locale === "en" ? "en-US" : "fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export default function DashboardScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const genre = useGenre();
  const { t, locale } = useTranslation();
  const { width: screenW } = useWindowDimensions();
  const chartW = screenW - spacing.xl * 2 - spacing.m * 2;
  const chartH = 110;
  const TIPS = [
    t("dashboard.tip1"), t("dashboard.tip2"), t("dashboard.tip3"),
    t("dashboard.tip4"), t("dashboard.tip5"), t("dashboard.tip6"),
  ];
  const [scans, setScans] = useState<UnifiedScan[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [activePeriod, setActivePeriod] = useState<ActivePeriodView | null | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const synced = await syncPendingReports();
      if (synced > 0) {
        setSyncMsg(t("dashboard.synced", { count: synced, s: synced > 1 ? "s" : "" }));
        setTimeout(() => setSyncMsg(null), 3000);
      }
      // skin_memory (le scan guide) est la source canonique, fusionnee a
      // l'affichage avec le residu local du flux /camera — voir scanHistory.ts.
      setScans(await listUnifiedScans());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  useFocusEffect(
    useCallback(() => { load(); }, [load]),
  );

  // Une seule lecture de la Phase active nourrit a la fois la relance de
  // checkpoint manque et la carte "memoire de peau" ci-dessous — deux
  // lectures separees du meme /api/periods/active auraient pu diverger
  // (l'une chargee, l'autre pas) sans jamais rien apporter de plus.
  // Silencieux en cas d'echec : ni l'un ni l'autre n'est une donnee dont le
  // reste du tableau de bord depend.
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      (async () => {
        try {
          const view = await api.getActivePeriod();
          if (!cancelled) setActivePeriod(view);
        } catch {
          if (!cancelled) setActivePeriod(null);
        }
      })();
      return () => {
        cancelled = true;
      };
    }, []),
  );

  const overdueTreatment = activePeriod && isTreatmentCheckpointOverdue(activePeriod) ? activePeriod.period.label : null;
  const nextCheckpoint = activePeriod && !overdueTreatment ? upcomingCheckpoint(activePeriod.period) : null;

  // Le scan guide est desormais LE parcours principal, pas une variante
  // beta a cote : c'est le seul qui alimente la Memoire de peau (Phases,
  // What Changed?) — voir analysis-guided.tsx. L'ancien scan 3 angles
  // (/camera) reste dans le code, mais plus derriere aucun bouton
  // principal ; un scan qui n'ecrit jamais dans la memoire n'a plus sa
  // place ici.
  const goScan = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/camera-guided");
  };

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

  // La carte "dernier scan" a besoin d'un score : un scan memoire dont le
  // second calcul (analyze_multi) a echoue n'en porte pas (voir server.py)
  // — rarissime, mais on saute proprement a l'entree suivante plutot que
  // d'afficher un score invente.
  const scored = scans.filter((s): s is UnifiedScan & { global_score: number } => s.global_score !== null);
  const last = scored[0];
  const previous = scored[1];
  const delta = last && previous ? last.global_score - previous.global_score : null;
  const chartScores = [...scored].reverse().slice(-4).map((r) => r.global_score);
  const firstName = (user?.name || t("common.you")).split(" ")[0];
  const greeting = t("dashboard.greeting", { name: firstName });
  const dayIndex = new Date().getDate();
  const tips = [TIPS[dayIndex % TIPS.length], TIPS[(dayIndex + 1) % TIPS.length]];

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <AmbientBackground />
      {/* La barre compacte descend quand la grande salutation est passee : le
          contexte ne disparait pas, il change de forme. C'est un objet qui se
          deplace en reponse au doigt, pas une apparition decidee a l'avance. */}
      <Animated.View style={[styles.compact, compactStyle]} pointerEvents="none">
        <SkynMarkStill size={20} />
        <Text style={styles.compactText} numberOfLines={1}>
          {greeting}
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
        <Reveal bouncy distance={10}>
          <Text style={styles.greeting} numberOfLines={1}>
            {greeting}
          </Text>
          <Text style={styles.date}>{todayLabel(locale)}</Text>
        </Reveal>

        {syncMsg ? (
          <FadeIn distance={6}>
            <View style={styles.syncBanner}>
              <Text style={styles.syncMsg} testID="dashboard-sync-msg">
                {syncMsg}
              </Text>
            </View>
          </FadeIn>
        ) : null}

        {overdueTreatment ? (
          <FadeIn distance={8}>
            <AnimatedPressable
              testID="dashboard-overdue-checkpoint-banner"
              style={styles.overdueBanner}
              haptic="light"
              onPress={goScan}
            >
              <Text style={styles.overdueTitle}>{overdueTreatment}</Text>
              <Text style={styles.overdueText}>
                Vous n&apos;avez pas encore refait de scan sur cette Phase. Faites le point.
              </Text>
            </AnimatedPressable>
          </FadeIn>
        ) : null}

        {/* Le centre de la mémoire : ce que la Phase active raconte,
            au-dessus du score isolé — SKYN se souvient, il ne se contente
            pas de mesurer une fois. Rien de nouveau ici : mêmes données
            (/api/periods/active), mêmes composants (SkinChangePill,
            PhaseHalo) que skin-map.tsx et phase-summary.tsx. */}
        {activePeriod ? (
          <FadeIn delay={60}>
            <AnimatedPressable
              testID="dashboard-memory-card"
              style={styles.memoryCard}
              scaleTo={0.99}
              onPress={() => router.push(`/phase-summary?id=${activePeriod.period.id}`)}
            >
              <View style={styles.memoryHead}>
                <PhaseHalo
                  size={40}
                  tone={
                    activePeriod.state !== "baseline" && phaseVerdict(activePeriod.changes) === "watch"
                      ? "watch"
                      : "calm"
                  }
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.memoryTitle}>{activePeriod.period.label ?? "Votre Phase actuelle"}</Text>
                  <Text style={styles.memorySub}>
                    Depuis le{" "}
                    {new Date(activePeriod.period.starts_at).toLocaleDateString(
                      locale === "en" ? "en-US" : "fr-FR",
                      { day: "numeric", month: "long" },
                    )}
                  </Text>
                </View>
              </View>

              {activePeriod.state === "baseline" ? (
                <Text style={styles.memoryNote}>Pas encore assez de données pour comparer.</Text>
              ) : activePeriod.changes.length > 0 ? (
                <View style={styles.memoryPills}>
                  {activePeriod.changes.slice(0, 2).map((c) => (
                    <SkinChangePill key={`${c.kind}-${c.metric}`} item={c} />
                  ))}
                </View>
              ) : (
                <Text style={styles.memoryNote}>{PHASE_VERDICT_LABEL.insufficient}</Text>
              )}

              {nextCheckpoint ? (
                <Text style={styles.memoryNext}>
                  Prochain scan conseillé · J+{nextCheckpoint.day} ·{" "}
                  {nextCheckpoint.date.toLocaleDateString(locale === "en" ? "en-US" : "fr-FR", {
                    day: "numeric",
                    month: "long",
                  })}
                </Text>
              ) : null}

              <Text style={styles.memoryLink}>Voir le Bilan</Text>
            </AnimatedPressable>
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
                  f: t("dashboard.heroTitleF"),
                  m: t("dashboard.heroTitleM"),
                  n: t("dashboard.heroTitleN"),
                })}
              </Text>
              <Text style={styles.heroSubtitle}>{t("dashboard.heroSubtitle")}</Text>
              <AnimatedPressable
                testID="dashboard-start-btn"
                style={styles.heroBtn}
                onPress={goScan}
              >
                <Text style={styles.heroBtnText}>{t("dashboard.startAnalysis")}</Text>
              </AnimatedPressable>
            </View>
          ) : (
            <AnimatedPressable
              testID="dashboard-last-scan-card"
              style={styles.scoreCard}
              scaleTo={0.985}
              onPress={() =>
                router.push(
                  last.origin === "memory" ? `/phase-summary?id=${last.period_id}` : `/scan-result?id=${last.id}`,
                )
              }
            >
              <Text style={styles.scoreLabel}>
                {t("dashboard.lastScan")} ·{" "}
                {new Date(last.date).toLocaleDateString(locale === "en" ? "en-US" : "fr-FR", {
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
                    {t("dashboard.max100")}
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
                {last.severity_level !== null ? (
                  <View style={styles.pill}>
                    <View style={styles.pillDot} />
                    <Text style={styles.pillLabel}>{SEVERITY_LABEL[last.severity_level]}</Text>
                  </View>
                ) : null}
                {last.skin_type ? (
                  <View style={styles.pill}>
                    <View style={styles.pillDot} />
                    <Text style={styles.pillLabel}>{t("dashboard.skinLabel")}</Text>
                    <Text style={styles.pillValue}>{SKIN_TYPE_LABEL[last.skin_type]}</Text>
                  </View>
                ) : null}
                <View style={styles.pill}>
                  <View style={styles.pillDot} />
                  <Text style={styles.pillLabel}>{t("dashboard.lesionsLabel")}</Text>
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
        {!loading && scored.length > 0 ? (
          <FadeIn delay={140}>
            <View style={styles.chartCard}>
              <Text style={styles.chartLabel}>
                {t("dashboard.chartTitle", { count: chartScores.length, s: chartScores.length > 1 ? "S" : "" })}
              </Text>
              <View style={styles.chartWrap}>
                <ScoreChart scores={chartScores} width={chartW} height={chartH} />
              </View>
            </View>
          </FadeIn>
        ) : null}

        {/* Conseils du jour */}
        <FadeIn delay={200}>
          <Text style={styles.sectionTitle}>{t("dashboard.tipsTitle")}</Text>
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
              <Text style={styles.ctaText}>{t("dashboard.analyzeSkin")}</Text>
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
            <Text style={styles.guidedLinkText}>{t("dashboard.discoverSkinMap")}</Text>
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
  overdueBanner: {
    backgroundColor: colors.accentSofter,
    borderWidth: 1,
    borderColor: colors.accentLine,
    borderRadius: radius.lg,
    padding: spacing.m,
    marginBottom: spacing.l,
  },
  overdueTitle: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.accentDark,
    marginBottom: 3,
  },
  overdueText: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 17,
    color: colors.fg,
  },
  memoryCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: spacing.l,
    marginBottom: spacing.l,
    gap: spacing.s,
    ...shadow.card,
  },
  memoryHead: { flexDirection: "row", alignItems: "center", gap: spacing.m },
  memoryTitle: { fontFamily: fonts.headingMedium, fontSize: 16, color: colors.fg },
  memorySub: { fontFamily: fonts.body, fontSize: 12, color: colors.fgDim, marginTop: 2 },
  memoryNote: { fontFamily: fonts.body, fontSize: 13, color: colors.fgMuted },
  memoryPills: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s },
  memoryNext: { fontFamily: fonts.body, fontSize: 12, color: colors.fgDim },
  memoryLink: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    color: colors.accent,
    textDecorationLine: "underline",
    marginTop: 2,
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
