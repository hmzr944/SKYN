import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { api } from "@/src/services/api";
import { scheduleTreatmentCheckpoints } from "@/src/services/reminders";
import { colors, fonts, radius, spacing, type } from "@/src/theme";

/**
 * Commencer un traitement — le point d'entree qui manquait a la memoire de
 * peau : jusqu'ici, un produit introduit (`ProductEvent`) ne rouvrait jamais
 * de Phase, et un changement de routine structurant en ouvrait une, mais
 * anonyme. Aucun des deux ne repondait a la vraie question : "je commence
 * CE traitement precis, est-ce qu'il change reellement ma peau ?"
 *
 * Cet ecran nomme ce debut. SKYN cloture la Phase en cours et en ouvre une
 * nouvelle, ancree sur le dernier scan connu — le prochain scan devient le
 * premier point de comparaison de cette Phase-la, pas d'une routine en vrac.
 */
export default function StartTreatmentScreen() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = name.trim().length > 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const treatmentName = name.trim();
      await api.startTreatment(treatmentName, goal.trim());
      // N'attend jamais l'autorisation notifications pour continuer : un
      // refus, ou l'absence de support (web), ne doit jamais bloquer le
      // debut de la Phase elle-meme — voir scheduleTreatmentCheckpoints.
      scheduleTreatmentCheckpoints(treatmentName).catch(() => {});
      router.replace("/phase-history");
    } catch {
      setError(
        "Impossible de démarrer cette Phase pour l'instant. Vérifiez votre connexion et réessayez."
      );
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <AnimatedPressable
            testID="start-treatment-close-btn"
            onPress={() => router.back()}
            style={styles.closeBtn}
            scaleTo={0.9}
            haptic={false}
            accessibilityLabel="Fermer"
          >
            <Text style={styles.closeText}>✕</Text>
          </AnimatedPressable>
          <SkynLockup size={20} still />
          <View style={{ width: 36 }} />
        </View>

        <View style={styles.body}>
          <Reveal bouncy distance={10}>
            <Text style={styles.kicker}>NOUVELLE PHASE</Text>
            <Text style={styles.title}>Vous commencez{"\n"}un traitement ?</Text>
            <Text style={styles.helper}>
              SKYN ouvre une nouvelle Phase à partir de maintenant. Vos prochains
              scans se compareront à aujourd'hui, pas au reste de votre historique.
            </Text>
          </Reveal>

          <Reveal delay={80} distance={10} style={styles.field}>
            <Text style={styles.label}>Traitement ou produit</Text>
            <TextInput
              testID="start-treatment-name-input"
              value={name}
              onChangeText={setName}
              placeholder="ex. Traitement anti-imperfections"
              placeholderTextColor={colors.fgFaint}
              style={styles.input}
              autoFocus
              returnKeyType="next"
              maxLength={80}
            />
          </Reveal>

          <Reveal delay={120} distance={10} style={styles.field}>
            <Text style={styles.label}>Objectif — facultatif</Text>
            <TextInput
              testID="start-treatment-goal-input"
              value={goal}
              onChangeText={setGoal}
              placeholder="ex. réduire les boutons du menton"
              placeholderTextColor={colors.fgFaint}
              style={styles.input}
              returnKeyType="done"
              maxLength={120}
              onSubmitEditing={submit}
            />
          </Reveal>

          {error ? (
            <Reveal distance={6} style={styles.errorBadge}>
              <Text style={styles.error} testID="start-treatment-error">
                {error}
              </Text>
            </Reveal>
          ) : null}
        </View>

        <View style={styles.footer}>
          <AnimatedPressable
            testID="start-treatment-submit-btn"
            style={[styles.submitBtn, !canSubmit && styles.submitBtnOff]}
            onPress={submit}
            disabled={!canSubmit}
            haptic="medium"
            squash
          >
            {busy ? (
              <ActivityIndicator color={colors.onAccent} size="small" />
            ) : (
              <Text style={styles.submitText}>Commencer cette Phase</Text>
            )}
          </AnimatedPressable>
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.m,
  },
  closeBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSunken,
  },
  closeText: { fontFamily: fonts.body, fontSize: 15, color: colors.fg },
  body: { flex: 1, paddingHorizontal: spacing.l, paddingTop: spacing.xl, gap: spacing.l },
  kicker: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    letterSpacing: 3,
    color: colors.accent,
    marginBottom: spacing.m,
  },
  title: {
    fontFamily: fonts.display,
    fontSize: 32,
    lineHeight: 36,
    color: colors.fg,
    letterSpacing: -0.6,
  },
  helper: {
    ...type.body,
    color: colors.fgMuted,
    marginTop: spacing.m,
    maxWidth: 340,
  },
  field: { gap: spacing.xs },
  label: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    letterSpacing: 0.4,
    color: colors.fgDim,
  },
  input: {
    fontFamily: fonts.body,
    fontSize: 16,
    color: colors.fg,
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.md,
    paddingHorizontal: spacing.m,
    paddingVertical: spacing.m,
    backgroundColor: colors.surface,
  },
  errorBadge: {
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.sm,
    paddingVertical: spacing.s,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.surface,
  },
  error: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 0.3,
  },
  footer: { paddingHorizontal: spacing.l, paddingBottom: spacing.m },
  submitBtn: {
    backgroundColor: colors.accent,
    paddingVertical: 16,
    alignItems: "center",
    borderRadius: radius.pill,
  },
  submitBtnOff: { opacity: 0.42 },
  submitText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
