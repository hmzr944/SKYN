import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { Chip } from "@/src/components/ui/Chip";
import { Disclosure } from "@/src/components/ui/Disclosure";
import { Reveal } from "@/src/components/ui/Reveal";
import {
  FACTORS,
  loggedDays,
  MIN_DAYS,
  observations,
  toggleFactor,
  type DayEntry,
  type FactorKey,
  type Observation,
} from "@/src/services/journal";
import { getDay } from "@/src/services/journal";
import { colors, radius, spacing, type } from "@/src/theme";

/**
 * Le journal du jour.
 *
 * Six facteurs, un appui chacun. C'est volontairement pauvre : un formulaire
 * long ne serait pas rempli, et un journal a moitie rempli ne vaut rien.
 *
 * Les observations n'apparaissent qu'une fois assez de jours consignes, et
 * elles decrivent une coincidence — jamais une cause.
 */
export function JournalCard() {
  const [entry, setEntry] = useState<DayEntry>({});
  const [days, setDays] = useState(0);
  const [obs, setObs] = useState<Observation[]>([]);

  const refresh = useCallback(async () => {
    const [e, d, o] = await Promise.all([getDay(), loggedDays(), observations()]);
    setEntry(e);
    setDays(d);
    setObs(o);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onToggle = async (key: FactorKey) => {
    setEntry(await toggleFactor(key));
    // Les observations ne bougent qu'au fil des jours : on les recalcule sans
    // bloquer l'appui.
    loggedDays().then(setDays);
    observations().then(setObs);
  };

  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>Journal du jour</Text>
      <Text style={styles.question}>Votre journée, en un appui.</Text>

      <View style={styles.grid}>
        {FACTORS.map((f) => (
          <Chip
            key={f.key}
            testID={`journal-${f.key}`}
            label={f.label}
            on={entry[f.key] === 1}
            onPress={() => onToggle(f.key)}
          />
        ))}
      </View>

      {obs.length > 0 ? (
        <View style={styles.obsWrap}>
          {obs.map((o, i) => (
            <Reveal key={o.factor} delay={i * 70} distance={8}>
              <View style={styles.obs}>
                <Text style={styles.obsTitle}>
                  {o.label} · {o.gap} points d&apos;écart
                </Text>
                <Text style={styles.obsBody}>
                  Vos scans précédés de cette période notent en moyenne {o.gap} points de
                  moins. {o.note}
                </Text>
                <Text style={styles.obsCaveat}>
                  Constat sur {o.sample} analyses, pas une cause démontrée.
                </Text>
              </View>
            </Reveal>
          ))}
        </View>
      ) : days >= MIN_DAYS ? (
        <Text style={styles.progress}>Pas encore d&apos;écart net entre vos journées.</Text>
      ) : (
        <View style={styles.progressWrap}>
          <DayTrack done={days} total={MIN_DAYS} />
          <Text style={styles.progress}>
            {`Encore ${MIN_DAYS - days} ${MIN_DAYS - days > 1 ? "jours" : "jour"} avant les premières observations.`}
          </Text>
        </View>
      )}

      <Disclosure testID="journal-why">
        <Text style={styles.helper}>
          {"Une lésion met plusieurs jours à sortir : ce qui l'a déclenchée est " +
            "déjà loin quand elle apparaît. C'est pour ça qu'on note au jour le " +
            "jour, et qu'il faut plusieurs semaines avant que quoi que ce soit " +
            "se dégage."}
        </Text>
      </Disclosure>
    </View>
  );
}

/**
 * Les jours notes, un segment chacun.
 *
 * "3/12 jours notés" est un fait ; douze segments dont trois sont pleins est
 * une distance. On voit d'un coup d'oeil ce qui est fait et ce qui reste, et
 * le segment du jour se remplit sous les yeux au lieu d'incrementer un
 * compteur.
 */
function DayTrack({ done, total }: { done: number; total: number }) {
  return (
    <View style={styles.track}>
      {Array.from({ length: total }).map((_, i) => (
        <Segment key={i} filled={i < done} index={i} />
      ))}
    </View>
  );
}

function Segment({ filled, index }: { filled: boolean; index: number }) {
  const t = useSharedValue(0);
  useEffect(() => {
    // Les segments se remplissent de gauche a droite : la serie se relit, elle
    // n'apparait pas d'un bloc.
    t.value = withDelay(
      index * 45,
      withTiming(filled ? 1 : 0, { duration: 320, easing: ease.out }),
    );
  }, [filled, index, t]);

  const aStyle = useAnimatedStyle(() => ({
    transform: [{ scaleX: t.value }],
  }));

  return (
    <View style={styles.segTrack}>
      <Animated.View style={[styles.segFill, aStyle]} />
    </View>
  );
}

const styles = StyleSheet.create({
  // Pas de carte ici, volontairement.
  //
  // Le journal et le suivi d'introduction se suivaient dans la page avec le
  // meme cadre, le meme filet, le meme surtitre corail : deux blocs de la meme
  // silhouette, et l'oeil ne distinguait plus l'un de l'autre. Le journal est
  // une habitude quotidienne, pas un dossier ouvert — il se pose sur la page.
  card: { paddingVertical: spacing.s, paddingHorizontal: spacing.m, gap: spacing.s },
  eyebrow: { ...type.kicker, color: colors.accent },
  question: { ...type.subtitle, color: colors.fg },
  helper: { ...type.bodySmall, color: colors.fgMuted },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s, marginTop: spacing.xs },
  progressWrap: { gap: spacing.s, marginTop: spacing.xs },
  progress: { ...type.bodySmall, color: colors.fgDim },
  track: { flexDirection: "row", gap: 4 },
  segTrack: {
    flex: 1,
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.fgFaint,
    overflow: "hidden",
  },
  segFill: {
    width: "100%",
    height: "100%",
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    transformOrigin: "left",
  },
  obsWrap: { gap: spacing.s, marginTop: spacing.s },
  obs: {
    borderLeftWidth: 2,
    borderLeftColor: colors.accent,
    paddingLeft: spacing.m,
    gap: 3,
  },
  obsTitle: { ...type.label, color: colors.fg },
  obsBody: { ...type.bodySmall, color: colors.fgMuted },
  obsCaveat: { ...type.bodySmall, fontSize: 11, color: colors.fgDim },
});
