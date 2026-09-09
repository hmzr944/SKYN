import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  interpolate,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { colors } from "@/src/theme";

/**
 * Un fond qui respire, pas un decor.
 *
 * Deux masses tres douces de terre-sur-creme derivent lentement derriere le
 * contenu — jamais de corail ici : le corail signale une zone qui demande de
 * l'attention (voir theme/index.ts), et l'utiliser en fond l'aurait dilue en
 * simple couleur d'ambiance. La "couleur" demandee vient donc d'un jeu
 * d'opacites de terre, exactement comme le reste du systeme (colors.surface,
 * colors.fgMuted, etc.) — jamais une teinte hors palette.
 *
 * Reserve aux ecrans "vitrine" (accueil, carte de peau) : partout ailleurs,
 * un fond qui bouge sous du texte qu'on lit activement distrairait plus
 * qu'il n'accueillerait.
 */
export function AmbientBackground() {
  const reduced = useReducedMotion();
  const t1 = useSharedValue(0);
  const t2 = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    t1.value = withRepeat(withTiming(1, { duration: 16000, easing: Easing.inOut(Easing.sin) }), -1, true);
    t2.value = withRepeat(withTiming(1, { duration: 21000, easing: Easing.inOut(Easing.sin) }), -1, true);
  }, [reduced, t1, t2]);

  const blobA = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(t1.value, [0, 1], [-26, 22]) },
      { translateY: interpolate(t1.value, [0, 1], [-18, 34]) },
    ],
  }));
  const blobB = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(t2.value, [0, 1], [18, -30]) },
      { translateY: interpolate(t2.value, [0, 1], [24, -14]) },
    ],
  }));

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Animated.View style={[styles.blob, styles.blobA, blobA]} />
      <Animated.View style={[styles.blob, styles.blobB, blobB]} />
    </View>
  );
}

const styles = StyleSheet.create({
  blob: {
    position: "absolute",
    borderRadius: 999,
    backgroundColor: colors.fg,
  },
  blobA: {
    top: -80,
    left: -60,
    width: 320,
    height: 320,
    opacity: 0.035,
  },
  blobB: {
    bottom: -100,
    right: -80,
    width: 380,
    height: 380,
    opacity: 0.03,
  },
});
