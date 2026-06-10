import { useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Dimensions,
  ScrollView,
  NativeSyntheticEvent,
  NativeScrollEvent,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { HowItWorksModal } from "@/src/components/HowItWorksModal";
import {
  PromiseIllustration,
  TechIllustration,
  PrivacyIllustration,
} from "@/src/components/illustrations/OnboardingIllustrations";

const { width: SCREEN_W } = Dimensions.get("window");

const AGE_OPTIONS = ["Moins de 25", "25 – 40", "40 – 60", "60 +"];
const AGE_VALUES = ["<25", "25-40", "40-60", "60+"];
const ENV_OPTIONS = [
  { label: "Urbain / Pollué", value: "Urbain" },
  { label: "Sec / Climatisé", value: "Sec" },
  { label: "Humide", value: "Humide" },
  { label: "Variable", value: "Variable" },
];
const PRIORITY_OPTIONS = ["Éclat", "Ridules", "Imperfections", "Sensibilité"];

export default function ProfileSetupScreen() {
  const router = useRouter();
  const { refreshProfile } = useAuth();
  const scrollRef = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const [ageRange, setAgeRange] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [priority, setPriority] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [howItWorksVisible, setHowItWorksVisible] = useState(false);

  const goToPage = (p: number) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    scrollRef.current?.scrollTo({ x: p * SCREEN_W, animated: true });
    setPage(p);
  };

  const onMomentumEnd = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const p = Math.round(e.nativeEvent.contentOffset.x / SCREEN_W);
    if (p !== page) {
      setPage(p);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }
  };

  const canNext = () => {
    if (page === 0) return ageRange !== null;
    if (page === 1) return environment !== null;
    if (page === 2) return priority !== null;
    return false;
  };

  const finish = async () => {
    setSaving(true);
    setError(null);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try {
      await api.updateProfile({
        age_range: ageRange,
        environment,
        priority,
        onboarded: true,
      });
      await refreshProfile();
      router.replace("/dashboard");
    } catch (e: any) {
      console.error("profile-setup finish failed:", e);
      setSaving(false);
      setError(
        e?.message?.includes("401") || e?.message?.includes("403")
          ? "Session expirée — reconnectez-vous."
          : "Connexion impossible. Vérifiez votre réseau et réessayez.",
      );
    }
  };

  const renderOptions = (
    options: { label: string; value: string }[],
    current: string | null,
    setter: (v: string) => void,
    testPrefix: string,
  ) => (
    <View style={styles.optionList}>
      {options.map((opt, i) => {
        const selected = current === opt.value;
        return (
          <FadeIn key={opt.value} delay={120 + i * 60} distance={10}>
            <AnimatedPressable
              testID={`${testPrefix}-${opt.value}`}
              style={[styles.option, selected && styles.optionSelected]}
              scaleTo={0.98}
              onPress={() => {
                setter(opt.value);
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              }}
            >
              <Text
                style={[
                  styles.optionText,
                  selected && styles.optionTextSelected,
                ]}
              >
                {opt.label}
              </Text>
              <View style={[styles.radio, selected && styles.radioSelected]}>
                {selected && <View style={styles.radioDot} />}
              </View>
            </AnimatedPressable>
          </FadeIn>
        );
      })}
    </View>
  );

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={{ flex: 1 }} />
        {page < 2 ? (
          <TouchableOpacity
            testID="profile-skip-btn"
            onPress={() => goToPage(2)}
            hitSlop={8}
          >
            <Text style={styles.skip}>Passer</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ height: 18 }} />
        )}
      </View>

      {/* Pages */}
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onMomentumEnd}
        keyboardShouldPersistTaps="handled"
        scrollEnabled={false}
      >
        {/* Q1 — Age range */}
        <View style={styles.page}>
          <FadeIn distance={16}>
            <View style={styles.illustration}>
              <PromiseIllustration />
            </View>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={styles.question}>{"Votre\ntranche d'âge"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={styles.helper}>
              {"Pour calibrer l'algorithme selon votre cycle cutané."}
            </Text>
          </FadeIn>
          {renderOptions(
            AGE_OPTIONS.map((l, i) => ({ label: l, value: AGE_VALUES[i] })),
            ageRange,
            setAgeRange,
            "age",
          )}
        </View>

        {/* Q2 — Environment */}
        <View style={styles.page}>
          <FadeIn distance={16}>
            <View style={styles.illustration}>
              <TechIllustration />
            </View>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={styles.question}>{"Votre\nenvironnement\nquotidien"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={styles.helper}>
              {"L'environnement influence directement l'état de votre peau."}
            </Text>
          </FadeIn>
          {renderOptions(ENV_OPTIONS, environment, setEnvironment, "env")}
        </View>

        {/* Q3 — Priority */}
        <View style={styles.page}>
          <FadeIn distance={16}>
            <View style={styles.illustration}>
              <PrivacyIllustration />
            </View>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={styles.question}>{"Votre priorité\nmajeure"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={styles.helper}>
              {"Nous personnaliserons vos recommandations en conséquence."}
            </Text>
          </FadeIn>
          {renderOptions(
            PRIORITY_OPTIONS.map((l) => ({ label: l, value: l })),
            priority,
            setPriority,
            "priority",
          )}
          <TouchableOpacity
            testID="profile-how-it-works-link"
            onPress={() => setHowItWorksVisible(true)}
            style={styles.howLink}
            hitSlop={8}
          >
            <Text style={styles.howLinkText}>Comment ça marche ?</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {error ? (
        <FadeIn distance={6}>
          <Text style={styles.errorText} testID="profile-setup-error">
            {error}
          </Text>
        </FadeIn>
      ) : null}

      {/* Footer */}
      <View style={styles.footer}>
        {page > 0 ? (
          <TouchableOpacity
            testID="profile-back-btn"
            onPress={() => goToPage(page - 1)}
            style={styles.backBtn}
            activeOpacity={0.6}
          >
            <Text style={styles.backText}>← Retour</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ width: 80 }} />
        )}

        <View style={styles.dotsRow}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={[styles.dot, page === i && styles.dotActive]} />
          ))}
        </View>

        <AnimatedPressable
          testID="profile-next-btn"
          disabled={!canNext() || saving}
          onPress={() => {
            if (page < 2) goToPage(page + 1);
            else finish();
          }}
          style={[styles.nextBtn, (!canNext() || saving) && styles.nextBtnDisabled]}
        >
          {saving ? (
            <ActivityIndicator color={colors.onAccent} size="small" />
          ) : (
            <Text style={styles.nextText}>
              {page < 2 ? "Suivant" : "Terminer"}
            </Text>
          )}
        </AnimatedPressable>
      </View>

      <HowItWorksModal
        visible={howItWorksVisible}
        onClose={() => setHowItWorksVisible(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.xs,
    minHeight: 36,
  },
  skip: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgDim,
  },
  page: {
    width: SCREEN_W,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
  },
  illustration: {
    width: 160,
    height: 160,
    marginBottom: spacing.m,
    alignItems: "center",
    justifyContent: "center",
  },
  question: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 36,
    lineHeight: 42,
    letterSpacing: -0.5,
    textAlign: "center",
  },
  helper: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 15,
    marginTop: spacing.m,
    lineHeight: 22,
    textAlign: "center",
  },
  optionList: { marginTop: spacing.xl, gap: spacing.s, width: "100%" },
  option: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    ...shadow.card,
  },
  optionSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSofter,
  },
  optionText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 16,
    letterSpacing: 0.2,
  },
  optionTextSelected: {
    color: colors.fg,
    fontFamily: fonts.bodyMedium,
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: colors.borderSubtle,
    alignItems: "center",
    justifyContent: "center",
  },
  radioSelected: {
    borderColor: colors.accent,
  },
  radioDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.accent,
  },
  howLink: { marginTop: spacing.l },
  howLinkText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fgDim,
    textDecorationLine: "underline",
  },
  errorText: {
    fontFamily: fonts.body,
    color: colors.accent,
    fontSize: 12,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
    marginBottom: spacing.s,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingBottom: Platform.OS === "ios" ? spacing.l : spacing.xl,
    paddingTop: spacing.m,
    gap: spacing.s,
  },
  backBtn: { paddingVertical: 12, paddingRight: spacing.m },
  backText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    letterSpacing: 0.5,
  },
  dotsRow: { flexDirection: "row", gap: 6 },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.borderMid,
  },
  dotActive: { backgroundColor: colors.accent, width: 20 },
  nextBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: 32,
    paddingVertical: 16,
    borderRadius: radius.pill,
    minWidth: 120,
    alignItems: "center",
    ...shadow.button,
  },
  nextBtnDisabled: { opacity: 0.35, shadowOpacity: 0 },
  nextText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
});
