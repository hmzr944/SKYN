import { View, Text, StyleSheet } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import { colors, fonts, radius } from "@/src/theme";
import {
  changeTone,
  confidenceDots,
  confidenceLabel,
  directionLabel,
  metricLabel,
} from "@/src/services/skinMemory";
import type { SkinChangeItem } from "@/src/types/skinMemory";

/**
 * La puce Skin Change — composant transversal, utilisé partout où un
 * changement doit s'afficher (Dashboard, What Changed?, Historique/Phase).
 *
 * Deux tonalités seulement, jamais une troisième couleur : "calm" reprend
 * la terre déjà utilisée pour "rien à signaler" dans tout SKYN, "watch"
 * reprend le corail déjà réservé à "demande de l'attention" — voir
 * `changeTone()`. La confiance se lit dans les points, jamais en
 * pourcentage.
 */

function Icon({ shape, color }: { shape: "flat" | "rising" | "watch"; color: string }) {
  if (shape === "flat") {
    return (
      <Svg width={13} height={13} viewBox="0 0 14 14">
        <Path d="M2,7 L12,7" stroke={color} strokeWidth={1.6} strokeLinecap="round" />
      </Svg>
    );
  }
  if (shape === "rising") {
    return (
      <Svg width={13} height={13} viewBox="0 0 14 14">
        <Path
          d="M2,10 L6,6 L9,8 L12,3"
          fill="none"
          stroke={color}
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </Svg>
    );
  }
  return (
    <Svg width={13} height={13} viewBox="0 0 14 14">
      <Path
        d="M2,4 L6,8 L9,6 L12,11"
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function ConfidenceDots({ n, color }: { n: number; color: string }) {
  return (
    <View style={styles.dots}>
      {[0, 1, 2].map((i) => (
        <View
          key={i}
          style={[styles.dot, { backgroundColor: i < n ? color : colors.fgFaint }]}
        />
      ))}
    </View>
  );
}

/** Variante sans donnée : Phase encore en Baseline, rien à comparer. */
export function InsufficientPill({ label }: { label?: string }) {
  return (
    <View style={[styles.pill, styles.insufficient]}>
      <Svg width={13} height={13} viewBox="0 0 14 14">
        <Circle cx={7} cy={7} r={2} fill={colors.fgDim} />
      </Svg>
      <Text style={styles.insufficientText}>{label ?? "Pas encore assez de mesures"}</Text>
    </View>
  );
}

export function SkinChangePill({
  item,
  showMetric = true,
  testID,
}: {
  item: SkinChangeItem;
  /** Prefixe la puce du nom de la métrique ("Texture"). Off dans une liste où le nom est déjà affiché à côté. */
  showMetric?: boolean;
  testID?: string;
}) {
  const tone = changeTone(item.kind, item.direction);
  const isCalm = tone === "calm";
  const color = isCalm ? colors.fg : colors.accent;
  const shape = item.direction === "stable" ? "flat" : isCalm ? "rising" : "watch";

  return (
    <View
      testID={testID}
      style={[styles.pill, isCalm ? styles.calm : styles.watch]}
      accessibilityLabel={`${metricLabel(item)} : ${directionLabel(item)}, ${confidenceLabel(item.confidence)}`}
    >
      <Icon shape={shape} color={color} />
      <Text style={[styles.label, { color }]}>
        {showMetric ? `${metricLabel(item)} · ` : ""}
        {directionLabel(item)}
      </Text>
      <ConfidenceDots n={confidenceDots(item.confidence)} color={color} />
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    alignSelf: "flex-start",
    paddingVertical: 8,
    paddingHorizontal: 13,
    borderRadius: radius.pill,
  },
  calm: { backgroundColor: colors.surfaceSunken },
  watch: { backgroundColor: colors.accentSoft, borderWidth: 1, borderColor: colors.accentLine },
  insufficient: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.borderMid,
  },
  label: { fontFamily: fonts.bodyMedium, fontSize: 12.5 },
  insufficientText: { fontFamily: fonts.bodyMedium, fontSize: 12.5, color: colors.fgDim },
  dots: { flexDirection: "row", gap: 3, marginLeft: 2 },
  dot: { width: 4, height: 4, borderRadius: 2 },
});
