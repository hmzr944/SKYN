import * as Clipboard from "expo-clipboard";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Linking, Platform, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { ease } from "@/src/animation/ease";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { type Locale, useTranslation } from "@/src/i18n";
import {
  applyPrefs,
  bumpTime,
  DEFAULT_PREFS,
  formatTime,
  getPrefs,
  remindersSupported,
  type ReminderPrefs,
} from "@/src/services/reminders";
import { deleteAccount, deletionMessage } from "@/src/services/account";
import { eraseAll, exportAll, summarize, type DataSummary } from "@/src/services/userData";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, motion, radius, spacing, type } from "@/src/theme";

/**
 * Les reglages.
 *
 * Trois choses seulement y ont leur place : ce qui se regle, ce qui informe
 * sur le traitement des donnees, et ce qui est legalement du a l'utilisateur.
 * Pas de bouton qui ne mene nulle part — c'est precisement ce qu'il y avait
 * avant, et un reglage inerte fait douter du reste de l'app.
 */
/**
 * Les documents integraux, a une URL publique.
 *
 * Les depliants ci-dessous en donnent l'essentiel en français lisible ; les
 * boutiques d'applications, elles, exigent une adresse web stable, et la loi
 * française des mentions accessibles depuis n'importe ou. Les deux coexistent :
 * le texte court pour lire, l'URL pour faire foi.
 */
const LEGAL = "https://hmzr944.github.io/SKYN/legal";

