import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Switch, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { HowItWorksModal } from "@/src/components/HowItWorksModal";
import {
  applyPrefs,
  bumpTime,
  DEFAULT_PREFS,
  formatTime,
  getPrefs,
  remindersSupported,
  type ReminderPrefs,
} from "@/src/services/reminders";

const SKIN_TYPES = ["Normale", "Mixte", "Grasse", "Sèche"];
const GOALS = ["Hydratation", "Anti-âge", "Éclat", "Pores"];

export default function ProfileScreen() {
  const router = useRouter();
  const { user, profile, refreshProfile, signOut } = useAuth();
  const [reminders, setReminders] = useState<ReminderPrefs>(DEFAULT_PREFS);

  useEffect(() => {
    getPrefs().then(setReminders);
  }, []);

  // Toute modification repasse par applyPrefs, qui reprogramme reellement les
  // rappels — et qui peut renvoyer l'inverse de ce qui a ete demande si le
  // systeme refuse l'autorisation.
  const updateReminders = useCallback(async (next: ReminderPrefs) => {
    setReminders(next);
    Haptics.selectionAsync();
    setReminders(await applyPrefs(next));
  }, []);
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
    router.replace("/auth");
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <FadeIn distance={10}>
          <Text style={styles.title}>Profil</Text>
        </FadeIn>

        <FadeIn delay={60}>
          <View style={styles.identity}>
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{initials}</Text>
            </View>
            <Text style={styles.name}>{user?.name}</Text>
            <Text style={styles.email}>{user?.email}</Text>
          </View>
        </FadeIn>

        <FadeIn delay={120}>
          <Text style={styles.sectionTitle}>Mon type de peau</Text>
          <View style={styles.pillsRow}>
            {SKIN_TYPES.map((type) => {
              const selected = skinType === type;
              return (
                <AnimatedPressable
                  key={type}
                  testID={`skin-type-${type}`}
                  style={[styles.pill, selected && styles.pillSelected]}
                  scaleTo={0.96}
                  onPress={() => selectSkinType(type)}
                >
                  <Text style={[styles.pillText, selected && styles.pillTextSelected]}>
                    {type}
                  </Text>
                </AnimatedPressable>
              );
            })}
          </View>
        </FadeIn>

        <FadeIn delay={180}>
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
                  <Text style={[styles.tagText, active && styles.tagTextActive]}>
                    {goal}
                  </Text>
                </AnimatedPressable>
              );
            })}
          </View>
        </FadeIn>

        <FadeIn delay={240}>
          <Text style={styles.sectionTitle}>Paramètres</Text>
          <View style={styles.list}>
            <View style={styles.row}>
              <View style={styles.rowText}>
                <Text style={styles.rowLabel}>Rappel du matin</Text>
                <TouchableOpacity
                  testID="reminder-am-time"
                  disabled={!reminders.am}
                  onPress={() => {
                    const t = bumpTime(reminders.amHour, reminders.amMinute);
                    updateReminders({ ...reminders, amHour: t.hour, amMinute: t.minute });
                  }}
                >
                  <Text style={[styles.rowHint, reminders.am && styles.rowHintActive]}>
                    {formatTime(reminders.amHour, reminders.amMinute)}
                  </Text>
                </TouchableOpacity>
              </View>
              <Switch
                testID="reminder-am"
                value={reminders.am}
                disabled={!remindersSupported}
                onValueChange={(v) => updateReminders({ ...reminders, am: v })}
                trackColor={{ false: colors.fgFaint, true: colors.accent }}
                thumbColor={colors.bg}
              />
            </View>
            <View style={styles.row}>
              <View style={styles.rowText}>
                <Text style={styles.rowLabel}>Rappel du soir</Text>
                <TouchableOpacity
                  testID="reminder-pm-time"
                  disabled={!reminders.pm}
                  onPress={() => {
                    const t = bumpTime(reminders.pmHour, reminders.pmMinute);
                    updateReminders({ ...reminders, pmHour: t.hour, pmMinute: t.minute });
                  }}
                >
                  <Text style={[styles.rowHint, reminders.pm && styles.rowHintActive]}>
                    {formatTime(reminders.pmHour, reminders.pmMinute)}
                  </Text>
                </TouchableOpacity>
              </View>
              <Switch
                testID="reminder-pm"
                value={reminders.pm}
                disabled={!remindersSupported}
                onValueChange={(v) => updateReminders({ ...reminders, pm: v })}
                trackColor={{ false: colors.fgFaint, true: colors.accent }}
                thumbColor={colors.bg}
              />
            </View>
            <TouchableOpacity testID="settings-privacy" style={styles.row} disabled>
              <Text style={styles.rowLabel}>Confidentialité</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.fgDim} />
            </TouchableOpacity>
            <TouchableOpacity
              testID="settings-how-it-works"
              style={styles.row}
              onPress={() => setHowItWorksVisible(true)}
            >
              <Text style={styles.rowLabel}>Comment ça marche</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.fgDim} />
            </TouchableOpacity>
            <TouchableOpacity testID="settings-about" style={[styles.row, styles.rowLast]} disabled>
              <Text style={styles.rowLabel}>À propos</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.fgDim} />
            </TouchableOpacity>
          </View>
        </FadeIn>

        <FadeIn delay={300}>
          <AnimatedPressable testID="profile-signout-btn" style={styles.signOutBtn} onPress={onSignOut}>
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
  title: {
    fontFamily: fonts.heading,
    fontSize: 24,
    color: colors.fg,
    letterSpacing: -0.3,
    marginBottom: spacing.l,
  },
  identity: {
    alignItems: "center",
    marginBottom: spacing.xl,
  },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.s,
    ...shadow.button,
  },
  avatarText: {
    fontFamily: fonts.heading,
    fontSize: 28,
    color: colors.onAccent,
  },
  name: {
    fontFamily: fonts.bodyMedium,
    fontSize: 17,
    color: colors.fg,
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
  pillsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.s,
  },
  pill: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: spacing.m,
  },
  pillSelected: {
    backgroundColor: colors.accent,
  },
  pillText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fgMuted,
  },
  pillTextSelected: {
    color: colors.onAccent,
  },
  tag: {
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: spacing.m,
  },
  tagActive: {
    backgroundColor: colors.ok,
  },
  tagText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fgMuted,
  },
  tagTextActive: {
    color: colors.onOk,
  },
  list: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.m,
    paddingHorizontal: spacing.m,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
  },
  rowLast: { borderBottomWidth: 0 },
  rowText: { gap: 4, alignItems: "flex-start" },
  rowHint: {
    fontFamily: fonts.bodyMedium,
    fontSize: 12,
    color: colors.fgDim,
    // Apple demande 44 px : sans ce remplissage la cible faisait 15 px.
    paddingVertical: 13,
    paddingHorizontal: 14,
    minHeight: 44,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    overflow: "hidden",
  },
  rowHintActive: { color: colors.accent, borderColor: colors.accentLine },
  rowLabel: {
    fontFamily: fonts.body,
    fontSize: 15,
    color: colors.fg,
  },
  signOutBtn: {
    marginTop: spacing.xl,
    alignItems: "center",
    paddingVertical: spacing.m,
  },
  signOutText: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.accent,
    letterSpacing: 0.5,
  },
});
