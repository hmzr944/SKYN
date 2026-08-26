import { MotiView } from "moti";
import Svg, { Circle, Path } from "react-native-svg";
import Animated, {
  useAnimatedProps,
  useDerivedValue,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";

import { duration, spring } from "@/src/animation/motion";
import { ease } from "@/src/animation/ease";
import { colors, palette } from "@/src/theme";
import { MARK_DOT, MARK_LENGTH, MARK_PATH, MARK_VIEWBOX, markMetrics } from "@/src/theme/mark";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/**
 * La marque s'assemble.
 *
 * Le point arrive au ressort, puis le S se deroule A PARTIR de lui — le trace
 * commence exactement au terminus dont le point est le prolongement.
 *
 * ────────────────────────────────────────────────────────────────────────
 * DEUX MOTEURS DANS UN MEME COMPOSANT, ET C'EST VOULU.
 *
 * L'enveloppe est un `MotiView` : echelle et opacite sont des proprietes de
 * vue, et le modele declaratif du skill (`from` / `animate` / `transition`)
 * les decrit mieux que trois valeurs partagees ecrites a la main.
 *
 * L'interieur reste en valeurs partagees, parce qu'il n'anime pas une vue mais
 * des ATTRIBUTS SVG — un decalage de pointilles et un rayon. Moti ne les
 * atteint pas ; il faut passer par `useAnimatedProps`. Melanger les deux n'est
 * pas une inconsequence : chacun couvre ce que l'autre ne sait pas faire.
 * ────────────────────────────────────────────────────────────────────────
 */
export function MarkAssembly({
  size = 96,
  delay = 0,
  onDark = false,
  style,
}: {
  size?: number;
  /** Retard avant le debut de l'assemblage, en millisecondes. */
  delay?: number;
  onDark?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { stroke, dot } = markMetrics(size);
  const reduced = useReducedMotion();

  const drop = useSharedValue(0);
  const draw = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      // Le mouvement est coupe, pas le contenu : la marque se pose entiere.
      drop.value = 1;
      draw.value = 1;
      return;
    }
    drop.value = withDelay(delay, withSpring(1, { damping: 10, stiffness: 200, mass: 1 }));
    draw.value = withDelay(
      delay + 140,
      withTiming(1, { duration: duration.draw, easing: ease.expoOut }),
    );
  }, [delay, reduced, drop, draw]);

  // Le point s'ecrase legerement a l'impact et reprend sa forme : une masse
  // qui se pose ne s'arrete pas net.
  const impact = useDerivedValue(() => Math.max(0, 1 - Math.abs(1 - drop.value) * 3));

  const dotProps = useAnimatedProps(() => ({
    r: dot * drop.value,
  }));

  const drawProps = useAnimatedProps(() => ({
    strokeDashoffset: MARK_LENGTH * (1 - draw.value),
    opacity: draw.value > 0 ? 1 : 0,
  }));

  const halo = useAnimatedProps(() => ({
    r: dot * (1 + impact.value * 1.6),
    opacity: impact.value > 0 && impact.value < 1 ? 0.35 * (1 - impact.value) : 0,
  }));

  return (
    <MotiView
      from={{ opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={reduced ? { type: "timing", duration: 0 } : { ...spring.gentle, delay }}
      style={style}
    >
      <Svg width={size} height={size} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}>
        <AnimatedPath
          d={MARK_PATH}
          fill="none"
          stroke={onDark ? palette.creme : palette.terre}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={MARK_LENGTH}
          animatedProps={drawProps}
        />
        {/* L'onde de l'impact : elle n'existe qu'entre les deux bornes. */}
        <AnimatedCircle
          cx={MARK_DOT.x}
          cy={MARK_DOT.y}
          fill="none"
          stroke={colors.accent}
          strokeWidth={1.4}
          animatedProps={halo}
        />
        <AnimatedCircle
          cx={MARK_DOT.x}
          cy={MARK_DOT.y}
          fill={colors.accent}
          animatedProps={dotProps}
        />
      </Svg>
    </MotiView>
  );
}
