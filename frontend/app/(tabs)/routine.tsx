import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { STEP_LABEL } from "@/src/types/analysis";
import type { ProductPick } from "@/src/types/analysis";
import {
  bestStreak,
  completionRate,
  currentStreak,
  getLog,
  getRoutine,
  recentDays,
  todayKey,
  toggleStep,
  type RoutineLog,
  type StoredRoutine,
} from "@/src/services/routineStore";

const DAY_INITIALS = ["D", "L", "M", "M", "J", "V", "S"];

/* ------------------------------------------------------------------ */
function StepRow({
  p,
  done,
  onToggle,
}: {
  p: ProductPick;
  done: boolean;
  onToggle: () => void;
}) {
  const s = useSharedValue(done ? 1 : 0);
  useEffect(() => {
    s.value = withSpring(done ? 1 : 0, { damping: 15, stiffness: 180 });
  }, [done, s]);

  const boxStyle = useAnimatedStyle(() => ({
    backgroundColor: s.value > 0.5 ? colors.lime : "transparent",
    borderColor: s.value > 0.5 ? colors.lime : colors.borderMid,
    transform: [{ scale: 0.9 + s.value * 0.1 }],
  }));

  return (
    <Pressable
      onPress={onToggle}
      style={styles.stepRow}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: done }}
      accessibilityLabel={`${STEP_LABEL[p.step] ?? p.step} : ${p.brand} ${p.name}`}
    >
      <Animated.View style={[styles.checkbox, boxStyle]}>
        {done ? <Text style={styles.checkMark}>✓</Text> : null}
      </Animated.View>
      <View style={{ flex: 1 }}>
        <Text style={styles.stepLabel}>{STEP_LABEL[p.step] ?? p.step}</Text>
        <Text style={[styles.stepName, done && styles.stepNameDone]} numberOfLines={1}>
          {p.brand} · {p.name}
        </Text>
      </View>
    </Pressable>
  );
}

