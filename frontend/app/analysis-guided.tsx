import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { api } from "@/src/services/api";
import { track } from "@/src/services/analytics";
import { colors, radius, spacing, type } from "@/src/theme";
import { storage } from "@/src/utils/storage";

/**
 * Etape de traitement du scan guide (EXPERIMENTAL) — ecran distinct de
 * scan-result.tsx, qui reste le seul ecran de resultat du scan 3 angles.
 *
 * Depuis le chantier 5 (memoire persistante), un succes ne s'affiche plus
 * ici : le scan est ingere dans la Phase active via POST /api/scans, puis
 * l'ecran redirige vers /what-changed, qui lit la Phase a jour plutot
 * qu'un resultat brut passe en memoire. Cet ecran ne gere donc plus que le
 * chargement et l'echec — voir `guided_scan_completed` dans le journal
 * local pour le dataset d'usage complet.
 */

function humanError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? "");
  if (/^\d{3}:/.test(raw) || /<!DOCTYPE|<html/i.test(raw) || /Network request failed/i.test(raw)) {
    return "Le serveur d'analyse n'a pas répondu. Vérifiez votre connexion et réessayez.";
  }
  return raw.trim() || "L'analyse n'a pas abouti.";
}

const moyenne = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

export default function AnalysisGuidedScreen() {
  const router = useRouter();
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

        // Chantier 5 : rattache ce scan a la Phase active (ou en cree une
        // baseline) avant de montrer quoi que ce soit — What Changed? lit
        // la Phase a jour, pas cette reponse brute.
        await api.ingestScan("guided", data as unknown as Record<string, unknown>);
        if (!cancelled) router.replace("/what-changed");
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <SkynLockup size={26} still />
      </View>
      <View style={styles.loadingWrap}>
        <ActivityIndicator color={colors.accent} />
        <Text style={styles.loadingText}>Mise à jour de votre carte…</Text>
      </View>
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
