import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, {
  Circle,
  ClipPath,
  Defs,
  G,
  Image as SvgImage,
  LinearGradient,
  Path,
  Rect,
  Stop,
} from "react-native-svg";
import Animated, {
  Easing,
  SharedValue,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { colors, motion, palette } from "@/src/theme";
import { FACE_CLOSED, FACE_LENGTH, FACE_PATH, MARK_VIEWBOX } from "@/src/theme/mark";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedRect = Animated.createAnimatedComponent(Rect);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

export type Detection = { x: number; y: number; radius?: number };

type Props = {
  size: number;
  /** 0 surface · 1 zones · 2 patterns · 3 rapport */
  phase: number;
  imageB64?: string | null;
  detections?: Detection[];
  style?: StyleProp<ViewStyle>;
};

/** Les zones du decoupage, en coordonnees du repere 64x64. */
const ZONES = [
  { x: 32, y: 18, r: 7 }, // front
  { x: 21, y: 30, r: 6 }, // joue gauche
  { x: 43, y: 30, r: 6 }, // joue droite
  { x: 32, y: 31, r: 4 }, // nez
  { x: 32, y: 44, r: 5.5 }, // menton
];

/**
 * Le champ d'analyse.
 *
 * C'est le symbole de la marque, agrandi et pose sur la capture : meme contour,
 * meme breche. Le trace tourne autour du visage pendant que la bande de lecture
 * le parcourt de haut en bas, puis les zones s'allument une par une et les
 * reperes corail se posent la ou le moteur a trouve quelque chose.
 *
 * La legere rotation en Y n'est pas un effet : elle donne au contour l'epaisseur
 * d'un volume, pour qu'on lise une surface examinee sous plusieurs angles
 * plutot qu'un gabarit plaque sur une photo.
 */
export function ScanField({ size, phase, imageB64, detections = [], style }: Props) {
  // Le contour se trace en boucle : le balayage n'est pas fini tant que
  // l'analyse tourne. Il se fige a la derniere phase.
  const sweep = useSharedValue(0);
  // La bande de lecture descend puis remonte.
  const band = useSharedValue(0);
  // L'ouverture des zones, une fois le mapping atteint.
  const zones = useSharedValue(0);
  // La pose des reperes.
  const marks = useSharedValue(0);
  // L'oscillation du volume.
  const tilt = useSharedValue(0);

  useEffect(() => {
    sweep.value = withRepeat(
      withSequence(
        withTiming(1, { duration: motion.sweep, easing: Easing.bezier(0.33, 1, 0.68, 1) }),
        withTiming(1, { duration: 260 }),
        withTiming(0, { duration: 0 }),
      ),
      -1,
      false,
    );
    band.value = withRepeat(
      withTiming(1, { duration: 1600, easing: Easing.inOut(Easing.quad) }),
      -1,
      true,
    );
    tilt.value = withRepeat(
      withTiming(1, { duration: 3800, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [sweep, band, tilt]);

  useEffect(() => {
    // Les zones s'ouvrent au mapping, les reperes se posent aux patterns.
    zones.value = withTiming(phase >= 1 ? 1 : 0, { duration: motion.slow });
    marks.value = withDelay(
      phase >= 2 ? 120 : 0,
      withSpring(phase >= 2 ? 1 : 0, motion.springDrop),
    );
  }, [phase, zones, marks]);

  const contourProps = useAnimatedProps(() => ({
    strokeDashoffset: FACE_LENGTH * (1 - sweep.value),
  }));

  // La bande traverse tout le repere, marges comprises.
  const bandProps = useAnimatedProps(() => ({
    y: -6 + band.value * (MARK_VIEWBOX + 2),
  }));

  const zoneProps = useAnimatedProps(() => ({ opacity: zones.value * 0.5 }));

  const tiltStyle = useAnimatedStyle(() => ({
    transform: [
      { perspective: 700 },
      { rotateY: `${(tilt.value - 0.5) * 13}deg` },
      { rotateX: `${(0.5 - tilt.value) * 4}deg` },
    ],
  }));

  const list = detections.length > 0 ? detections : [];

  return (
    <Animated.View style={[style, tiltStyle]}>
      <Svg width={size} height={size} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}>
        <Defs>
          <ClipPath id="skyn-face">
            <Path d={FACE_CLOSED} />
          </ClipPath>
          <LinearGradient id="skyn-band" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={palette.corail} stopOpacity="0" />
            <Stop offset="0.5" stopColor={palette.corail} stopOpacity="0.85" />
            <Stop offset="1" stopColor={palette.corail} stopOpacity="0" />
          </LinearGradient>
        </Defs>

        <G clipPath="url(#skyn-face)">
          {imageB64 ? (
            <SvgImage
              href={{ uri: `data:image/jpeg;base64,${imageB64}` }}
              x="0"
              y="0"
              width={MARK_VIEWBOX}
              height={MARK_VIEWBOX}
              preserveAspectRatio="xMidYMid slice"
              opacity={0.55}
            />
          ) : (
            <Path d={FACE_CLOSED} fill={colors.surfaceSunken} />
          )}

          {/* Voile terre : la capture passe au second plan, le trace au premier. */}
          <Path d={FACE_CLOSED} fill={palette.terre} opacity={imageB64 ? 0.28 : 0.06} />

          {/* Le decoupage en zones, une fois le mapping atteint. */}
          {ZONES.map((z, i) => (
            <AnimatedCircle
              key={i}
              cx={z.x}
              cy={z.y}
              r={z.r}
              fill="none"
              stroke={imageB64 ? palette.creme : palette.terre}
              strokeWidth={0.6}
              animatedProps={zoneProps}
            />
          ))}

          {/* La bande de lecture. */}
          <AnimatedRect
            x={0}
            width={MARK_VIEWBOX}
            height={6}
            fill="url(#skyn-band)"
            animatedProps={bandProps}
          />
        </G>

        {/* Le contour — le symbole lui-meme, a l'echelle du visage. */}
        <AnimatedPath
          d={FACE_PATH}
          fill="none"
          stroke={colors.accent}
          strokeWidth={1}
          strokeLinecap="round"
          strokeDasharray={FACE_LENGTH}
          animatedProps={contourProps}
        />

        {/* Les reperes : la ou le moteur a trouve quelque chose. */}
        {list.map((d, i) => (
          <DetectionMark key={i} d={d} progress={marks} index={i} />
        ))}
      </Svg>
    </Animated.View>
  );
}

/** Un repere se pose au ressort, avec son halo — comme le point du symbole. */
function DetectionMark({
  d,
  progress,
  index,
}: {
  d: Detection;
  progress: SharedValue<number>;
  index: number;
}) {
  const cx = d.x * MARK_VIEWBOX;
  const cy = d.y * MARK_VIEWBOX;
  const r = Math.max(1.6, (d.radius ?? 0.04) * MARK_VIEWBOX * 0.9);

  // Chaque repere part legerement apres le precedent : la lecture se fait
  // point par point, pas d'un bloc.
  const ramp = (v: number) => {
    "worklet";
    const start = Math.min(index * 0.14, 0.7);
    return Math.max(0, Math.min(1, (v - start) / (1 - start)));
  };

  const ringProps = useAnimatedProps(() => {
    const p = ramp(progress.value);
    return { r: r * (0.6 + p * 0.6), opacity: p * 0.9 };
  });
  const coreProps = useAnimatedProps(() => {
    const p = ramp(progress.value);
    return { r: 0.9 * p, opacity: p };
  });

  return (
    <>
      <AnimatedCircle
        cx={cx}
        cy={cy}
        fill="none"
        stroke={colors.accent}
        strokeWidth={0.7}
        animatedProps={ringProps}
      />
      <AnimatedCircle cx={cx} cy={cy} fill={colors.accent} animatedProps={coreProps} />
    </>
  );
}
