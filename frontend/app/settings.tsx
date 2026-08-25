import * as Clipboard from "expo-clipboard";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Linking, Platform, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
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
import { colors, radius, spacing, type } from "@/src/theme";

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
    Alert.alert(
      "Données copiées",
      "Vos analyses, votre journal et vos suivis sont dans le presse-papier, " +
        "au format JSON. Collez-les où vous voulez les conserver.",
    );
  };

  /** Demande confirmation, ici comme sur le web ou Alert n'a qu'un bouton. */
  const confirmer = (titre: string, question: string, faire: () => void) => {
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(`${titre}\n\n${question}`)) faire();
      return;
    }
    Alert.alert(titre, question, [
      { text: "Annuler", style: "cancel" },
      { text: "Supprimer", style: "destructive", onPress: faire },
    ]);
  };

  const onDeleteAccount = () => {
    confirmer(
      "Supprimer votre compte ?",
      "Cela ferme votre compte et supprime vos analyses, ici et en ligne. " +
        "C'est définitif : rien ne pourra être récupéré.",
      async () => {
        const r = await deleteAccount(user?.user_id ?? null);
        await refresh();
        setReminders(DEFAULT_PREFS);
        Alert.alert("Suppression", deletionMessage(r));
        router.replace("/auth");
      },
    );
  };

  const onErase = () => {
    // Une suppression definitive se confirme. Sur le web, Alert n'a pas de
    // boutons multiples : on passe par la confirmation native du navigateur.
    const question =
      "Cela supprime vos analyses, votre journal, vos suivis et vos réglages. " +
      "C'est définitif et immédiat.";
    const done = async () => {
      const n = await eraseAll();
      await refresh();
      setReminders(DEFAULT_PREFS);
      Alert.alert("Données supprimées", `${n} entrées effacées de cet appareil.`);
    };
    confirmer("Tout supprimer ?", question, done);
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
          accessibilityLabel="Retour"
          onPress={() => router.back()}
        >
          <Text style={styles.backText}>←</Text>
        </AnimatedPressable>
        <SkynLockup size={22} still />
        <View style={{ width: 36 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Text style={styles.title}>Réglages</Text>

        {/* ————— Rappels ————— */}
        <Reveal delay={40}>
          <Text style={styles.section}>Rappels</Text>
          <View style={styles.card}>
            <ReminderRow
              label="Le matin"
              hint="Nettoyant, soin, protection solaire"
              on={reminders.am}
              time={formatTime(reminders.amHour, reminders.amMinute)}
              onToggle={(v) => update({ ...reminders, am: v })}
              onBump={() => {
                const t = bumpTime(reminders.amHour, reminders.amMinute);
                update({ ...reminders, amHour: t.hour, amMinute: t.minute });
              }}
            />
            <View style={styles.sep} />
            <ReminderRow
              label="Le soir"
              hint="Le moment qui compte le plus"
              on={reminders.pm}
              time={formatTime(reminders.pmHour, reminders.pmMinute)}
              onToggle={(v) => update({ ...reminders, pm: v })}
              onBump={() => {
                const t = bumpTime(reminders.pmHour, reminders.pmMinute);
                update({ ...reminders, pmHour: t.hour, pmMinute: t.minute });
              }}
            />
          </View>
          {!remindersSupported ? (
            <Text style={styles.note}>
              Les rappels ne fonctionnent pas dans un navigateur. Ils s&apos;activeront
              dans l&apos;application installée.
            </Text>
          ) : null}
        </Reveal>

        {/* ————— Données ————— */}
        <Reveal delay={80}>
          <Text style={styles.section}>Vos données</Text>
          <View style={styles.card}>
            <View style={styles.statRow}>
              <Stat value={data?.scans ?? 0} label="analyses" />
              <Stat value={data?.joursDeJournal ?? 0} label="jours notés" />
              <Stat value={data?.suivis ?? 0} label="suivis" />
              <Stat value={data?.poidsKo ?? 0} label="Ko" />
            </View>
            <View style={styles.sep} />
            <Row
              label="Exporter mes données"
              hint="Copie tout au format JSON"
              onPress={onExport}
            />
            <View style={styles.sep} />
            <Row
              label="Supprimer mes données"
              hint="Définitif, immédiat, sur cet appareil"
              danger
              onPress={onErase}
            />
            {aUnCompte ? (
              <>
                <View style={styles.sep} />
                <Row
                  label="Supprimer mon compte"
                  hint="Ferme le compte et efface aussi la copie en ligne"
                  danger
                  onPress={onDeleteAccount}
                />
              </>
            ) : null}
          </View>
        </Reveal>

        {/* ————— Confidentialité et cadre légal ————— */}
        <Reveal delay={120}>
          <Text style={styles.section}>Confidentialité et cadre légal</Text>
          <View style={styles.card}>
            <Fold
              id="donnees"
              open={open}
              setOpen={setOpen}
              label="Où vont vos données"
              body={
                "Vos analyses, votre journal et vos suivis sont stockés sur cet appareil, " +
                "pas sur nos serveurs.\n\n" +
                "Vos photos partent au moteur d'analyse le temps du calcul, puis sont " +
                "effacées de l'appareil. Elles ne sont ni conservées ni réutilisées pour " +
                "entraîner quoi que ce soit.\n\n" +
                "Si vous avez un compte, seuls votre identifiant et vos scores de synthèse " +
                "sont sauvegardés pour vous les retrouver sur un autre appareil."
              }
            />
            <View style={styles.sep} />
            <Fold
              id="medical"
              open={open}
              setOpen={setOpen}
              label="Avertissement médical"
              body={
                "SKYN est un outil de mesure et de suivi. Ce n'est pas un dispositif " +
                "médical et il ne pose aucun diagnostic.\n\n" +
                "Les lectures qu'il propose décrivent ce qui est fréquent ou inhabituel, " +
                "jamais une certitude. Elles ne remplacent pas l'avis d'un dermatologue.\n\n" +
                "Consultez sans attendre en cas de douleur, de gonflement, de lésions qui " +
                "s'étendent, ou si une réaction apparaît après un nouveau produit."
              }
            />
            <View style={styles.sep} />
            <Fold
              id="mineurs"
              open={open}
              setOpen={setOpen}
              label="Utilisation par un mineur"
              body={
                "L'acné touche surtout les adolescents, et l'app leur est destinée.\n\n" +
                "En dessous de 15 ans, le consentement d'un parent est requis pour le " +
                "traitement des données en France. Les données restant sur l'appareil, " +
                "aucun profil n'est constitué de notre côté."
              }
            />
            <View style={styles.sep} />
            <Fold
              id="droits"
              open={open}
              setOpen={setOpen}
              label="Vos droits"
              body={
                "Accès, rectification, effacement, portabilité : ces droits s'exercent " +
                "directement depuis la section « Vos données » ci-dessus, sans avoir à " +
                "nous écrire ni à nous croire sur parole.\n\n" +
                "L'export vous rend l'intégralité de ce qui est conservé.\n\n" +
                "« Supprimer mes données » efface ce qui est sur cet appareil. " +
                "« Supprimer mon compte » ferme en plus le compte et efface la copie " +
                "en ligne de vos scores. L'app vous dit ensuite ce qui a réellement " +
                "été supprimé, y compris si quelque chose a échoué."
              }
            />
          </View>
        </Reveal>

        {/* ————— À propos ————— */}
        <Reveal delay={160}>
          <Text style={styles.section}>À propos</Text>
          <View style={styles.card}>
            <Fold
              id="moteur"
              open={open}
              setOpen={setOpen}
              label="Comment l'analyse fonctionne"
              body={
                "Le moteur repère 468 points du visage, en déduit 13 zones, et écarte " +
                "sourcils, cils, lèvres et narines du calcul.\n\n" +
                "Il compte les lésions et les classe par signature colorimétrique, estime " +
                "le type de peau par différence de brillance entre zone T et zone U, et le " +
                "phototype par angle typologique.\n\n" +
                "Les produits sont ensuite appariés à ce relevé, avec un niveau de preuve " +
                "affiché pour chacun et un contrôle des incompatibilités d'actifs."
              }
            />
            <View style={styles.sep} />
            <Fold
              id="licences"
              open={open}
              setOpen={setOpen}
              label="Licences"
              body={
                "Outfit, de Rodrigo Fuenzalida, sous SIL Open Font License 1.1.\n\n" +
                "Fraunces, de Undercase Type, sous SIL Open Font License 1.1.\n\n" +
                "MediaPipe (guidage du cadrage), de Google, licence Apache 2.0.\n\n" +
                "OpenCV, SciPy et NumPy, licences BSD.\n\n" +
                "React Native et Expo, licence MIT."
              }
            />
            <View style={styles.sep} />
            <Row
              label="Documents légaux"
              hint="Confidentialité, mentions légales, conditions"
              onPress={() => {
                Linking.openURL(`${LEGAL}/confidentialite.html`).catch(() => {
                  Alert.alert(
                    "Page indisponible",
                    "Impossible d'ouvrir le navigateur. Les points essentiels " +
                      "restent dépliables ci-dessus.",
                  );
                });
              }}
            />
            <View style={styles.sep} />
            <View style={styles.versionRow}>
              <Text style={styles.rowLabel}>Version</Text>
              <Text style={styles.version}>{version}</Text>
            </View>
          </View>
        </Reveal>

        <Text style={styles.foot}>
          SKYN n&apos;est pas un dispositif médical et ne remplace pas un avis dermatologique.
        </Text>
      </ScrollView>
    </SafeAreaView>
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
  return (
    <View>
      <AnimatedPressable
        style={styles.row}
        scaleTo={0.99}
        haptic={false}
        onPress={() => setOpen(isOpen ? null : id)}
      >
        <Text style={[styles.rowLabel, { flex: 1 }]}>{label}</Text>
        <Text style={styles.chevron}>{isOpen ? "−" : "+"}</Text>
      </AnimatedPressable>
      {isOpen ? (
        <Reveal distance={6}>
          <Text style={styles.body}>{body}</Text>
        </Reveal>
      ) : null}
    </View>
  );
}

function ReminderRow({
  label,
  hint,
  on,
  time,
  onToggle,
  onBump,
}: {
  label: string;
  hint: string;
  on: boolean;
  time: string;
  onToggle: (v: boolean) => void;
  onBump: () => void;
}) {
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowHint}>{hint}</Text>
      </View>
      <AnimatedPressable
        style={[styles.timeChip, on && styles.timeChipOn]}
        disabled={!on}
        scaleTo={0.94}
        onPress={onBump}
      >
        <Text style={[styles.timeText, on && styles.timeTextOn]}>{time}</Text>
      </AnimatedPressable>
      <Switch
        value={on}
        disabled={!remindersSupported}
        onValueChange={onToggle}
        trackColor={{ false: colors.fgFaint, true: colors.accent }}
        thumbColor={colors.bg}
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
  rowLabel: { ...type.label, color: colors.fg },
  rowHint: { ...type.bodySmall, color: colors.fgDim, marginTop: 2 },
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
