import { useEffect } from "react";
import { StyleSheet } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import Svg, { Defs, RadialGradient, Stop, Ellipse } from "react-native-svg";

import { colors } from "@/src/theme";

/**
 * Le Halo d'Évolution — accent secondaire du langage "Living Skin", posé à
 * côté de la carte (jamais à sa place, voir la recommandation du deck). Il
 * ne représente rien de plus que la confiance globale de la Phase : une
 * respiration lente et régulière quand la mesure est posée, plus vive quand
 * une variation demande de l'attention. Pas d'icône, pas de texte — un objet
 * ambiant, pas un indicateur qu'on lit.
 */
export function PhaseHalo({
  tone = "calm",
  size = 96,
}: {
  tone?: "calm" | "watch";
  size?: number;
}) {
  const breathe = useSharedValue(0);

  useEffect(() => {
    // Le corail respire plus vite : c'est ce qui distingue "à surveiller" de
    // "rien à signaler" ici, jamais une nouvelle couleur.
    const duration = tone === "watch" ? 2200 : 4200;
    breathe.value = withRepeat(
      withSequence(
        withTiming(1, { duration, easing: Easing.inOut(Easing.sin) }),
        withTiming(0, { duration, easing: Easing.inOut(Easing.sin) }),
      ),
      -1,
      false,
    );
  }, [tone, breathe]);

  const style = useAnimatedStyle(() => ({
    transform: [
      { scale: 1 + breathe.value * 0.06 },
      { rotate: `${breathe.value * (tone === "watch" ? 5 : 3)}deg` },
    ],
  }));

  const stops =
    tone === "watch"
      ? { from: colors.accent, to: "#8C3D42" }
      : { from: "#8A6255", to: colors.fg };

  return (
    <Animated.View style={[styles.wrap, { width: size, height: size }, style]}>
      <Svg width={size} height={size} viewBox="0 0 100 100">
        <Defs>
          <RadialGradient id="halo" cx="36%" cy="30%">
            <Stop offset="0%" stopColor={stops.from} />
            <Stop offset="100%" stopColor={stops.to} />
          </RadialGradient>
        </Defs>
        <Ellipse cx={50} cy={50} rx={46} ry={44} fill="url(#halo)" />
      </Svg>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center" },
});
