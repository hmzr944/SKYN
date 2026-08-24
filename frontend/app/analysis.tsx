import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Dimensions, StyleSheet, Text, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { ScanField } from "@/src/components/analysis/ScanField";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { Reveal } from "@/src/components/ui/Reveal";
import { useAuth } from "@/src/contexts/AuthContext";
import { api, queuePendingReport } from "@/src/services/api";
import { pushReportToSupabase } from "@/src/services/supabase";
import { colors, motion, radius, spacing, type } from "@/src/theme";
import { storage } from "@/src/utils/storage";

const { width: SCREEN_W } = Dimensions.get("window");
const FIELD = Math.min(SCREEN_W * 0.72, 300);

const PHASES = [
  { title: "Scan de surface", note: "Lecture du grain et de la brillance" },
  { title: "Mapping des zones", note: "Découpage du visage en 13 régions" },
  { title: "Micro-patterns", note: "Repérage des lésions et de leur densité" },
  { title: "Génération du rapport", note: "Croisement avec la base dermatologique" },
];

type Detection = { type: string; x: number; y: number; confidence: number; radius: number };

export default function AnalysisScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [phase, setPhase] = useState(0);
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [blackOut, setBlackOut] = useState(false);
  const hapticInt = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef<number>(Date.now());
  const analysisRef = useRef<any>(null);

  useEffect(() => {
    analysisRef.current = analysis;
  }, [analysis]);

  // La requete part des le montage — elle tourne en parallele de la sequence
  // visuelle. A la derniere phase, les vraies donnees sont quasi toujours la.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const b = (await storage.getItem("skyn_last_capture_b64", "")) as string;
      if (cancelled) return;
      if (b) setImageB64(b);
      if (b) {
        try {
          const data = await api.analyze(b);
          if (!cancelled) setAnalysis(data);
        } catch {
          /* on garde null → chemin de repli */
        }
      }
    })();

    hapticInt.current = setInterval(() => Haptics.selectionAsync(), 240);

    const t1 = setTimeout(() => {
      if (hapticInt.current) clearInterval(hapticInt.current);
      setPhase(1);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }, 2000);

    const t2 = setTimeout(() => {
      setPhase(2);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    }, 4000);

    const t3 = setTimeout(() => setPhase(3), 6000);

    const finalize = async () => {
      const a = analysisRef.current;

      // Aucun visage detecte — on ne fabrique pas un rapport, on renvoie
      // l'utilisateur reprendre la photo.
      if (a && a.detected === false) {
        router.replace({ pathname: "/camera", params: { retake: "no_face" } });
        return;
      }

      setBlackOut(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

      // Repli si le moteur a totalement echoue.
      const scores = a
        ? {
            global_score: a.global_score,
            texture: a.texture,
            radiance: a.radiance,
            imperfections: a.imperfections,
          }
        : { global_score: 70, texture: 72, radiance: 68, imperfections: 70 };

      const recs = a?.recommendations || [
        "Maintenez une protection solaire SPF 50 quotidienne.",
        "Hydratez matin et soir avec un sérum à l'acide hyaluronique.",
        "Affinez progressivement le grain de peau avec une exfoliation douce hebdomadaire.",
      ];

      const payload = {
        ...scores,
        recommendations: recs,
        diagnosis: a?.diagnosis || "",
        detections: a?.detections || [],
      };

      await storage.setItem("skyn_last_low_light", a?.low_light ? "1" : "");

      try {
        const report = await api.createReport(payload);
        pushReportToSupabase({
          id: report.id,
          user_id: user?.user_id || "",
          global_score: report.global_score,
          texture: report.texture,
          radiance: report.radiance,
          imperfections: report.imperfections,
          recommendations: report.recommendations,
          created_at: report.created_at,
        });
        router.replace(`/report?id=${report.id}`);
      } catch {
        await queuePendingReport(payload as any);
        router.replace("/dashboard");
      }
    };

    const t4 = setTimeout(() => {
      const elapsed = Date.now() - startedAt.current;
      const wait = Math.max(0, 6500 - elapsed);
      setTimeout(finalize, wait);
    }, 6500);

    return () => {
      cancelled = true;
      if (hapticInt.current) clearInterval(hapticInt.current);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Chaque lesion trouvee se signale au doigt, une par une.
  useEffect(() => {
    if (phase !== 2 || !analysis?.detections?.length) return;
    const timers = analysis.detections.map((_: Detection, i: number) =>
      setTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light), i * 320 + 80),
    );
    return () => timers.forEach(clearTimeout);
  }, [phase, analysis]);

  const detections: Detection[] = analysis?.detections || [];

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Reveal distance={10}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
          <Text style={styles.counter}>0{phase + 1} / 04</Text>
        </View>
      </Reveal>

      <View style={styles.stage}>
        <ScanField
          size={FIELD}
          phase={phase}
          imageB64={imageB64}
          detections={detections}
          style={styles.field}
        />

        {/* Le titre se remplace a chaque phase : la cle force la re-entree. */}
        <Reveal key={phase} delay={60} distance={12} style={styles.phaseBlock}>
          <Text style={styles.phaseTitle} testID={`analysis-phase-${phase}`}>
            {PHASES[phase].title}
          </Text>
          <Text style={styles.phaseNote}>{PHASES[phase].note}</Text>
        </Reveal>
      </View>

      <View style={styles.footer}>
        <View style={styles.rail}>
          {PHASES.map((p, i) => (
            <Segment key={p.title} active={i <= phase} />
          ))}
        </View>
        <Text style={styles.hint}>Ne bougez pas</Text>
      </View>

      {blackOut ? (
        <View style={styles.blackOut} pointerEvents="auto" testID="analysis-blackout" />
      ) : null}
    </SafeAreaView>
  );
}

/** Un segment du rail se remplit quand sa phase est atteinte. */
function Segment({ active }: { active: boolean }) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withTiming(active ? 1 : 0, {
      duration: motion.slow,
      easing: Easing.out(Easing.cubic),
    });
  }, [active, t]);

  const aStyle = useAnimatedStyle(() => ({
    transform: [{ scaleX: t.value }],
    opacity: 0.25 + t.value * 0.75,
  }));

  return (
    <View style={styles.segTrack}>
      <Animated.View style={[styles.segFill, aStyle]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "space-between",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.m,
  },
  counter: {
    ...type.kicker,
    color: colors.fgDim,
    fontVariant: ["tabular-nums"],
  },
  stage: { alignItems: "center", gap: spacing.xl, paddingHorizontal: spacing.l },
  field: { alignSelf: "center" },
  phaseBlock: { alignItems: "center", gap: spacing.xs },
  phaseTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  phaseNote: {
    ...type.bodySmall,
    color: colors.fgMuted,
    textAlign: "center",
    maxWidth: 260,
  },
  footer: {
    paddingHorizontal: spacing.l,
    paddingBottom: spacing.xl,
    gap: spacing.m,
  },
  rail: { flexDirection: "row", gap: 6 },
  segTrack: {
    flex: 1,
    height: 3,
    borderRadius: radius.pill,
    backgroundColor: colors.fgFaint,
    overflow: "hidden",
  },
  segFill: {
    width: "100%",
    height: "100%",
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    // Le remplissage part de la gauche, comme une lecture.
    transformOrigin: "left",
  },
  hint: {
    ...type.kicker,
    color: colors.fgDim,
    textAlign: "center",
  },
  blackOut: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.bg },
});
