import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Chip } from "@/src/components/ui/Chip";
import { Disclosure } from "@/src/components/ui/Disclosure";
import { Reveal } from "@/src/components/ui/Reveal";
import { track } from "@/src/services/analytics";
import {
  activeTracking,
  candidates,
  dayNumber,
  isAlert,
  logDay,
  readTracking,
  SIGNALS,
  startTracking,
  stopTracking,
  todayLogged,
  type Signal,
  type Tracking,
} from "@/src/services/introduction";
import type { StoredRoutine } from "@/src/services/routineStore";
import { colors, fonts, radius, spacing, type } from "@/src/theme";
import type { ProductPick } from "@/src/types/analysis";

/**
 * Le suivi d'introduction, dans l'onglet ou l'habitude quotidienne existe deja.
 *
 * Trois etats seulement : rien en cours (on propose de demarrer), un point a
 * renseigner aujourd'hui, ou la lecture du moment. Volontairement pauvre :
 * c'est une question de trois secondes, tous les jours, pendant quelques
 * semaines — tout ce qui l'allonge la fera abandonner.
 */
export function IntroductionCard({ routine }: { routine: StoredRoutine | null }) {
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [picked, setPicked] = useState<Signal[]>([]);

  const refresh = useCallback(async () => {
    setTracking(await activeTracking());
    setLoaded(true);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (loaded) track("intro_feature_seen");
  }, [loaded]);

  if (!loaded || !routine) return null;

  const eligible = candidates([...routine.am, ...routine.pm, ...routine.weekly]);
  if (!tracking && eligible.length === 0) return null;

  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>Suivi d&apos;introduction</Text>
      {tracking ? (
        <Running
          tracking={tracking}
          picked={picked}
          setPicked={setPicked}
          onChange={refresh}
        />
      ) : (
        <Idle products={eligible} onStarted={refresh} />
      )}
    </View>
  );
}

/* ------------------------------------------------------------------ */
function Idle({
  products,
  onStarted,
}: {
  products: ProductPick[];
  onStarted: () => void;
}) {
  return (
    <>
      <Text style={styles.lede}>Vous venez d&apos;introduire un produit ?</Text>
      <View style={styles.chips}>
        {products.slice(0, 4).map((p) => (
          <Chip
            key={p.id}
            testID={`intro-start-${p.id}`}
            label={p.name}
            on={false}
            onPress={async () => {
              await startTracking(p);
              onStarted();
            }}
          />
        ))}
      </View>
      <Disclosure testID="intro-why">
        <Text style={styles.helper}>
          {"Quand vous commencez un actif, la peau peut réagir les premières " +
            "semaines. C'est le moment où l'on abandonne le plus souvent. En le " +
            "suivant jour par jour, on sait si ça passe ou s'il faut arrêter."}
        </Text>
      </Disclosure>
    </>
  );
}

