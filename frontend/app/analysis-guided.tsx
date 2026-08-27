import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { api } from "@/src/services/api";
import { track } from "@/src/services/analytics";
import { colors, radius, spacing, type } from "@/src/theme";
import type { GuidedScanResponse } from "@/src/types/guidedScan";
import { storage } from "@/src/utils/storage";

/**
 * Resultat du scan guide (v0, EXPERIMENTAL) — ecran distinct de
 * scan-result.tsx, qui reste le seul ecran de resultat du scan 3 angles.
 *
 * Volontairement minimal : pas de score global (ce pipeline n'en calcule
 * pas — voir skyn_engine.v2.multiview, aucun `analyze_face`/`concerns.py`
 * n'entre dans ce chemin), pas de routine, pas de sauvegarde d'historique.
 * L'objectif de cette version n'est pas de remplacer scan-result.tsx, c'est
 * de verifier que le protocole de capture guide produit un resultat
 * exploitable — voir `guided_scan_completed` dans le journal local pour le
 * dataset d'usage complet.
 */

function humanError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? "");
  if (/^\d{3}:/.test(raw) || /<!DOCTYPE|<html/i.test(raw) || /Network request failed/i.test(raw)) {
    return "Le serveur d'analyse n'a pas répondu. Vérifiez votre connexion et réessayez.";
  }
  return raw.trim() || "L'analyse n'a pas abouti.";
}

const STATUS_LABEL: Record<string, string> = {
  TARGET_REACHED: "Mesure stable atteinte",
  MAX_REACHED: "Nombre de vues maximum atteint",
  NEED_MORE_VIEWS: "Trop peu de vues exploitables",
};

const moyenne = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

