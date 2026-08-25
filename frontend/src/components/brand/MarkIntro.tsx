import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";
import Animated, {
  Easing,
  type SharedValue,
  useAnimatedProps,
  useDerivedValue,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { colors, palette } from "@/src/theme";
import { FACE_LENGTH, FACE_PATH, MARK_DOT, MARK_VIEWBOX, markMetrics } from "@/src/theme/mark";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);
const AnimatedPath = Animated.createAnimatedComponent(Path);

/**
 * L'ouverture de l'app : le point traverse, puis la marque se forme.
 *
 * Le symbole n'apparait pas — il arrive. Un point corail entre par le bas a
 * gauche, traverse le cadre en decelerant, et se pose exactement dans la
 * breche du contour. Le contour ne se dessine qu'ENSUITE, et il part du point :
 * la marque nait de ce qui vient de bouger, elle ne se pose pas a cote.
 *
 * C'est la meme sequence que le produit — quelque chose parcourt une surface,
 * s'arrete sur un endroit, et le signale — jouee en une seconde et demie. Une
 * animation d'ouverture qui raconterait autre chose que ce que fait l'app
 * serait une decoration ; celle-ci est une demonstration.
 */

/** Le point entre hors cadre : le dessin deborde donc le carre de la marque. */
const PAD = 32;

/** Depart, point de controle, arrivee — dans le repere du dessin. */
const P0 = { x: -26, y: 92 };
const P1 = { x: 20, y: 30 };
const P2 = MARK_DOT;

/** Position sur la courbe. Une quadratique suffit : un seul infléchissement. */
function at(p: number, axis: "x" | "y") {
  "worklet";
  const u = 1 - p;
  return u * u * P0[axis] + 2 * u * p * P1[axis] + p * p * P2[axis];
}

/** Retards de la sequence, en millisecondes depuis le montage. */
const TRAVEL = 920;
const SWEEP = 820;
const WAVE_AT = TRAVEL + SWEEP - 240;

/** Duree totale du trace, utile a l'ecran qui enchaine derriere. */
export const INTRO_DURATION = TRAVEL + SWEEP;

/** Sillage : chaque fantome est en retard d'autant de course sur le point. */
const TRAIL = [0.075, 0.155, 0.245, 0.35];

type Props = {
  size?: number;
  style?: StyleProp<ViewStyle>;
};

export function MarkIntro({ size = 92, style }: Props) {
  const { stroke, dot } = markMetrics(size);
  const reduced = useReducedMotion();

  const travel = useSharedValue(0);
  const sweep = useSharedValue(0);
  const wave = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      // Le mouvement est coupe, pas le contenu : la marque se pose sans course.
      travel.value = 1;
      sweep.value = withTiming(1, { duration: 320 });
      return;
    }
    // Entree franche, arret long : le point a une masse, il ne s'arrete pas
    // net. La courbe reste assez plate au debut pour qu'on voie la course —
    // une deceleration trop brutale donnait un point deja arrive.
    travel.value = withTiming(1, {
      duration: TRAVEL,
      easing: Easing.bezier(0.3, 0.62, 0.25, 1),
    });
    sweep.value = withDelay(
      TRAVEL,
      withTiming(1, { duration: SWEEP, easing: Easing.bezier(0.33, 1, 0.68, 1) }),
    );
    wave.value = withDelay(
      WAVE_AT,
      withTiming(1, { duration: 720, easing: Easing.out(Easing.quad) }),
    );
  }, [reduced, travel, sweep, wave]);

  const sweepProps = useAnimatedProps(() => ({
    strokeDashoffset: FACE_LENGTH * (1 - sweep.value),
    // Le trait n'existe pas avant que le point soit pose.
    opacity: sweep.value > 0 ? 1 : 0,
  }));

  // Le point s'ecrase legerement dans l'elan et reprend sa taille en se posant.
  const rushing = useDerivedValue(() => 1 - travel.value);

  const headProps = useAnimatedProps(() => ({
    cx: at(travel.value, "x"),
    cy: at(travel.value, "y"),
    r: dot * (1 + rushing.value * 0.28),
  }));

  const waveProps = useAnimatedProps(() => ({
    r: dot * (1 + wave.value * 2.1),
    // L'onde n'existe qu'entre les deux bornes : ni avant, ni apres.
    opacity: wave.value === 0 || wave.value === 1 ? 0 : 0.5 * (1 - wave.value),
  }));

  return (
    <Svg
      width={size * ((MARK_VIEWBOX + PAD * 2) / MARK_VIEWBOX)}
      height={size * ((MARK_VIEWBOX + PAD * 2) / MARK_VIEWBOX)}
      viewBox={`${-PAD} ${-PAD} ${MARK_VIEWBOX + PAD * 2} ${MARK_VIEWBOX + PAD * 2}`}
      style={style}
      pointerEvents="none"
    >
      <AnimatedPath
        d={FACE_PATH}
        fill="none"
        stroke={palette.terre}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={FACE_LENGTH}
        animatedProps={sweepProps}
      />
      {TRAIL.map((lag, i) => (
        <TrailDot key={i} travel={travel} lag={lag} radius={dot} rank={i} />
      ))}
      <AnimatedCircle
        cx={MARK_DOT.x}
        cy={MARK_DOT.y}
        fill="none"
        stroke={colors.accent}
        strokeWidth={1.2}
        animatedProps={waveProps}
      />
      <AnimatedCircle fill={colors.accent} animatedProps={headProps} />
    </Svg>
  );
}

/**
 * Un fantome du sillage.
 *
 * Il suit la meme courbe avec un retard fixe de course — pas de temps. Comme
 * la course ralentit a la fin, le sillage se resserre tout seul sur le point a
 * l'arrivee : la trainee se resorbe sans qu'on ait a l'animer separement.
 */
function TrailDot({
  travel,
  lag,
  radius,
  rank,
}: {
  travel: SharedValue<number>;
  lag: number;
  radius: number;
  rank: number;
}) {
  const props = useAnimatedProps(() => {
    const p = Math.max(0, travel.value - lag);
    return {
      cx: at(p, "x"),
      cy: at(p, "y"),
      r: radius * (0.78 - rank * 0.14),
      // Le sillage s'efface a mesure que le point s'arrete.
      opacity: (0.6 - rank * 0.12) * (1 - travel.value),
    };
  });
  return <AnimatedCircle fill={colors.accent} animatedProps={props} />;
}