/* ------------------------------------------------------------------ */
function Running({
  tracking,
  picked,
  setPicked,
  onChange,
}: {
  tracking: Tracking;
  picked: Signal[];
  setPicked: (s: Signal[]) => void;
  onChange: () => void;
}) {
  const day = dayNumber(tracking);
  const verdict = readTracking(tracking, day);
  const done = todayLogged(tracking);

  useEffect(() => {
    if (isAlert(verdict)) track("intro_alert_shown", { niveau: verdict.level });
  }, [verdict]);

  const toggle = (s: Signal) => {
    // Les trois reponses sur les lesions s'excluent : "moins" et "plus" en
    // meme temps ne veut rien dire.
    const lesion: Signal[] = ["lesions_up", "lesions_same", "lesions_down"];
    if (lesion.includes(s)) {
      setPicked([...picked.filter((x) => !lesion.includes(x)), ...(picked.includes(s) ? [] : [s])]);
      return;
    }
    setPicked(picked.includes(s) ? picked.filter((x) => x !== s) : [...picked, s]);
  };

  return (
    <>
      <View style={styles.head}>
        <View style={styles.dayBlock}>
          <Text style={styles.dayNum}>{day}</Text>
          <Text style={styles.dayWord}>{day > 1 ? "jours" : "jour"}</Text>
        </View>
        <Text style={styles.product} numberOfLines={2}>
          {tracking.brand} · {tracking.name}
        </Text>
      </View>

      <Reveal key={verdict.level} distance={8}>
        <View style={[styles.verdict, isAlert(verdict) && styles.verdictAlert]}>
          <Text style={[styles.verdictTitle, isAlert(verdict) && styles.verdictTitleAlert]}>
            {verdict.title}
          </Text>
          <Text style={styles.verdictBody}>{verdict.body}</Text>
          <Text style={styles.verdictAction}>→ {verdict.action}</Text>
        </View>
      </Reveal>

      {done ? (
        <Text style={styles.foot}>Point du jour enregistré. À demain.</Text>
      ) : (
        <>
          <Text style={styles.question}>Aujourd&apos;hui, votre peau :</Text>
          <View style={styles.chips}>
            {SIGNALS.map((s) => (
              <Chip
                key={s.key}
                testID={`intro-signal-${s.key}`}
                label={s.label}
                on={picked.includes(s.key)}
                onPress={() => toggle(s.key)}
              />
            ))}
          </View>
          <AnimatedPressable
            testID="intro-submit"
            style={[styles.submit, picked.length === 0 && styles.submitOff]}
            disabled={picked.length === 0}
            haptic="medium"
            onPress={async () => {
              await logDay(tracking.id, picked);
              setPicked([]);
              onChange();
            }}
          >
            <Text style={styles.submitText}>Enregistrer</Text>
          </AnimatedPressable>
        </>
      )}

      <AnimatedPressable
        testID="intro-stop"
        style={styles.stop}
        haptic={false}
        onPress={async () => {
          await stopTracking(tracking.id, isAlert(verdict) ? "alert" : "user");
          onChange();
        }}
      >
        <Text style={styles.stopText}>
          {isAlert(verdict) ? "J'ai arrêté ce produit" : "Arrêter le suivi"}
        </Text>
      </AnimatedPressable>
    </>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: spacing.m,
    gap: spacing.s,
  },
  eyebrow: { ...type.kicker, color: colors.accent },
  lede: { ...type.subtitle, color: colors.fg },
  helper: { ...type.bodySmall, color: colors.fgMuted },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.m },
  // Le jour de suivi est LE chiffre de cette carte : il dit ou l'on en est
  // dans la fenetre qui compte. Il etait relegue en petites capitales a
  // droite, ou il ne se lisait pas.
  dayBlock: { flexDirection: "row", alignItems: "baseline", gap: 4 },
  dayNum: {
    fontFamily: fonts.display,
    fontSize: 38,
    lineHeight: 40,
    color: colors.accent,
    fontVariant: ["tabular-nums"],
  },
  dayWord: { ...type.bodySmall, color: colors.fgDim },
  product: { ...type.label, color: colors.fg, flex: 1 },

  verdict: {
    borderLeftWidth: 2,
    borderLeftColor: colors.fgFaint,
    paddingLeft: spacing.m,
    paddingVertical: 2,
    gap: 4,
  },
  verdictAlert: { borderLeftColor: colors.accent },
  verdictTitle: { ...type.label, color: colors.fg },
  verdictTitleAlert: { color: colors.accent },
  verdictBody: { ...type.bodySmall, color: colors.fgMuted },
  verdictAction: { ...type.bodySmall, color: colors.fg },

  question: { ...type.label, color: colors.fg, marginTop: spacing.xs },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s },

  submit: {
    marginTop: spacing.xs,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 14,
    alignItems: "center",
  },
  submitOff: { backgroundColor: colors.fgFaint },
  submitText: { ...type.kicker, color: colors.onAccent },
  stop: { alignSelf: "flex-start", paddingVertical: 12, minHeight: 44, justifyContent: "center" },
  stopText: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
  foot: { ...type.bodySmall, color: colors.fgDim },
});
