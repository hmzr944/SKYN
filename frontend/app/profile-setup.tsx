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

import { colors, fonts, spacing, radius } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";

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
    } catch {
      setSaving(false);
    }
  };

  const renderOptions = (
    options: { label: string; value: string }[],
    current: string | null,
    setter: (v: string) => void,
    testPrefix: string,
  ) => (
    <View style={styles.optionList}>
      {options.map((opt) => {
        const selected = current === opt.value;
        return (
          <TouchableOpacity
            key={opt.value}
            testID={`${testPrefix}-${opt.value}`}
            style={[styles.option, selected && styles.optionSelected]}
            activeOpacity={0.7}
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
          </TouchableOpacity>
        );
      })}
    </View>
  );

  const STEP_LABELS = ["Tranche d'âge", "Environnement", "Priorité"];

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.stepCounter}>
            0{page + 1}
            <Text style={styles.stepTotal}> / 03</Text>
          </Text>
          <Text style={styles.stepLabel}>{STEP_LABELS[page]}</Text>
        </View>
        <View style={styles.dotsRow}>
          {[0, 1, 2].map((i) => (
            <View
              key={i}
              style={[styles.dot, page === i && styles.dotActive]}
            />
          ))}
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
      >
        {/* Q1 — Age range */}
        <View style={styles.page}>
          <Text style={styles.question}>{"Votre\ntranche d'âge"}</Text>
          <Text style={styles.helper}>
            {"Pour calibrer l'algorithme selon votre cycle cutané."}
          </Text>
          {renderOptions(
            AGE_OPTIONS.map((l, i) => ({ label: l, value: AGE_VALUES[i] })),
            ageRange,
            setAgeRange,
            "age",
          )}
        </View>

        {/* Q2 — Environment */}
        <View style={styles.page}>
          <Text style={styles.question}>{"Votre\nenvironnement\nquotidien"}</Text>
          <Text style={styles.helper}>
            {"L'environnement influence directement l'état de votre peau."}
          </Text>
          {renderOptions(ENV_OPTIONS, environment, setEnvironment, "env")}
        </View>

        {/* Q3 — Priority */}
        <View style={styles.page}>
          <Text style={styles.question}>{"Votre priorité\nmajeure"}</Text>
          <Text style={styles.helper}>
            {"Nous personnaliserons vos recommandations en conséquence."}
          </Text>
          {renderOptions(
            PRIORITY_OPTIONS.map((l) => ({ label: l, value: l })),
            priority,
            setPriority,
            "priority",
          )}
        </View>
      </ScrollView>

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

        <TouchableOpacity
          testID="profile-next-btn"
          disabled={!canNext() || saving}
          onPress={() => {
            if (page < 2) goToPage(page + 1);
            else finish();
          }}
          style={[styles.nextBtn, (!canNext() || saving) && styles.nextBtnDisabled]}
          activeOpacity={0.75}
        >
          {saving ? (
            <ActivityIndicator color={colors.bg} size="small" />
          ) : (
            <Text style={styles.nextText}>
              {page < 2 ? "Suivant →" : "Terminer"}
            </Text>
          )}
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.l,
    paddingBottom: spacing.m,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  stepCounter: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 22,
    letterSpacing: -0.5,
  },
  stepTotal: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
  },
  stepLabel: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    marginTop: 4,
  },
  dotsRow: { flexDirection: "row", gap: 6, paddingTop: 6 },
  dot: {
    width: 28,
    height: 2,
    backgroundColor: colors.borderSubtle,
    borderRadius: 1,
  },
  dotActive: { backgroundColor: colors.fg },
  page: {
    width: SCREEN_W,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
  },
  question: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 36,
    lineHeight: 44,
    letterSpacing: -0.5,
  },
  helper: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13,
    marginTop: spacing.m,
    lineHeight: 20,
    letterSpacing: 0.2,
  },
  optionList: { marginTop: spacing.xl, gap: spacing.s },
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
  },
  optionSelected: {
    borderColor: colors.borderActive,
    backgroundColor: colors.fgFaint,
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
    borderColor: colors.fg,
  },
  radioDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.fg,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingBottom: Platform.OS === "ios" ? spacing.l : spacing.xl,
    paddingTop: spacing.m,
  },
  backBtn: { paddingVertical: 12, paddingRight: spacing.m },
  backText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    letterSpacing: 0.5,
  },
  nextBtn: {
    backgroundColor: colors.fg,
    paddingHorizontal: 36,
    paddingVertical: 16,
    borderRadius: radius.pill,
    minWidth: 130,
    alignItems: "center",
  },
  nextBtnDisabled: { opacity: 0.3 },
  nextText: {
    fontFamily: fonts.bodyMedium,
    color: colors.bg,
    fontSize: 13,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
});
