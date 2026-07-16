import { useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  NativeSyntheticEvent,
  NativeScrollEvent,
  ActivityIndicator,
  Platform,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import Svg, { Path } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { HowItWorksModal } from "@/src/components/HowItWorksModal";

// Questionnaire = un "cahier" : identité propre (numérotation en grand,
// barre de progression pleine largeur, cases à cocher carrées) qui le
// distingue nettement du récit illustré de l'onboarding.
const QUESTIONS_META = [
  { n: "01", label: "ÂGE" },
  { n: "02", label: "ENVIRONNEMENT" },
  { n: "03", label: "TYPE DE PEAU" },
  { n: "04", label: "PRIORITÉ" },
];

const AGE_OPTIONS = ["Moins de 25", "25 – 40", "40 – 60", "60 +"];
const AGE_VALUES = ["<25", "25-40", "40-60", "60+"];
const ENV_OPTIONS = [
  { label: "Urbain / Pollué", value: "Urbain" },
  { label: "Sec / Climatisé", value: "Sec" },
  { label: "Humide", value: "Humide" },
  { label: "Variable", value: "Variable" },
];
const PRIORITY_OPTIONS = ["Éclat", "Ridules", "Imperfections", "Sensibilité"];
const SKIN_OPTIONS = [
  { label: "Normale", value: "Normale" },
  { label: "Mixte (zone T brillante)", value: "Mixte" },
  { label: "Grasse", value: "Grasse" },
  { label: "Sèche", value: "Sèche" },
  { label: "Je ne sais pas — détectez-le", value: "auto" },
];

export default function ProfileSetupScreen() {
  const { width: SCREEN_W, height: SCREEN_H } = useWindowDimensions();
  const isShort = SCREEN_H < 700;
  const router = useRouter();
  const { refreshProfile } = useAuth();
  const scrollRef = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const [ageRange, setAgeRange] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [skinType, setSkinType] = useState<string | null>(null);
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
    if (page === 2) return skinType !== null;
    if (page === 3) return priority !== null;
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
        // "auto" = l'utilisateur laisse la photo décider (ViT + sébum zones)
        skin_type: skinType && skinType !== "auto" ? skinType : null,
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
    <View style={[styles.optionList, isShort && { marginTop: spacing.l }]}>
      {options.map((opt, i) => {
        const selected = current === opt.value;
        return (
          <FadeIn key={opt.value} delay={120 + i * 60} distance={10}>
            <AnimatedPressable
              testID={`${testPrefix}-${opt.value}`}
              style={[
                styles.option,
                isShort && { paddingVertical: spacing.s },
                selected && styles.optionSelected,
              ]}
              scaleTo={0.98}
              onPress={() => {
                setter(opt.value);
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              }}
            >
              <View style={[styles.checkbox, selected && styles.checkboxSelected]}>
                {selected ? (
                  <Svg width={12} height={10} viewBox="0 0 12 10">
                    <Path
                      d="M1 5 L4.3 8.3 L11 1"
                      stroke={colors.onAccent}
                      strokeWidth={1.8}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                    />
                  </Svg>
                ) : null}
              </View>
              <Text
                style={[
                  styles.optionText,
                  selected && styles.optionTextSelected,
                ]}
              >
                {opt.label}
              </Text>
            </AnimatedPressable>
          </FadeIn>
        );
      })}
    </View>
  );

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Header — barre de progression pleine largeur, motif "cahier" */}
      <View style={styles.header}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${((page + 1) / 4) * 100}%` }]} />
        </View>
        <View style={styles.headerRow}>
          <Text style={styles.qCounter}>
            {QUESTIONS_META[page].n}<Text style={styles.qCounterMax}> / 04</Text>
          </Text>
          {page < 3 ? (
            <TouchableOpacity
              testID="profile-skip-btn"
              onPress={() => goToPage(3)}
              hitSlop={8}
            >
              <Text style={styles.skip}>Passer</Text>
            </TouchableOpacity>
          ) : (
            <View style={{ height: 18 }} />
          )}
        </View>
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
        style={{ flex: 1 }}
      >
        {/* Q1 — Age range */}
        <ScrollView
          style={{ width: SCREEN_W }}
          contentContainerStyle={styles.page}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <FadeIn distance={10}>
            <Text style={styles.qLabel}>{QUESTIONS_META[0].label}</Text>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={[styles.question, isShort && styles.questionShort]}>{"Votre\ntranche d'âge"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={[styles.helper, isShort && { marginTop: spacing.s, fontSize: 14 }]}>
              {"Pour calibrer l'algorithme selon votre cycle cutané."}
            </Text>
          </FadeIn>
          {renderOptions(
            AGE_OPTIONS.map((l, i) => ({ label: l, value: AGE_VALUES[i] })),
            ageRange,
            setAgeRange,
            "age",
          )}
        </ScrollView>

        {/* Q2 — Environment */}
        <ScrollView
          style={{ width: SCREEN_W }}
          contentContainerStyle={styles.page}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <FadeIn distance={10}>
            <Text style={styles.qLabel}>{QUESTIONS_META[1].label}</Text>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={[styles.question, isShort && styles.questionShort]}>{"Votre\nenvironnement\nquotidien"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={[styles.helper, isShort && { marginTop: spacing.s, fontSize: 14 }]}>
              {"L'environnement influence directement l'état de votre peau."}
            </Text>
          </FadeIn>
          {renderOptions(ENV_OPTIONS, environment, setEnvironment, "env")}
        </ScrollView>

        {/* Q3 — Skin type */}
        <ScrollView
          style={{ width: SCREEN_W }}
          contentContainerStyle={styles.page}
          showsVerticalScrollIndicator={false}
        >
          <FadeIn distance={10}>
            <Text style={styles.qLabel}>{QUESTIONS_META[2].label}</Text>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={[styles.question, isShort && styles.questionShort]}>{"Votre type\nde peau"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={[styles.helper, isShort && { marginTop: spacing.s, fontSize: 14 }]}>
              {"Le critère n°1 pour vos produits. En cas de doute, notre analyse photo le détecte pour vous."}
            </Text>
          </FadeIn>
          {renderOptions(SKIN_OPTIONS, skinType, setSkinType, "skin")}
        </ScrollView>

        {/* Q4 — Priority */}
        <ScrollView
          style={{ width: SCREEN_W }}
          contentContainerStyle={styles.page}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <FadeIn distance={10}>
            <Text style={styles.qLabel}>{QUESTIONS_META[3].label}</Text>
          </FadeIn>
          <FadeIn delay={60} distance={16}>
            <Text style={[styles.question, isShort && styles.questionShort]}>{"Votre priorité\nmajeure"}</Text>
          </FadeIn>
          <FadeIn delay={120}>
            <Text style={[styles.helper, isShort && { marginTop: spacing.s, fontSize: 14 }]}>
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
        </ScrollView>
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

        <View />

        <AnimatedPressable
          testID="profile-next-btn"
          disabled={!canNext() || saving}
          onPress={() => {
            if (page < 3) goToPage(page + 1);
            else finish();
          }}
          style={[styles.nextBtn, (!canNext() || saving) && styles.nextBtnDisabled]}
        >
          {saving ? (
            <ActivityIndicator color={colors.onAccent} size="small" />
          ) : (
            <Text style={styles.nextText}>
              {page < 3 ? "Suivant" : "Terminer"}
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
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.s,
  },
  progressTrack: {
    height: 3,
    borderRadius: 1.5,
    backgroundColor: colors.borderSubtle,
    overflow: "hidden",
    marginBottom: spacing.m,
  },
  progressFill: {
    height: 3,
    borderRadius: 1.5,
    backgroundColor: colors.accent,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    minHeight: 24,
  },
  qCounter: {
    fontFamily: fonts.heading,
    fontSize: 15,
    color: colors.fg,
    letterSpacing: -0.3,
  },
  qCounterMax: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fgDim,
  },
  skip: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgDim,
  },
  page: {
    minHeight: "100%",
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.l,
    paddingTop: spacing.xl,
    alignItems: "flex-start",
  },
  qLabel: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    letterSpacing: 2.5,
    color: colors.accent,
    marginBottom: spacing.s,
  },
  question: {
    fontFamily: fonts.heading,
    color: colors.fg,
    textAlign: "left",
    fontSize: 36,
    lineHeight: 42,
    letterSpacing: -0.5,
  },
  questionShort: {
    fontSize: 27,
    lineHeight: 32,
  },
  helper: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 15,
    marginTop: spacing.m,
    lineHeight: 22,
    textAlign: "left",
  },
  optionList: { marginTop: spacing.xl, gap: spacing.s, width: "100%" },
  option: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderLeftWidth: 3,
    borderLeftColor: "transparent",
    ...shadow.card,
  },
  optionSelected: {
    borderLeftColor: colors.accent,
    backgroundColor: colors.accentSofter,
  },
  optionText: {
    flex: 1,
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 16,
    letterSpacing: 0.2,
  },
  optionTextSelected: {
    color: colors.fg,
    fontFamily: fonts.bodyMedium,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: colors.borderMid,
    alignItems: "center",
    justifyContent: "center",
  },
  checkboxSelected: {
    borderColor: colors.accent,
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
