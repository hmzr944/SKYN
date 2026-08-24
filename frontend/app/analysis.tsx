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
import { BrandField } from "@/src/components/brand/BrandField";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { useAuth } from "@/src/contexts/AuthContext";
import { api } from "@/src/services/api";
import { saveRoutineFromAnalysis } from "@/src/services/routineStore";
import { track } from "@/src/services/analytics";
import { saveScan, subScores } from "@/src/services/scanStore";
import { pushReportToSupabase } from "@/src/services/supabase";
import { colors, motion, radius, spacing, type } from "@/src/theme";
import type { FaceAnalysis } from "@/src/types/analysis";
import { storage } from "@/src/utils/storage";

const { width: SCREEN_W } = Dimensions.get("window");
const FIELD = Math.min(SCREEN_W * 0.72, 300);

/**
 * Un echec technique ne se montre pas tel quel.
 *
 * Le client d'API leve `502: <!DOCTYPE html>...` quand le serveur renvoie une
 * page d'erreur : afficher ca a quelqu'un qui vient de se photographier le
 * visage n'a aucun sens. Seul le message du moteur — qui est ecrit pour etre
 * lu — remonte intact.
 */
function humanError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? "");
  if (/^\d{3}:/.test(raw) || /<!DOCTYPE|<html/i.test(raw) || /Network request failed/i.test(raw)) {
    return "Le serveur d'analyse n'a pas répondu. Vérifiez votre connexion et réessayez.";
  }
  return raw.trim() || "L'analyse n'a pas abouti.";
}

const PHASES = [
  { title: "Scan de surface", note: "Lecture du grain et de la brillance" },
  { title: "Mapping des zones", note: "Découpage du visage en 13 régions" },
  { title: "Micro-patterns", note: "Repérage des lésions et de leur densité" },
  { title: "Génération du rapport", note: "Croisement avec la base dermatologique" },
];

export default function AnalysisScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [phase, setPhase] = useState(0);
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<FaceAnalysis | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [blackOut, setBlackOut] = useState(false);
  const hapticInt = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef<number>(Date.now());
  const analysisRef = useRef<FaceAnalysis | null>(null);
  /** Nombre d'angles reellement envoyes au moteur, pour l'instrumentation. */
  const anglesRef = useRef(1);
  const failureRef = useRef<string | null>(null);

  useEffect(() => {
    analysisRef.current = analysis;
  }, [analysis]);
  useEffect(() => {
    failureRef.current = failure;
  }, [failure]);

  // La requete part des le montage — elle tourne en parallele de la sequence
  // visuelle. A la derniere phase, les vraies donnees sont quasi toujours la.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const b = (await storage.getItem("skyn_last_capture_b64", "")) as string;
      if (cancelled) return;
      if (!b) {
        router.replace("/camera");
        return;
      }
      setImageB64(b);

      // Le scan guide produit trois angles : la vue de face aplatit les joues
      // et les tempes, les profils les exposent. On transmet les angles
      // supplementaires quand ils existent, sans jamais bloquer si le scan
      // s'est arrete apres une seule prise.
      let extras: string[] = [];
      try {
        const raw = (await storage.getItem("skyn_last_captures", "[]")) as string;
        const all = JSON.parse(raw || "[]") as string[];
        extras = all.filter((x) => x && x !== b).slice(0, 2);
      } catch {
        extras = [];
      }

      anglesRef.current = 1 + extras.length;
      try {
        const data = await api.analyzeV2(b, extras);
        if (cancelled) return;
        if (!data.ok) setFailure(data.summary || "Visage non détecté.");
        else setAnalysis(data);
      } catch (e) {
        if (!cancelled) setFailure(humanError(e));
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

      // Aucun visage exploitable : on ne fabrique pas un diagnostic, on renvoie
      // reprendre la photo. Une analyse inventee serait pire que pas d'analyse.
      if (!a) {
        setFailure((f) => f ?? "L'analyse n'a rien pu lire sur cette photo.");
        return;
      }

      setBlackOut(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

      // La source unique : l'analyse complete, rouvrable plus tard.
      const id = await saveScan(a);
      await track("scan_completed", { score: a.global_score, angles: anglesRef.current });
      await saveRoutineFromAnalysis(a);
      await storage.setItem("skyn_last_capture_b64", "");
      await storage.setItem("skyn_last_captures", "[]");

      // Miroir serveur au mieux : il alimente la sauvegarde cloud, mais l'app
      // ne depend plus de lui pour afficher quoi que ce soit.
      const sub = subScores(a);
      api
        .createReport({
          global_score: a.global_score,
          ...sub,
          recommendations: a.routine.am.map((p) => `${p.brand} ${p.name}`),
          diagnosis: a.diagnosis,
        })
        .then((report) =>
          pushReportToSupabase({
            id: report.id,
            user_id: user?.user_id || "",
            global_score: report.global_score,
            texture: report.texture,
            radiance: report.radiance,
            imperfections: report.imperfections,
            recommendations: report.recommendations,
            created_at: report.created_at,
          }),
        )
        .catch(() => {
          /* hors ligne : le scan reste consultable en local */
        });

      router.replace(`/scan-result?id=${id}`);
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

  // Chaque lesion trouvee se signale au doigt, une par une — mais on plafonne :
  // sur une peau tres chargee, cinquante vibrations d'affilee sont penibles.
  useEffect(() => {
    if (phase !== 2 || !analysis?.lesions?.length) return;
    const timers = analysis.lesions
      .slice(0, 8)
      .map((_, i) =>
        setTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light), i * 320 + 80),
      );
    return () => timers.forEach(clearTimeout);
  }, [phase, analysis]);

  const detections = analysis?.lesions ?? [];

  // L'echec doit avoir son ecran : sans lui, une photo illisible laisse
  // l'utilisateur devant une animation qui tourne sans fin.
  if (failure) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
        </View>
        <Reveal style={styles.failWrap} distance={14}>
          <Text style={styles.failTitle}>Analyse impossible</Text>
          <Text style={styles.failNote}>{failure}</Text>
          <Text style={styles.failHint}>
            {"Placez votre visage dans l'ovale, en lumière du jour de préférence, " +
              "sans lunettes ni cheveux sur le front."}
          </Text>
          <AnimatedPressable
            style={styles.failCta}
            haptic="medium"
            onPress={() => router.replace("/camera")}
          >
            <Text style={styles.failCtaText}>Reprendre une photo</Text>
          </AnimatedPressable>
        </Reveal>
        <View />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Reveal distance={10}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
          <Text style={styles.counter}>0{phase + 1} / 04</Text>
        </View>
      </Reveal>

      <View style={styles.stage}>
        <BrandField size={FIELD * 1.9} drift style={styles.brandField} />
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
  brandField: { position: "absolute", top: -60 },
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
  failWrap: { paddingHorizontal: spacing.l, alignItems: "center", gap: spacing.m },
  failTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  failNote: { ...type.body, color: colors.fgMuted, textAlign: "center" },
  failHint: {
    ...type.bodySmall,
    color: colors.fgDim,
    textAlign: "center",
    maxWidth: 280,
  },
  failCta: {
    marginTop: spacing.s,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 15,
    paddingHorizontal: spacing.xl,
  },
  failCtaText: { ...type.kicker, color: colors.onAccent },
  blackOut: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.bg },
});
