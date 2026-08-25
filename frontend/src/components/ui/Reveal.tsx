import { Children, ReactNode, isValidElement, useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
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
    t.value = withDelay(delay, withTiming(1, { duration, easing: ease.out }));
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
  /** Ecart entre deux voisins, en millisecondes. */
  step?: number;
  /**
   * Duree TOTALE du decalage, repartie sur l'ensemble.
   *
   * A preferer a `step` des que le nombre d'elements varie : une liste de
   * trois et une liste de douze prennent alors le meme temps a se deposer.
   * Avec `step`, la seconde durerait quatre fois plus longtemps et
   * l'utilisateur attendrait devant un ecran qui se remplit encore.
   */
  amount?: number;
  /** Retard avant le premier enfant. */
  delay?: number;
  /**
   * D'ou part la propagation.
   *
   * Ce n'est pas decoratif : une liste qui s'ouvre depuis son centre se lit
   * comme un depliage, depuis ses bords comme une convergence, depuis la fin
   * comme un retour en arriere. Le sens porte une information que l'ordre
   * seul ne porte pas.
   */
  from?: StaggerFrom;
  direction?: Direction;
  distance?: number;
  style?: StyleProp<ViewStyle>;
};

export type StaggerFrom = "start" | "end" | "center" | "edges" | "random";

/** Rang de propagation de chaque element, en nombre de pas. */
function ordre(n: number, from: StaggerFrom): number[] {
  const r = new Array(n).fill(0);
  switch (from) {
    case "end":
      for (let i = 0; i < n; i++) r[i] = n - 1 - i;
      break;
    case "center": {
      const c = (n - 1) / 2;
      for (let i = 0; i < n; i++) r[i] = Math.abs(i - c);
      break;
    }
    case "edges": {
      const c = (n - 1) / 2;
      for (let i = 0; i < n; i++) r[i] = c - Math.abs(i - c);
      break;
    }
    case "random": {
      const m = [...Array(n).keys()];
      for (let i = n - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [m[i], m[j]] = [m[j], m[i]];
      }
      for (let i = 0; i < n; i++) r[i] = m[i];
      break;
    }
    default:
      for (let i = 0; i < n; i++) r[i] = i;
  }
  return r;
}

/**
 * Enveloppe chaque enfant dans un Reveal decale.
 *
 * Une liste qui apparait d'un bloc ne dit rien ; une liste qui se depose
 * ligne par ligne montre qu'elle a ete construite.
 */
export function Stagger({
  children,
  step = motion.stagger,
  amount,
  delay = 0,
  from = "start",
  direction = "up",
  distance = 14,
  style,
}: StaggerProps) {
  const items = Children.toArray(children).filter(isValidElement);
  const n = items.length;
  const rangs = ordre(n, from);
  const pas = amount !== undefined ? (n > 1 ? amount / (n - 1) : 0) : step;

  return (
    <Animated.View style={style}>
      {items.map((child, i) => (
        <Reveal
          key={child.key ?? i}
          delay={delay + rangs[i] * pas}
          from={direction}
          distance={distance}
        >
          {child}
        </Reveal>
      ))}
    </Animated.View>
  );
}
