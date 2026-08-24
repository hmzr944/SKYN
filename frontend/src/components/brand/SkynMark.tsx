import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { colors, motion, palette } from "@/src/theme";
import { FACE_LENGTH, FACE_PATH, MARK_DOT, MARK_VIEWBOX, markMetrics } from "@/src/theme/mark";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

type Props = {
  size?: number;
  /** Sur le bloc terre, le contour passe en creme. Le corail ne change jamais. */
  onDark?: boolean;
  /** Rejoue le balayage. Change la valeur pour relancer. */
  playKey?: number;
  style?: StyleProp<ViewStyle>;
};

/**
 * Le symbole SKYN, anime.
 *
 * Le trace balaie le contour d'un visage et s'arrete avant d'avoir referme ;
 * le point corail se pose alors dans la breche, et une onde unique part de lui.
 * C'est la sequence du produit en trois temps : il balaie, il trouve, il
 * signale. Elle ne boucle jamais — une conclusion ne se repete pas.
 */
export function SkynMark({ size = 64, onDark, playKey = 0, style }: Props) {
  const { stroke, dot } = markMetrics(size);
  const strokeColor = onDark ? palette.creme : palette.terre;

  const sweep = useSharedValue(0);
  const drop = useSharedValue(0);
  const halo = useSharedValue(0);

  useEffect(() => {
    sweep.value = 0;
    drop.value = 0;
    halo.value = 0;

    sweep.value = withTiming(1, {
      duration: motion.sweep,
      easing: Easing.bezier(0.33, 1, 0.68, 1),
    });
    // Le point se pose juste avant que le balayage se referme.
    drop.value = withDelay(880, withSpring(1, motion.springDrop));
    halo.value = withDelay(1080, withTiming(1, { duration: 760, easing: Easing.out(Easing.quad) }));
  }, [playKey, sweep, drop, halo]);

  const sweepProps = useAnimatedProps(() => ({
    strokeDashoffset: FACE_LENGTH * (1 - sweep.value),
  }));

  const dotProps = useAnimatedProps(() => ({ r: dot * drop.value }));

  const haloProps = useAnimatedProps(() => ({
    r: dot * (1 + halo.value * 1.9),
    // L'onde s'eteint en s'ecartant : elle n'existe qu'entre 0 et 1.
    opacity: halo.value === 0 || halo.value === 1 ? 0 : 0.55 * (1 - halo.value),
  }));

  return (
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      style={style}
    >
      <AnimatedPath
        d={FACE_PATH}
        fill="none"
        stroke={strokeColor}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={FACE_LENGTH}
        animatedProps={sweepProps}
      />
      <AnimatedCircle
        cx={MARK_DOT.x}
        cy={MARK_DOT.y}
        fill="none"
        stroke={colors.accent}
        strokeWidth={1.2}
        animatedProps={haloProps}
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
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      style={style}
    >
      <Path
        d={FACE_PATH}
        fill="none"
        stroke={onDark ? palette.creme : palette.terre}
        strokeWidth={stroke}
        strokeLinecap="round"
      />
      <Circle cx={MARK_DOT.x} cy={MARK_DOT.y} r={dot} fill={colors.accent} />
    </Svg>
  );
}