/* ------------------------------------------------------------------ */
export default function RoutineScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [routine, setRoutine] = useState<StoredRoutine | null>(null);
  const [log, setLog] = useState<RoutineLog>({});
  const [moment, setMoment] = useState<"am" | "pm">(
    new Date().getHours() < 16 ? "am" : "pm",
  );
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const [r, l] = await Promise.all([getRoutine(), getLog()]);
    setRoutine(r);
    setLog(l);
    setLoaded(true);
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const today = todayKey();
  const doneToday = log[today] ?? { am: [], pm: [] };
  const streak = useMemo(() => currentStreak(log), [log]);
  const best = useMemo(() => bestStreak(log), [log]);
  const rate = useMemo(() => completionRate(log, 30), [log]);
  const days = useMemo(() => recentDays(log, 14), [log]);

  const steps = routine ? (moment === "am" ? routine.am : routine.pm) : [];
  const doneIds = doneToday[moment] ?? [];
  const allDone = steps.length > 0 && steps.every((p) => doneIds.includes(p.id));

  const progress = useSharedValue(0);
  useEffect(() => {
    const done = steps.filter((p) => doneIds.includes(p.id)).length;
    progress.value = withTiming(steps.length ? done / steps.length : 0, {
      duration: 420,
      easing: Easing.out(Easing.cubic),
    });
  }, [steps, doneIds, progress]);
  const progressStyle = useAnimatedStyle(() => ({
    width: `${progress.value * 100}%`,
  }));

  const onToggle = async (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const next = await toggleStep(moment, id);
    setLog({ ...next });
    const stepsNow = moment === "am" ? routine?.am ?? [] : routine?.pm ?? [];
    const nowDone = next[today]?.[moment] ?? [];
    if (stepsNow.length && stepsNow.every((p) => nowDone.includes(p.id))) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    }
  };

  /* ---------- aucun scan ---------- */
  if (loaded && !routine) {
    return (
      <SafeAreaView style={styles.container} edges={["top"]}>
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Pas encore de routine</Text>
          <Text style={styles.emptyHelper}>
            Lancez un premier scan : votre routine du matin et du soir sera
            construite à partir de ce que l'analyse mesure sur votre peau.
          </Text>
          <AnimatedPressable style={styles.cta} onPress={() => router.push("/camera")}>
            <Text style={styles.ctaText}>Scanner ma peau</Text>
          </AnimatedPressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: spacing.xxxl * 2 }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Ma routine</Text>
          <Text style={styles.subtitle}>{routine?.diagnosis}</Text>
        </View>

        {/* Série */}
        <FadeIn>
          <View style={styles.streakCard}>
            <View style={styles.streakTop}>
              <View>
                <Text style={styles.streakNum}>{streak}</Text>
                <Text style={styles.streakLabel}>
                  {streak <= 1 ? "jour d'affilée" : "jours d'affilée"}
                </Text>
              </View>
              <View style={styles.streakStats}>
                <View style={styles.streakStat}>
                  <Text style={styles.streakStatVal}>{best}</Text>
                  <Text style={styles.streakStatLabel}>record</Text>
                </View>
                <View style={styles.streakStat}>
                  <Text style={styles.streakStatVal}>{Math.round(rate * 100)}%</Text>
                  <Text style={styles.streakStatLabel}>sur 30 j</Text>
                </View>
              </View>
            </View>

            <View style={styles.dayGrid}>
              {days.map((d) => {
                const dt = new Date(d.day);
                const both = d.am && d.pm;
                const some = d.am || d.pm;
                return (
                  <View key={d.day} style={styles.dayCol}>
                    <View
                      style={[
                        styles.dayDot,
                        some && styles.dayDotSome,
                        both && styles.dayDotBoth,
                        d.day === today && styles.dayDotToday,
                      ]}
                    />
                    <Text style={styles.dayInitial}>{DAY_INITIALS[dt.getDay()]}</Text>
                  </View>
                );
              })}
            </View>
          </View>
        </FadeIn>

        {/* Aujourd'hui */}
        <FadeIn delay={80}>
          <View style={styles.card}>
            <View style={styles.cardHead}>
              <Text style={styles.cardEyebrow}>Aujourd'hui</Text>
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

            <View style={styles.progressTrack}>
              <Animated.View style={[styles.progressFill, progressStyle]} />
            </View>

            {steps.map((p) => (
              <StepRow
                key={p.id}
                p={p}
                done={doneIds.includes(p.id)}
                onToggle={() => onToggle(p.id)}
              />
            ))}

            {allDone && (
              <View style={styles.doneBanner}>
                <Text style={styles.doneText}>
                  {moment === "am" ? "Matin bouclé." : "Soir bouclé."} La
                  régularité compte davantage que le produit : les effets d'un
                  actif se jugent sur huit à douze semaines.
                </Text>
              </View>
            )}
          </View>
        </FadeIn>

        {/* Soin hebdomadaire */}
        {routine?.weekly?.length ? (
          <FadeIn delay={120}>
            <View style={styles.card}>
              <Text style={styles.cardEyebrow}>Une fois par semaine</Text>
              {routine.weekly.map((p) => (
                <Text key={p.id} style={styles.weeklyItem}>
                  {p.brand} · {p.name}
                </Text>
              ))}
            </View>
          </FadeIn>
        ) : null}

        <AnimatedPressable
          style={[styles.cta, { marginTop: spacing.l }]}
          onPress={() => router.push("/camera")}
        >
          <Text style={styles.ctaText}>Nouveau scan</Text>
        </AnimatedPressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: { paddingHorizontal: spacing.l, paddingTop: spacing.m, paddingBottom: spacing.s },
  title: { fontFamily: fonts.heading, fontSize: 30, color: colors.fg, letterSpacing: -0.6 },
  subtitle: { fontFamily: fonts.body, fontSize: 13, color: colors.fgMuted, marginTop: 2 },

  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
  },
  emptyTitle: { fontFamily: fonts.heading, fontSize: 24, color: colors.fg, textAlign: "center" },
  emptyHelper: {
    fontFamily: fonts.body,
    fontSize: 14,
    lineHeight: 21,
    color: colors.fgMuted,
    textAlign: "center",
    marginTop: spacing.s,
  },

  streakCard: {
    backgroundColor: colors.fg,
    borderRadius: radius.lg,
    marginHorizontal: spacing.l,
    marginTop: spacing.m,
    padding: spacing.l,
    ...shadow.raised,
  },
  streakTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  streakNum: {
    fontFamily: fonts.heading,
    fontSize: 52,
    color: colors.lime,
    lineHeight: 56,
    letterSpacing: -2,
  },
  streakLabel: { fontFamily: fonts.body, fontSize: 13, color: "rgba(255,248,242,0.7)" },
  streakStats: { flexDirection: "row", gap: spacing.l },
  streakStat: { alignItems: "flex-end" },
  streakStatVal: { fontFamily: fonts.headingMedium, fontSize: 18, color: colors.bg },
  streakStatLabel: { fontFamily: fonts.body, fontSize: 10, color: "rgba(255,248,242,0.5)" },

  dayGrid: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.l,
  },
  dayCol: { alignItems: "center", gap: 5 },
  dayDot: {
    width: 15,
    height: 15,
    borderRadius: 8,
    backgroundColor: "rgba(255,248,242,0.12)",
  },
  dayDotSome: { backgroundColor: "rgba(200,240,74,0.45)" },
  dayDotBoth: { backgroundColor: colors.lime },
  dayDotToday: { borderWidth: 1.5, borderColor: colors.bg },
  dayInitial: { fontFamily: fonts.body, fontSize: 9, color: "rgba(255,248,242,0.45)" },

  card: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    marginHorizontal: spacing.l,
    marginTop: spacing.l,
    padding: spacing.l,
    ...shadow.card,
  },
  cardHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.m,
  },
  cardEyebrow: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: colors.fgDim,
  },

  segment: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.pill,
    padding: 3,
  },
  segmentBtn: { paddingHorizontal: spacing.m, paddingVertical: 6, borderRadius: radius.pill },
  segmentActive: { backgroundColor: colors.fg },
  segmentText: { fontFamily: fonts.bodyMedium, fontSize: 12, color: colors.fgMuted },
  segmentTextActive: { color: colors.bg },

  progressTrack: {
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.fgFaint,
    overflow: "hidden",
    marginBottom: spacing.m,
  },
  progressFill: { height: "100%", backgroundColor: colors.lime, borderRadius: 3 },

  stepRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    paddingVertical: spacing.s + 2,
  },
  checkbox: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 1.5,
    alignItems: "center",
    justifyContent: "center",
  },
  checkMark: { fontFamily: fonts.bodyMedium, fontSize: 14, color: colors.onLime },
  stepLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 9,
    letterSpacing: 1.3,
    textTransform: "uppercase",
    color: colors.fgDim,
  },
  stepName: { fontFamily: fonts.body, fontSize: 14, color: colors.fg, marginTop: 1 },
  stepNameDone: { color: colors.fgDim, textDecorationLine: "line-through" },

  doneBanner: {
    marginTop: spacing.m,
    padding: spacing.m,
    backgroundColor: colors.limeSofter,
    borderRadius: radius.md,
  },
  doneText: { fontFamily: fonts.body, fontSize: 12, lineHeight: 19, color: colors.fg },

  weeklyItem: {
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.fg,
    paddingVertical: 4,
  },

  cta: {
    backgroundColor: colors.accent,
    marginHorizontal: spacing.l,
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
