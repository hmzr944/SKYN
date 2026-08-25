import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { colors, motion, palette } from "@/src/theme";
import { MARK_DOT, MARK_LENGTH, MARK_PATH, MARK_VIEWBOX, markMetrics } from "@/src/theme/mark";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

type Props = {
  size?: number;
  /** Sur le bloc terre, le trait passe en creme. Le corail ne change jamais. */
  onDark?: boolean;
  /** Rejoue le trace. Change la valeur pour relancer. */
  playKey?: number;
  style?: StyleProp<ViewStyle>;
};

/**
 * Le S de SKYN, anime.
 *
 * Le point corail se pose d'abord, puis le S se deroule A PARTIR de lui : le
 * trace commence exactement au terminus superieur, celui dont le point est le
 * prolongement. La lettre n'apparait pas, elle est lancee.
 *
 * La sequence ne boucle jamais. Une signature ne se repete pas.
 */
export function SkynMark({ size = 64, onDark, playKey = 0, style }: Props) {
  const { stroke, dot } = markMetrics(size);
  const strokeColor = onDark ? palette.creme : palette.terre;

  const drop = useSharedValue(0);
  const draw = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      // Le mouvement est coupe, pas le contenu : la marque se pose entiere.
      drop.value = 1;
      draw.value = 1;
      return;
    }
    drop.value = 0;
    draw.value = 0;
    drop.value = withSpring(1, motion.springDrop);
    draw.value = withDelay(
      210,
      withTiming(1, { duration: motion.sweep, easing: Easing.bezier(0.33, 1, 0.68, 1) }),
    );
  }, [playKey, reduced, drop, draw]);

  const dotProps = useAnimatedProps(() => ({ r: dot * drop.value }));

  const drawProps = useAnimatedProps(() => ({
    strokeDashoffset: MARK_LENGTH * (1 - draw.value),
    opacity: draw.value > 0 ? 1 : 0,
  }));

  return (
    <Svg width={size} height={size} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`} style={style}>
      <AnimatedPath
        d={MARK_PATH}
        fill="none"
        stroke={strokeColor}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={MARK_LENGTH}
        animatedProps={drawProps}
      />
      <AnimatedCircle
        cx={MARK_DOT.x}
        cy={MARK_DOT.y}
        fill={colors.accent}
        animatedProps={dotProps}
      />
    </Svg>
  );
}

/** Version figee, sans hooks d'animation — pour les onglets, les listes, les en-tetes. */
export function SkynMarkStill({
  size = 24,
  onDark,
  style,
}: {
  size?: number;
  onDark?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { stroke, dot } = markMetrics(size);
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`} style={style}>
      <Path
        d={MARK_PATH}
        fill="none"
        stroke={onDark ? palette.creme : palette.terre}
        strokeWidth={stroke}
        strokeLinecap="round"
      />
      <Circle cx={MARK_DOT.x} cy={MARK_DOT.y} r={dot} fill={colors.accent} />
    </Svg>
  );
}
