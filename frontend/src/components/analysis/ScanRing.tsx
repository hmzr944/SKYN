import { useEffect } from "react";
import Animated, {
  useAnimatedProps,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import { Line } from "react-native-svg";

import { colors, motion } from "@/src/theme";

const AnimatedLine = Animated.createAnimatedComponent(Line);

/**
 * La couronne de traits, façon enregistrement Face ID.
 *
 * Chaque trait represente une direction de rotation. Ils s'allument a mesure
 * que la tete balaie l'amplitude, et le geste devient evident sans qu'on ait
 * a l'expliquer : il faut completer le cercle.
 *
 * C'est nettement plus lisible qu'une jauge lineaire — une jauge dit COMBIEN
 * il reste, une couronne dit AUSSI dans quelle direction aller.
 */

/** Assez de traits pour lire une progression continue, pas assez pour moutonner. */
const TICKS = 36;

function Tick({
  index,
  total,
  cx,
  cy,
  rInner,
  rOuter,
  lit,
}: {
  index: number;
  total: number;
  cx: number;
  cy: number;
  rInner: number;
  rOuter: number;
  lit: boolean;
}) {
  // On part du haut et on tourne : c'est le sens de lecture d'un cadran.
  const angle = (index / total) * Math.PI * 2 - Math.PI / 2;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);

  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withSpring(lit ? 1 : 0, motion.spring);
  }, [lit, t]);

  const props = useAnimatedProps(() => {
    // Un trait allume s'allonge vers l'exterieur : le relief se voit meme du
    // coin de l'oeil, pendant qu'on regarde son propre visage.
    const grow = rOuter + t.value * (rOuter - rInner) * 0.55;
    return {
      x2: cx + cos * grow,
      y2: cy + sin * grow,
      opacity: 0.18 + t.value * 0.82,
    };
  });

  return (
    <AnimatedLine
      x1={cx + cos * rInner}
      y1={cy + sin * rInner}
      stroke={lit ? colors.accent : colors.fg}
      strokeWidth={2}
      strokeLinecap="round"
      animatedProps={props}
    />
  );
}

export function ScanRing({
  cx,
  cy,
  radius,
  progress,
}: {
  cx: number;
  cy: number;
  radius: number;
  /** Part de l'amplitude couverte, entre 0 et 1. */
  progress: number;
}) {
  const rInner = radius;
  const rOuter = radius + Math.max(8, radius * 0.06);
  // Les traits s'allument des deux cotes a partir du haut, comme un cercle
  // qu'on referme — c'est la lecture que donne Face ID.
  const litCount = Math.round(progress * TICKS);

  return (
    <>
      {Array.from({ length: TICKS }).map((_, i) => {
        // Distance au sommet, dans les deux sens : le remplissage est
        // symetrique, il ne privilegie pas un cote.
        const fromTop = Math.min(i, TICKS - i);
        return (
          <Tick
            key={i}
            index={i}
            total={TICKS}
            cx={cx}
            cy={cy}
            rInner={rInner}
            rOuter={rOuter}
            lit={fromTop * 2 < litCount}
          />
        );
      })}
    </>
  );
}