export default function SettingsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { t, locale, setLocale } = useTranslation();
  const aUnCompte = !!user && user.user_id !== "guest";
  const [reminders, setReminders] = useState<ReminderPrefs>(DEFAULT_PREFS);
  const [data, setData] = useState<DataSummary | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setData(await summarize());
  }, []);

  useEffect(() => {
    getPrefs().then(setReminders);
    refresh();
  }, [refresh]);

  const update = async (next: ReminderPrefs) => {
    setReminders(next);
    setReminders(await applyPrefs(next));
  };

  const onExport = async () => {
    const json = await exportAll();
    await Clipboard.setStringAsync(json);
    Alert.alert(t("settings.exportedTitle"), t("settings.exportedBody"));
  };

  /** Demande confirmation, ici comme sur le web ou Alert n'a qu'un bouton. */
  const confirmer = (titre: string, question: string, faire: () => void) => {
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(`${titre}\n\n${question}`)) faire();
      return;
    }
    Alert.alert(titre, question, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("common.delete"), style: "destructive", onPress: faire },
    ]);
  };

  const onDeleteAccount = () => {
    confirmer(
      t("settings.deleteAccountConfirmTitle"),
      t("settings.deleteAccountConfirmBody"),
      async () => {
        const r = await deleteAccount(user?.user_id ?? null);
        await refresh();
        setReminders(DEFAULT_PREFS);
        Alert.alert(t("settings.deletionTitle"), deletionMessage(r));
        router.replace("/auth");
      },
    );
  };

  const onErase = () => {
    // Une suppression definitive se confirme. Sur le web, Alert n'a pas de
    // boutons multiples : on passe par la confirmation native du navigateur.
    const done = async () => {
      const n = await eraseAll();
      await refresh();
      setReminders(DEFAULT_PREFS);
      Alert.alert(t("settings.erasedTitle"), t("settings.erasedBody", { count: n }));
    };
    confirmer(t("settings.eraseConfirmTitle"), t("settings.eraseConfirmBody"), done);
  };

  const version =
    Constants.expoConfig?.version ?? Constants.easConfig?.version ?? "1.0.0";

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <View style={styles.header}>
        <AnimatedPressable
          style={styles.back}
          scaleTo={0.9}
          hitSlop={8}
          accessibilityLabel={t("common.back")}
          onPress={() => router.back()}
        >
          <Text style={styles.backText}>←</Text>
        </AnimatedPressable>
        <SkynLockup size={22} still />
        <View style={{ width: 36 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Reveal bouncy>
          <Text style={styles.title}>{t("settings.title")}</Text>
        </Reveal>

        {/* ————— Langue ————— */}
        <Reveal delay={20}>
          <Text style={styles.section}>{t("settings.language")}</Text>
          <View style={styles.card}>
            <View style={styles.langRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>{t("settings.language")}</Text>
                <Text style={styles.rowHint}>{t("settings.languageHint")}</Text>
              </View>
              <LanguageSwitch locale={locale} onChange={setLocale} />
            </View>
          </View>
        </Reveal>

        {/* ————— Rappels ————— */}
        <Reveal delay={40}>
          <Text style={styles.section}>{t("settings.remindersSection")}</Text>
          {/* La raison se lit AVANT les controles.
              Elle etait sous la carte : on appuyait d'abord sur deux
              interrupteurs qui ne bougeaient pas, et on lisait l'explication
              seulement apres — quand on l'a lue. */}
          {!remindersSupported ? (
            <Text style={styles.note} testID="settings-reminders-note">
              {t("settings.remindersUnsupported")}
            </Text>
          ) : null}
          <View style={styles.card}>
            <ReminderRow
              label={t("settings.remindersMorning")}
              hint={t("settings.remindersMorningHint")}
              toggleLabel={t("settings.remindersToggleLabel", { label: t("settings.remindersMorning").toLowerCase() })}
              bumpLabel={t("settings.bumpTimeLabel", { time: formatTime(reminders.amHour, reminders.amMinute) })}
              on={reminders.am}
              time={formatTime(reminders.amHour, reminders.amMinute)}
              onToggle={(v) => update({ ...reminders, am: v })}
              onBump={() => {
                const nt = bumpTime(reminders.amHour, reminders.amMinute);
                update({ ...reminders, amHour: nt.hour, amMinute: nt.minute });
              }}
            />
            <View style={styles.sep} />
            <ReminderRow
              label={t("settings.remindersEvening")}
              hint={t("settings.remindersEveningHint")}
              toggleLabel={t("settings.remindersToggleLabel", { label: t("settings.remindersEvening").toLowerCase() })}
              bumpLabel={t("settings.bumpTimeLabel", { time: formatTime(reminders.pmHour, reminders.pmMinute) })}
              on={reminders.pm}
              time={formatTime(reminders.pmHour, reminders.pmMinute)}
              onToggle={(v) => update({ ...reminders, pm: v })}
              onBump={() => {
                const nt = bumpTime(reminders.pmHour, reminders.pmMinute);
                update({ ...reminders, pmHour: nt.hour, pmMinute: nt.minute });
              }}
            />
          </View>
        </Reveal>

        {/* ————— Données ————— */}
        <Reveal delay={80}>
          <Text style={styles.section}>{t("settings.dataSection")}</Text>
          <View style={styles.card}>
            <View style={styles.statRow}>
              <Stat value={data?.scans ?? 0} label={t("settings.statScans")} />
              <Stat value={data?.joursDeJournal ?? 0} label={t("settings.statJournalDays")} />
              <Stat value={data?.suivis ?? 0} label={t("settings.statFollowups")} />
              <Stat value={data?.poidsKo ?? 0} label={t("settings.statKo")} />
            </View>
            <View style={styles.sep} />
            <Row
              label={t("settings.exportData")}
              hint={t("settings.exportHint")}
              onPress={onExport}
            />
            <View style={styles.sep} />
            <Row
              label={t("settings.eraseData")}
              hint={t("settings.eraseHint")}
              danger
              onPress={onErase}
            />
            {aUnCompte ? (
              <>
                <View style={styles.sep} />
                <Row
                  label={t("settings.deleteAccount")}
                  hint={t("settings.deleteAccountHint")}
                  danger
                  onPress={onDeleteAccount}
                />
              </>
            ) : null}
          </View>
        </Reveal>

        {/* ————— Confidentialité et cadre légal ————— */}
        <Reveal delay={120}>
          <Text style={styles.section}>{t("settings.legalSection")}</Text>
          <View style={styles.card}>
            <Fold
              id="donnees"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldDataTitle")}
              body={t("settings.foldDataBody")}
            />
            <View style={styles.sep} />
            <Fold
              id="medical"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldMedicalTitle")}
              body={t("settings.foldMedicalBody")}
            />
            <View style={styles.sep} />
            <Fold
              id="mineurs"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldMinorsTitle")}
              body={t("settings.foldMinorsBody")}
            />
            <View style={styles.sep} />
            <Fold
              id="droits"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldRightsTitle")}
              body={t("settings.foldRightsBody")}
            />
          </View>
        </Reveal>

        {/* ————— À propos ————— */}
        <Reveal delay={160}>
          <Text style={styles.section}>{t("settings.aboutSection")}</Text>
          <View style={styles.card}>
            <Fold
              id="moteur"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldEngineTitle")}
              body={t("settings.foldEngineBody")}
            />
            <View style={styles.sep} />
            <Fold
              id="licences"
              open={open}
              setOpen={setOpen}
              label={t("settings.foldLicensesTitle")}
              body={t("settings.foldLicensesBody")}
            />
            <View style={styles.sep} />
            <Row
              label={t("settings.legalDocs")}
              hint={t("settings.legalDocsHint")}
              onPress={() => {
                Linking.openURL(`${LEGAL}/confidentialite.html`).catch(() => {
                  Alert.alert(t("settings.legalUnavailableTitle"), t("settings.legalUnavailableBody"));
                });
              }}
            />
            <View style={styles.sep} />
            <View style={styles.versionRow}>
              <Text style={styles.rowLabel}>{t("settings.version")}</Text>
              <Text style={styles.version}>{version}</Text>
            </View>
          </View>
        </Reveal>

        <Text style={styles.foot}>{t("settings.footNote")}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function LanguageSwitch({ locale, onChange }: { locale: Locale; onChange: (l: Locale) => void }) {
  const { t } = useTranslation();
  return (
    <View style={styles.langSwitch}>
      {(["fr", "en"] as const).map((l) => (
        <AnimatedPressable
          key={l}
          style={[styles.langOption, locale === l && styles.langOptionOn]}
          scaleTo={0.94}
          haptic="light"
          accessibilityRole="button"
          accessibilityState={{ selected: locale === l }}
          accessibilityLabel={l === "fr" ? t("settings.french") : t("settings.english")}
          onPress={() => onChange(l)}
        >
          <Text style={[styles.langOptionText, locale === l && styles.langOptionTextOn]}>
            {l === "fr" ? "FR" : "EN"}
          </Text>
        </AnimatedPressable>
      ))}
    </View>
  );
}

/* ------------------------------------------------------------------ */
function Stat({ value, label }: { value: number; label: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Row({
  label,
  hint,
  danger,
  onPress,
}: {
  label: string;
  hint?: string;
  danger?: boolean;
  onPress: () => void;
}) {
  return (
    <AnimatedPressable style={styles.row} scaleTo={0.99} haptic="medium" onPress={onPress}>
      <View style={{ flex: 1 }}>
        <Text style={[styles.rowLabel, danger && styles.danger]}>{label}</Text>
        {hint ? <Text style={styles.rowHint}>{hint}</Text> : null}
      </View>
      <Text style={[styles.chevron, danger && styles.danger]}>›</Text>
    </AnimatedPressable>
  );
}

/** Un pli : le texte long ne s'impose pas, il se demande. */
function Fold({
  id,
  open,
  setOpen,
  label,
  body,
}: {
  id: string;
  open: string | null;
  setOpen: (v: string | null) => void;
  label: string;
  body: string;
}) {
  const isOpen = open === id;
  const [hauteur, setHauteur] = useState(0);
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withTiming(isOpen ? 1 : 0, {
      duration: reduced ? 0 : motion.base,
      easing: ease.out,
    });
  }, [isOpen, t, reduced]);

  // Le depliant se REFERME aussi. Il s'ouvrait avec une entree animee mais
  // disparaissait d'un coup : la moitie du geste seulement etait dessinee, et
  // c'est la fermeture qu'on remarque, parce qu'on la declenche exprès.
  const corps = useAnimatedStyle(() => ({
    height: t.value * hauteur,
    opacity: t.value,
  }));
  const signe = useAnimatedStyle(() => ({
    transform: [{ rotate: `${t.value * 135}deg` }],
  }));

  return (
    <View>
      <AnimatedPressable
        style={styles.row}
        scaleTo={0.99}
        haptic={false}
        accessibilityState={{ expanded: isOpen } as { selected?: boolean }}
        accessibilityLabel={label}
        onPress={() => setOpen(isOpen ? null : id)}
      >
        <Text style={[styles.rowLabel, { flex: 1 }]}>{label}</Text>
        <Animated.Text style={[styles.chevron, signe]}>+</Animated.Text>
      </AnimatedPressable>

      <Animated.View style={[styles.foldClip, corps]}>
        <View
          onLayout={(e) => {
            const h = Math.ceil(e.nativeEvent.layout.height);
            setHauteur((prev) => (Math.abs(prev - h) < 1 ? prev : h));
          }}
        >
          <Text style={styles.body}>{body}</Text>
        </View>
      </Animated.View>
    </View>
  );
}

function ReminderRow({
  label,
  hint,
  toggleLabel,
  bumpLabel,
  on,
  time,
  onToggle,
  onBump,
}: {
  label: string;
  hint: string;
  toggleLabel: string;
  bumpLabel: string;
  on: boolean;
  time: string;
  onToggle: (v: boolean) => void;
  onBump: () => void;
}) {
  // Hors service, la rangee ENTIERE s'eteint : libelle compris. Un intitule a
  // pleine opacite au-dessus d'un interrupteur mort se lit comme un reglage
  // disponible, et c'est l'appui suivant qui apprend le contraire.
  return (
    <View style={[styles.row, !remindersSupported && styles.rowEteinte]}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowHint}>{hint}</Text>
      </View>
      <AnimatedPressable
        style={[styles.timeChip, on && styles.timeChipOn]}
        disabled={!on}
        scaleTo={0.94}
        onPress={onBump}
        accessibilityLabel={bumpLabel}
      >
        <Text style={[styles.timeText, on && styles.timeTextOn]}>{time}</Text>
      </AnimatedPressable>
      <Switch
        value={on}
        disabled={!remindersSupported}
        onValueChange={onToggle}
        trackColor={{ false: colors.fgFaint, true: colors.accent }}
        thumbColor={colors.bg}
        accessibilityLabel={toggleLabel}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingVertical: spacing.s,
  },
  back: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSunken,
  },
  backText: { color: colors.fg, fontSize: 17 },
  scroll: { paddingHorizontal: spacing.l, paddingBottom: spacing.xxxl },
  title: { ...type.display, color: colors.fg, marginBottom: spacing.l },
  section: { ...type.kicker, color: colors.fgDim, marginBottom: spacing.s, marginTop: spacing.l },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    overflow: "hidden",
  },
  sep: { height: 1, backgroundColor: colors.borderSubtle },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    paddingHorizontal: spacing.m,
    paddingVertical: 14,
    minHeight: 56,
  },
  // Meme valeur que celle d'AnimatedPressable : deux controles hors service
  // cote a cote doivent s'eteindre pareil.
  rowEteinte: { opacity: 0.42 },
  rowLabel: { ...type.label, color: colors.fg },
  rowHint: { ...type.bodySmall, color: colors.fgDim, marginTop: 2 },
  foldClip: { overflow: "hidden" },
  chevron: { ...type.subtitle, color: colors.fgDim },
  danger: { color: colors.accent },
  body: {
    ...type.bodySmall,
    color: colors.fgMuted,
    paddingHorizontal: spacing.m,
    paddingBottom: spacing.m,
  },

  statRow: { flexDirection: "row", paddingVertical: spacing.m },
  stat: { flex: 1, alignItems: "center", gap: 2 },
  statValue: {
    ...type.subtitle,
    color: colors.fg,
    fontVariant: ["tabular-nums"],
  },
  statLabel: { ...type.bodySmall, fontSize: 11, color: colors.fgDim },

  timeChip: {
    paddingVertical: 9,
    paddingHorizontal: 13,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    minHeight: 44,
    justifyContent: "center",
  },
  timeChipOn: { borderColor: colors.accentLine },
  timeText: { ...type.bodySmall, color: colors.fgDim },
  timeTextOn: { color: colors.accent },

  langRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    paddingHorizontal: spacing.m,
    paddingVertical: 14,
    minHeight: 56,
  },
  langSwitch: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.pill,
    padding: 3,
    gap: 2,
  },
  langOption: {
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: radius.pill,
    minWidth: 44,
    minHeight: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  langOptionOn: { backgroundColor: colors.accent },
  langOptionText: { ...type.label, color: colors.fgDim },
  langOptionTextOn: { color: colors.onAccent },

  versionRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: spacing.m,
    paddingVertical: 16,
  },
  version: { ...type.bodySmall, color: colors.fgDim, fontVariant: ["tabular-nums"] },
  note: { ...type.bodySmall, color: colors.fgDim, marginTop: spacing.s },
  foot: {
    ...type.bodySmall,
    fontSize: 11,
    color: colors.fgDim,
    textAlign: "center",
    marginTop: spacing.xl,
  },
});
