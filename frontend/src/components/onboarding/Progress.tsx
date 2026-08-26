import { StyleSheet, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useDerivedValue,
  useReducedMotion,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { colors, palette } from "@/src/theme";

/**
 * La progression, en segments, tout en haut.
 *
 * Les points ronds disaient « il y a cinq ecrans ». Des segments disent
 * « voila ce qui est derriere toi ». La difference compte au moment ou
 * quelqu'un se demande combien de temps ca va encore durer.
 *
 * Chaque segment se remplit par une mise a l'echelle depuis sa gauche, jamais
 * par une largeur : une largeur qui s'anime declenche une remise en page a
 * chaque image, et la barre saccade sur les telephones lents.
 */
function Segment({ rempli, onDark }: { rempli: boolean; onDark: boolean }) {
  const reduced = useReducedMotion();
  const t = useDerivedValue(() =>
    withTiming(rempli ? 1 : 0, { duration: reduced ? 0 : 420, easing: ease.out }),
  );

  const fill = useAnimatedStyle(() => ({
    transform: [{ scaleX: t.value }],
  }));

  return (
    <View
      style={[
        styles.rail,
        { backgroundColor: onDark ? "rgba(255,246,240,0.28)" : colors.fgFaint },
      ]}
    >
      <Animated.View
        style={[
          styles.fill,
          { backgroundColor: onDark ? palette.creme : colors.accent },
          fill,
        ]}
      />
    </View>
  );
}

export function Progress({
  count,
  page,
  onDark = false,
}: {
  count: number;
  page: number;
  onDark?: boolean;
}) {
  return (
    <View
      style={styles.row}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 1, max: count, now: page + 1 }}
      accessibilityLabel={`Étape ${page + 1} sur ${count}`}
      // `accessibilityValue` ne descend pas jusqu'aux attributs ARIA sur le
      // web : mesure faite, `aria-valuenow` restait vide et la barre
      // n'annoncait aucune position. Les trois attributs sont donc poses a la
      // main, en plus, pour que les trois plateformes disent la meme chose.
      aria-valuemin={1}
      aria-valuemax={count}
      aria-valuenow={page + 1}
    >
      {Array.from({ length: count }).map((_, i) => (
        <Segment key={i} rempli={i <= page} onDark={onDark} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 5, flex: 1 },
  rail: { flex: 1, height: 2, borderRadius: 1, overflow: "hidden" },
  // L'echelle part du bord gauche, pas du centre : le segment se remplit dans
  // le sens de la lecture.
  fill: { width: "100%", height: "100%", borderRadius: 1, transformOrigin: "left" },
});
