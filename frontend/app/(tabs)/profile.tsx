import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import Svg, { Circle, Path } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { HowItWorksModal } from "@/src/components/HowItWorksModal";

const SKIN_TYPES = ["Normale", "Mixte", "Grasse", "Sèche"];
const GOALS = ["Hydratation", "Anti-âge", "Éclat", "Pores"];

const SETTINGS_ROWS = [
  { id: "settings-notifications", icon: "notifications-outline" as const, label: "Notifications", enabled: false },
  { id: "settings-privacy", icon: "lock-closed-outline" as const, label: "Confidentialité", enabled: false },
  { id: "settings-how-it-works", icon: "sparkles-outline" as const, label: "Comment ça marche", enabled: true },
  { id: "settings-about", icon: "information-circle-outline" as const, label: "À propos", enabled: false },
];

/** Cachet circulaire — remplace l'avatar rond classique par un anneau
 * pointillé façon tampon de dossier, signature propre à cet écran. */
function DossierStamp({ initials }: { initials: string }) {
  return (
    <View style={styles.stampWrap}>
      <Svg width={104} height={104} viewBox="0 0 104 104" style={StyleSheet.absoluteFill}>
        <Circle
          cx={52} cy={52} r={49}
          stroke={colors.accent}
          strokeWidth={1.4}
          strokeDasharray="1 7"
          fill="none"
        />
      </Svg>
      <View style={styles.stampCore}>
        <Text style={styles.stampText}>{initials}</Text>
      </View>
    </View>
  );
}

