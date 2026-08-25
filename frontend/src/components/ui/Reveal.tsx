import { Children, ReactNode, isValidElement, useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { motion } from "@/src/theme";

type Direction = "up" | "down" | "left" | "right" | "none";

type RevealProps = {
  children: ReactNode;
  delay?: number;
  duration?: number;
  distance?: number;
  /** D'ou l'element arrive. "up" = il monte a sa place. */
  from?: Direction;
  /** Legere montee en echelle, pour un element qui doit sembler s'approcher. */
  scale?: boolean;
  style?: StyleProp<ViewStyle>;
};

/**
 * Entree directionnelle : l'element arrive d'ou il vient logiquement.
 * Vers le haut pour une carte qui monte dans la pile, depuis la gauche pour
 * une ligne de liste — le sens porte l'information de hierarchie.
 */
export function Reveal({
  children,
  delay = 0,
  duration = motion.slow,
  distance = 16,
  from = "up",
  scale = false,
  style,
}: RevealProps) {
  const t = useSharedValue(0);
  // Respecte "Reduire les animations" : on coupe le deplacement, pas le contenu.
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withDelay(delay, withTiming(1, { duration, easing: Easing.out(Easing.cubic) }));
  }, [t, delay, duration]);

  const aStyle = useAnimatedStyle(() => {
    const rest = 1 - t.value;
    const shift = reduced ? 0 : rest * distance;
    // Chaque entree de `transform` ne porte qu'une seule cle : RN refuse les
    // objets a cles optionnelles multiples.
    const transform: ({ translateX: number } | { translateY: number } | { scale: number })[] = [];

    if (from === "up") transform.push({ translateY: shift });
    else if (from === "down") transform.push({ translateY: -shift });
    else if (from === "left") transform.push({ translateX: shift });
    else if (from === "right") transform.push({ translateX: -shift });

    if (scale && !reduced) transform.push({ scale: 0.96 + 0.04 * t.value });

    return { opacity: t.value, transform };
  }, [reduced, distance, from, scale]);

  return <Animated.View style={[style, aStyle]}>{children}</Animated.View>;
}

type StaggerProps = {
  children: ReactNode;
  /** Decalage entre deux enfants. */
  step?: number;
  /** Retard avant le premier enfant. */
  delay?: number;
  from?: Direction;
  distance?: number;
  style?: StyleProp<ViewStyle>;
};

/**
 * Enveloppe chaque enfant dans un Reveal decale.
 * Une liste qui apparait d'un bloc ne dit rien ; une liste qui se depose
 * ligne par ligne montre qu'elle a ete construite.
 */
export function Stagger({
  children,
  step = motion.stagger,
  delay = 0,
  from = "up",
  distance = 14,
  style,
}: StaggerProps) {
  const items = Children.toArray(children).filter(isValidElement);
  return (
    <Animated.View style={style}>
      {items.map((child, i) => (
        <Reveal key={child.key ?? i} delay={delay + i * step} from={from} distance={distance}>
          {child}
        </Reveal>
      ))}
    </Animated.View>
  );
}