export default function AnalysisGuidedScreen() {
  const router = useRouter();
  const [result, setResult] = useState<GuidedScanResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const framesProposedRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const raw = (await storage.getItem("skyn_guided_captures", "[]")) as string;
      const images = JSON.parse(raw || "[]") as string[];
      const captureMs = Number((await storage.getItem("skyn_guided_capture_ms", "0")) as string) || 0;
      framesProposedRef.current = images.length;

      if (cancelled) return;
      if (!images.length) {
        setFailure("Aucune vue capturée. Reprenez le scan guidé.");
        return;
      }

      const t0 = Date.now();
      try {
        const data = await api.analyzeGuided(images);
        const backendMs = Date.now() - t0;
        if (cancelled) return;

        if (!data.usable_views || !data.lesions) {
          const msg = "Aucune vue exploitable sur cette série. Reprenez le scan, avec un visage bien cadré et une lumière suffisante.";
          setFailure(msg);
          await track("guided_scan_failed", {
            reason: data.stop_reason || "no_usable_views",
            frames_proposed: images.length,
            frames_sent: images.length,
            backend_ms: backendMs,
          });
          return;
        }

        setResult(data);

        const yaws = data.view_diagnostics.map((v) => v.yaw_proxy);
        await track("guided_scan_completed", {
          frames_proposed: framesProposedRef.current,
          frames_sent: images.length,
          usable_views: data.usable_views,
          status: data.status,
          stop_reason: data.stop_reason,
          lesions_confirmed: data.lesions.length,
          capture_ms: captureMs,
          backend_ms: backendMs,
          total_ms: captureMs + backendMs,
          yaw_min: yaws.length ? Math.min(...yaws) : 0,
          yaw_max: yaws.length ? Math.max(...yaws) : 0,
          yaw_avg: moyenne(yaws),
        });
      } catch (e) {
        if (cancelled) return;
        setFailure(humanError(e));
        await track("guided_scan_failed", {
          reason: "request_error",
          frames_proposed: images.length,
          frames_sent: images.length,
        });
      } finally {
        if (!cancelled) {
          await storage.setItem("skyn_guided_captures", "[]");
          await storage.setItem("skyn_guided_capture_ms", "0");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (failure) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
        </View>
        <Reveal style={styles.failWrap} distance={14}>
          <Text style={styles.failTitle}>Scan guidé impossible</Text>
          <Text style={styles.failNote}>{failure}</Text>
          <AnimatedPressable
            style={styles.failCta}
            haptic="medium"
            onPress={() => router.replace("/camera-guided")}
          >
            <Text style={styles.failCtaText}>Reprendre le scan guidé</Text>
          </AnimatedPressable>
          <AnimatedPressable style={styles.linkBtn} haptic={false} onPress={() => router.replace("/(tabs)/dashboard")}>
            <Text style={styles.linkText}>{"Retour à l'accueil"}</Text>
          </AnimatedPressable>
        </Reveal>
      </SafeAreaView>
    );
  }

  if (!result) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <SkynLockup size={26} still />
        </View>
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.loadingText}>Analyse multi-vue en cours…</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={26} still />
        <Text style={styles.betaTag}>bêta</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Reveal distance={10}>
          <Text style={styles.title}>Scan guidé — résultat</Text>
          <Text style={styles.statusLine}>
            {STATUS_LABEL[result.status] || result.status} · {result.usable_views} vues
            exploitables sur {result.frames_received} proposées
          </Text>
        </Reveal>

        <Reveal distance={10} delay={60} style={styles.card}>
          <Text style={styles.cardTitle}>
            {result.lesions.length} observation{result.lesions.length > 1 ? "s" : ""} confirmée
            {result.lesions.length > 1 ? "s" : ""}
          </Text>
          {result.lesions.length === 0 ? (
            <Text style={styles.cardNote}>
              Aucune observation confirmée avec suffisamment de constance sur cette série.
            </Text>
          ) : (
            result.lesions.map((l, i) => (
              <View key={i} style={styles.lesionRow}>
                <Text style={styles.lesionType}>{l.type}</Text>
                <Text style={styles.lesionMeta}>
                  {l.n_observations} obs. · pos. ({l.x.toFixed(2)}, {l.y.toFixed(2)})
                </Text>
              </View>
            ))
          )}
        </Reveal>

        <Text style={styles.disclaimer}>
          {"Version expérimentale : pas de score global ni de routine associée pour l'instant — " +
            "cet écran vérifie la qualité du protocole de capture, pas encore le suivi complet."}
        </Text>

        <AnimatedPressable
          style={styles.failCta}
          haptic="medium"
          onPress={() => router.replace("/(tabs)/dashboard")}
        >
          <Text style={styles.failCtaText}>{"Retour à l'accueil"}</Text>
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
  scroll: { padding: spacing.l, gap: spacing.l, paddingBottom: spacing.xxl },
  title: { ...type.title, color: colors.fg },
  statusLine: { ...type.bodySmall, color: colors.fgMuted, marginTop: spacing.xs },

  card: {
    borderWidth: 1,
    borderColor: colors.accentLine,
    borderRadius: radius.md,
    padding: spacing.l,
    gap: spacing.s,
  },
  cardTitle: { ...type.subtitle, color: colors.fg },
  cardNote: { ...type.bodySmall, color: colors.fgMuted },
  lesionRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: spacing.xs,
    borderTopWidth: 1,
    borderTopColor: colors.fgFaint,
  },
  lesionType: { ...type.body, color: colors.fg, textTransform: "capitalize" },
  lesionMeta: { ...type.bodySmall, color: colors.fgDim, fontVariant: ["tabular-nums"] },

  disclaimer: { ...type.bodySmall, color: colors.fgDim },

  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.m },
  loadingText: { ...type.body, color: colors.fgMuted },

  failWrap: { flex: 1, paddingHorizontal: spacing.l, alignItems: "center", justifyContent: "center", gap: spacing.m },
  failTitle: { ...type.title, color: colors.fg, textAlign: "center" },
  failNote: { ...type.body, color: colors.fgMuted, textAlign: "center" },
  failCta: {
    marginTop: spacing.s,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 15,
    paddingHorizontal: spacing.xl,
    alignSelf: "center",
  },
  failCtaText: { ...type.kicker, color: colors.onAccent },
  linkBtn: { paddingVertical: spacing.s },
  linkText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
});