export default function ProfileScreen() {
  const router = useRouter();
  const { user, profile, refreshProfile, signOut } = useAuth();
  const [skinType, setSkinType] = useState<string | null>(profile?.skin_type ?? null);
  const [goals, setGoals] = useState<string[]>(profile?.goals ?? []);
  const [howItWorksVisible, setHowItWorksVisible] = useState(false);

  const initials = (user?.name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const selectSkinType = async (value: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSkinType(value);
    try {
      await api.updateProfile({ skin_type: value });
      await refreshProfile();
    } catch {
      /* ignore */
    }
  };

  const toggleGoal = async (value: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const next = goals.includes(value)
      ? goals.filter((g) => g !== value)
      : [...goals, value];
    setGoals(next);
    try {
      await api.updateProfile({ goals: next });
      await refreshProfile();
    } catch {
      /* ignore */
    }
  };

  const onSignOut = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    await signOut();
    router.replace("/onboarding");
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* En-tête dossier — portrait à gauche, identité à droite (jamais centré) */}
        <FadeIn distance={10}>
          <View style={styles.identityRow}>
            <DossierStamp initials={initials} />
            <View style={styles.identityText}>
              <Text style={styles.dossierEyebrow}>DOSSIER CUTANÉ</Text>
              <Text style={styles.name} numberOfLines={1}>{user?.name}</Text>
              <Text style={styles.email} numberOfLines={1}>{user?.email}</Text>
            </View>
          </View>
        </FadeIn>

        {/* Type de peau — chips "tampon" à contour marqué, différentes des pills du Dashboard */}
        <FadeIn delay={100}>
          <Text style={styles.sectionTitle}>Mon type de peau</Text>
          <View style={styles.pillsRow}>
            {SKIN_TYPES.map((type) => {
              const selected = skinType === type;
              return (
                <AnimatedPressable
                  key={type}
                  testID={`skin-type-${type}`}
                  style={[styles.stampPill, selected && styles.stampPillSelected]}
                  scaleTo={0.96}
                  onPress={() => selectSkinType(type)}
                >
                  <Text style={[styles.stampPillText, selected && styles.stampPillTextSelected]}>
                    {type}
                  </Text>
                </AnimatedPressable>
              );
            })}
          </View>
        </FadeIn>

        <FadeIn delay={160}>
          <Text style={styles.sectionTitle}>Objectifs</Text>
          <View style={styles.pillsRow}>
            {GOALS.map((goal) => {
              const active = goals.includes(goal);
              return (
                <AnimatedPressable
                  key={goal}
                  testID={`goal-${goal}`}
                  style={[styles.tag, active && styles.tagActive]}
                  scaleTo={0.96}
                  onPress={() => toggleGoal(goal)}
                >
                  {active ? <View style={styles.tagCheck} /> : null}
                  <Text style={[styles.tagText, active && styles.tagTextActive]}>
                    {goal}
                  </Text>
                </AnimatedPressable>
              );
            })}
          </View>
        </FadeIn>

        {/* Paramètres — liste à icônes rondes, distincte du style carte du reste de l'app */}
        <FadeIn delay={220}>
          <Text style={styles.sectionTitle}>Paramètres</Text>
          <View style={styles.list}>
            {SETTINGS_ROWS.map((row, i) => (
              <TouchableOpacity
                key={row.id}
                testID={row.id}
                style={[styles.row, i === SETTINGS_ROWS.length - 1 && styles.rowLast]}
                disabled={!row.enabled}
                onPress={row.id === "settings-how-it-works" ? () => setHowItWorksVisible(true) : undefined}
                activeOpacity={row.enabled ? 0.6 : 1}
              >
                <View style={styles.rowIconWrap}>
                  <Ionicons name={row.icon} size={16} color={colors.accent} />
                </View>
                <Text style={styles.rowLabel}>{row.label}</Text>
                <Ionicons name="chevron-forward" size={16} color={colors.fgDim} />
              </TouchableOpacity>
            ))}
          </View>
        </FadeIn>

        <FadeIn delay={280}>
          <AnimatedPressable testID="profile-signout-btn" style={styles.signOutBtn} onPress={onSignOut}>
            <Svg width={14} height={14} viewBox="0 0 14 14" style={{ marginRight: 6 }}>
              <Path d="M5 1H2v12h3M9 4l3 3-3 3M12 7H5" stroke={colors.accent} strokeWidth={1.3} fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </Svg>
            <Text style={styles.signOutText}>Se déconnecter</Text>
          </AnimatedPressable>
        </FadeIn>
      </ScrollView>

      <HowItWorksModal visible={howItWorksVisible} onClose={() => setHowItWorksVisible(false)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.xxl,
  },
  identityRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    marginBottom: spacing.xl,
  },
  stampWrap: {
    width: 104,
    height: 104,
    alignItems: "center",
    justifyContent: "center",
  },
  stampCore: {
    width: 78,
    height: 78,
    borderRadius: 39,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    ...shadow.button,
  },
  stampText: {
    fontFamily: fonts.heading,
    fontSize: 26,
    color: colors.onAccent,
  },
  identityText: { flex: 1 },
  dossierEyebrow: {
    fontFamily: fonts.bodyMedium,
    fontSize: 9,
    letterSpacing: 2,
    color: colors.fgDim,
    marginBottom: 4,
  },
  name: {
    fontFamily: fonts.heading,
    fontSize: 22,
    color: colors.fg,
    letterSpacing: -0.4,
  },
  email: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgMuted,
    marginTop: 2,
  },
  sectionTitle: {
    fontFamily: fonts.body,
    fontSize: 11,
    letterSpacing: 1.5,
    color: colors.fgDim,
    textTransform: "uppercase",
    marginBottom: spacing.s,
    marginTop: spacing.l,
  },
  pillsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s },
  stampPill: {
    borderWidth: 1.5,
    borderColor: colors.borderMid,
    backgroundColor: "transparent",
    borderRadius: radius.pill,
    paddingVertical: 9,
    paddingHorizontal: spacing.m,
  },
  stampPillSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.accent,
  },
  stampPillText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fg,
  },
  stampPillTextSelected: { color: colors.onAccent },
  tag: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: spacing.m,
  },
  tagActive: { backgroundColor: colors.lime },
  tagCheck: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: colors.onLime,
    marginRight: 6,
  },
  tagText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fgMuted,
  },
  tagTextActive: { color: colors.onLime },
  list: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.md,
    overflow: "hidden",
    ...shadow.card,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
  },
  rowLast: { borderBottomWidth: 0 },
  rowIconWrap: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.accentSofter,
    alignItems: "center",
    justifyContent: "center",
  },
  rowLabel: {
    flex: 1,
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.fg,
  },
  signOutBtn: {
    flexDirection: "row",
    marginTop: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.m,
  },
  signOutText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.accent,
    letterSpacing: 0.5,
  },
});
