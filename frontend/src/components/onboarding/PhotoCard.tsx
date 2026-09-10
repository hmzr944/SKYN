import { useEffect } from "react";
import { Image, ImageSourcePropType, StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { motion, radius, spacing } from "@/src/theme";
import { onboardingPalette } from "@/src/theme/onboardingPalette";

/**
 * La carte photo d'une page d'onboarding (hors la premiere, en grille bento).
 *
 * Un rectangle a coins arrondis, jamais un rond — chaque page porte SA
 * propre photo, chacune racontant le sujet de la page plutot qu'une matiere
 * abstraite reprise partout. Meme ressort d'arrivee que BentoGrid, meme
 * derive lente en continu (Ken Burns) : le vocabulaire de mouvement reste un
 * seul, pas un par ecran.
 */
export function PhotoCard({
  source,
  height,
  delay = 0,
}: {
  source: ImageSourcePropType;
  height: number;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  const t = useSharedValue(0);
  const s = useSharedValue(1);

  useEffect(() => {
    if (reduced) {
      t.value = 1;
      return;
    }
    t.value = withDelay(delay, withSpring(1, motion.springDrop));
    s.value = withRepeat(
      withTiming(1.08, { duration: 9000, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [delay, reduced, t, s]);

  const cardStyle = useAnimatedStyle(() => ({
    opacity: Math.min(1, t.value),
    transform: [
      { scale: 0.9 + Math.min(1, t.value) * 0.1 },
      { translateY: (1 - Math.min(1, t.value)) * 16 },
    ],
  }));
  const kenBurnsStyle = useAnimatedStyle(() => ({ transform: [{ scale: s.value }] }));

  return (
    <Animated.View style={[styles.card, { height }, cardStyle]}>
      <Animated.View style={[StyleSheet.absoluteFill, kenBurnsStyle]}>
        <Image source={source} style={styles.photo} resizeMode="cover" />
      </Animated.View>
      <View style={styles.rim} pointerEvents="none" />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: "100%",
    // Meme respiration que `bentoLayer` sur la page hero (voir onboarding.tsx) :
    // sans elle, le kicker de la page collait directement sous la photo, la
    // seule page a ne pas avoir cet espace.
    marginBottom: spacing.l,
    borderRadius: radius.xl,
    overflow: "hidden",
    backgroundColor: onboardingPalette.sable,
  },
  photo: { width: "100%", height: "100%" },
  // Un filet tres doux sur le bord : la photo se detache mieux du fond creme
  // sans passer par une ombre portee, plus lourde a ce format.
  rim: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: "rgba(0,0,0,0.06)",
  },
});
