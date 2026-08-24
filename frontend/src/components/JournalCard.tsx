import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
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
      <Text style={styles.helper}>
        {"Ce qui s'est passé aujourd'hui. Une lésion met plusieurs jours à sortir : " +
          "c'est en notant régulièrement qu'on voit ce qui revient."}
      </Text>

      <View style={styles.grid}>
        {FACTORS.map((f) => {
          const on = entry[f.key] === 1;
          return (
            <AnimatedPressable
              key={f.key}
              testID={`journal-${f.key}`}
              style={[styles.chip, on && styles.chipOn]}
              scaleTo={0.94}
              onPress={() => onToggle(f.key)}
            >
              <Text style={[styles.chipText, on && styles.chipTextOn]}>{f.label}</Text>
            </AnimatedPressable>
          );
        })}
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
      ) : (
        <Text style={styles.progress}>
          {days >= MIN_DAYS
            ? "Pas encore d'écart net entre vos journées."
            : `${days}/${MIN_DAYS} jours notés avant les premières observations.`}
        </Text>
      )}
    </View>
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
  helper: { ...type.bodySmall, color: colors.fgMuted },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.s, marginTop: spacing.xs },
  chip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: 9,
    paddingHorizontal: spacing.m,
  },
  chipOn: { backgroundColor: colors.fg, borderColor: colors.fg },
  chipText: { ...type.label, color: colors.fgMuted },
  chipTextOn: { color: colors.onInverse },
  progress: { ...type.bodySmall, color: colors.fgDim, marginTop: spacing.xs },
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
