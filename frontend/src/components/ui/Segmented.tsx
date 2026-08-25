import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  interpolateColor,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { colors, fonts, motion, radius, spacing } from "@/src/theme";

export type SegmentOption<T extends string | number> = { value: T; label: string };

/**
 * Un selecteur ou le fond GLISSE d'un segment a l'autre.
 *
 * Le changement d'etat etait instantane : un fond disparaissait ici,
 * reapparaissait la, et rien ne reliait les deux. C'est le defaut le plus
 * courant d'une interface — chaque etat est correct, aucun passage n'est
 * dessine, et l'ensemble parait mort meme quand tout fonctionne.
 *
 * Le fond est unique et il parcourt la distance. Le libelle, lui, ne bascule
 * pas d'un coup : sa couleur se croise avec celle du fond qui arrive.
 *
 * La piste est MESUREE puis divisee en parts egales : «7 j» et «3 mois» n'ont
 * pas la meme largeur naturelle, et des segments inegaux obligeraient a animer
 * la largeur de l'indicateur en plus de sa position.
 */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  testIDPrefix,
  style,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  testIDPrefix?: string;
  style?: object;
}) {
  /**
   * Largeur utile de la piste.
   *
   * Les segments se partagent cette largeur A PARTS EGALES, par `flex`, et
   * non par une largeur qu'on leur imposerait. Deux versions ont echoue avant
   * celle-ci, et pour deux raisons differentes :
   *
   *   · animer la LARGEUR de l'indicateur pour suivre des segments inegaux —
   *     sur le web, une propriete de mise en page ne s'anime pas, et
   *     l'indicateur restait a la taille du segment precedent ;
   *   · imposer une largeur calculee a chaque segment — la piste se
   *     redimensionnait alors en retour, ce qui relançait la mesure, en
   *     boucle sans fin.
   *
   * Avec `flex`, la piste tient sa largeur de son parent et la mesure ne sert
   * plus qu'a placer l'indicateur : plus rien ne revient en arriere.
   */
  const [piste, setPiste] = useState(0);
  const n = options.length;
  const largeur = piste > 0 ? piste / n : 0;

  const x = useSharedValue(0);
  const ready = useSharedValue(0);
  const reduced = useReducedMotion();

  const index = Math.max(0, options.findIndex((o) => o.value === value));

  useEffect(() => {
    if (!largeur) return;
    const cible = index * largeur;
    if (ready.value === 0) {
      // Premiere mesure : l'indicateur se pose la, il ne traverse pas la piste.
      x.value = cible;
      ready.value = withTiming(1, { duration: motion.fast });
    } else if (reduced) {
      x.value = withTiming(cible, { duration: motion.instant });
    } else {
      x.value = withSpring(cible, motion.spring);
    }
  }, [index, largeur, x, ready, reduced]);

  const indicateur = useAnimatedStyle(() => ({
    opacity: ready.value,
    transform: [{ translateX: x.value }],
  }));

  return (
    <View
      style={[styles.track, style]}
      onLayout={(e) => {
        // Largeur INTERIEURE : le rembourrage de la piste n'appartient a aucun
        // segment.
        const w = Math.floor(e.nativeEvent.layout.width) - PAD * 2;
        setPiste((prev) => (Math.abs(prev - w) < 1 ? prev : w));
      }}
    >
      {largeur > 0 ? (
        <Animated.View
          style={[styles.indicator, { width: largeur }, indicateur]}
          pointerEvents="none"
        />
      ) : null}
      {options.map((o) => (
        <Item
          key={String(o.value)}
          option={o}
          actif={o.value === value}
          onPress={() => onChange(o.value)}
          testID={testIDPrefix ? `${testIDPrefix}-${o.value}` : undefined}
        />
      ))}
    </View>
  );
}

function Item<T extends string | number>({
  option,
  actif,
  onPress,
  testID,
}: {
  option: SegmentOption<T>;
  actif: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const t = useSharedValue(actif ? 1 : 0);

  useEffect(() => {
    t.value = withTiming(actif ? 1 : 0, { duration: motion.base });
  }, [actif, t]);

  const texte = useAnimatedStyle(() => ({
    color: interpolateColor(t.value, [0, 1], [colors.fgMuted, colors.onInverse]),
  }));

  return (
    <AnimatedPressable
      testID={testID}
      onPress={onPress}
      containerStyle={styles.itemBox}
      style={styles.item}
      scaleTo={0.96}
      haptic={false}
      accessibilityState={{ selected: actif }}
      accessibilityLabel={option.label}
    >
      <Animated.Text style={[styles.label, texte]} numberOfLines={1}>
        {option.label}
      </Animated.Text>
    </AnimatedPressable>
  );
}

const PAD = 3;

const styles = StyleSheet.create({
  track: {
    flexDirection: "row",
    // La piste prend la largeur qu'on lui donne : celle du parent par defaut,
    // ou celle passee en style. Elle ne se dimensionne jamais sur son contenu,
    // sans quoi la mesure et la mise en page se poursuivraient l'une l'autre.
    alignSelf: "stretch",
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.pill,
    padding: PAD,
  },
  indicator: {
    position: "absolute",
    top: PAD,
    bottom: PAD,
    left: PAD,
    borderRadius: radius.pill,
    backgroundColor: colors.fg,
  },
  // La boite participe a la mise en page ; le dessin, lui, vit a l'interieur.
  itemBox: { flex: 1 },
  item: {
    minHeight: 44,
    paddingHorizontal: spacing.s,
    alignItems: "center",
    justifyContent: "center",
  },
  label: { fontFamily: fonts.bodyMedium, fontSize: 12.5 },
});
