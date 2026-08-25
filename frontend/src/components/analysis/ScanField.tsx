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
  useReducedMotion,
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
import type { FaceBox } from "@/src/types/analysis";

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
  /** La boite du visage dans la photo. Absente sur les analyses anciennes. */
  faceBox?: FaceBox | null;
  style?: StyleProp<ViewStyle>;
};

/**
 * L'encombrement du contour dans le repere 64x64, mesure au navigateur
 * (getBBox) : les points de controle d'une courbe debordent de la courbe, une
 * lecture a l'oeil sur le chemin donnerait une boite trop large.
 */
const OVAL = { x: 14.238, y: 10.2, w: 35.524, h: 44.3 };
const OVAL_CX = OVAL.x + OVAL.w / 2;
const OVAL_CY = OVAL.y + OVAL.h / 2;

/**
 * Ou poser la photo et les reperes.
 *
 * Les coordonnees d'une lesion sont normalisees sur la BOITE DU VISAGE, pas
 * sur l'image. Elles etaient pourtant multipliees par les 64 unites du repere
 * entier : une lesion en bord de joue tombait alors a cote du contour, et on
 * voyait des reperes flotter hors du visage.
 *
 * On cadre donc la photo sur la boite du visage, en la posant sur la boite du
 * contour. Les deux reperes coincident alors par construction, et un repere
 * tombe exactement sur ce que le moteur a vu.
 */
function frame(box?: FaceBox | null) {
  if (!box || !box.w || !box.h || !box.image_w || !box.image_h) {
    // Sans la boite (analyses d'avant son ajout), on ne peut plus faire
    // coincider photo et reperes : on replace les reperes sur le contour, ce
    // qui reste anatomiquement juste, et on renonce a la photo dessous.
    return { known: false, s: 1, imgX: 0, imgY: 0, imgW: MARK_VIEWBOX, imgH: MARK_VIEWBOX,
             markX: (nx: number) => OVAL.x + nx * OVAL.w,
             markY: (ny: number) => OVAL.y + ny * OVAL.h,
             markR: (nr: number) => nr * OVAL.h };
  }
  // Recouvrement : la boite du visage couvre au moins celle du contour, le
  // debord est rogne par le contour lui-meme.
  const s = Math.max(OVAL.w / box.w, OVAL.h / box.h);
  return {
    known: true,
    s,
    imgW: box.image_w * s,
    imgH: box.image_h * s,
    imgX: OVAL_CX - (box.x + box.w / 2) * s,
    imgY: OVAL_CY - (box.y + box.h / 2) * s,
    markX: (nx: number) => OVAL_CX + (nx - 0.5) * box.w * s,
    markY: (ny: number) => OVAL_CY + (ny - 0.5) * box.h * s,
    markR: (nr: number) => nr * Math.max(box.w, box.h) * s,
  };
}

/**
 * Le champ d'analyse.
 *
 * C'est le symbole de la marque, agrandi et pose sur la capture : meme contour,
 * meme breche. Le trace tourne autour du visage pendant que la bande de lecture
 * le parcourt de haut en bas, puis les reperes corail se posent la ou le moteur
 * a trouve quelque chose.
 *
 * Il portait aussi cinq cercles blancs censes montrer le decoupage en zones.
 * Ils etaient a des positions fixes pendant qu'un texte annonçait treize
 * regions : ils n'indiquaient rien, et encombraient la capture.
 *
 * La legere rotation en Y n'est pas un effet : elle donne au contour l'epaisseur
 * d'un volume, pour qu'on lise une surface examinee sous plusieurs angles
 * plutot qu'un gabarit plaque sur une photo.
 */
export function ScanField({ size, phase, imageB64, detections = [], faceBox, style }: Props) {
  const f = frame(faceBox);
  // Le contour se trace en boucle : le balayage n'est pas fini tant que
  // l'analyse tourne. Il se fige a la derniere phase.
  const sweep = useSharedValue(0);
  // La bande de lecture descend puis remonte.
  const band = useSharedValue(0);
  // La pose des reperes.
  const marks = useSharedValue(0);
  // L'oscillation du volume.
  const tilt = useSharedValue(0);

  // Trois boucles tournent ici en permanence : le trace, la bande de lecture
  // et le basculement du volume. C'est l'ecran le plus penible de l'app pour
  // quelqu'un sujet au mal des transports, et le seul dont on ne peut pas
  // detourner le regard puisqu'il faut attendre.
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      // Le contenu reste, le mouvement s'arrete : le contour se pose entier,
      // la bande et le volume ne bougent plus.
      sweep.value = withTiming(1, { duration: motion.slow });
      band.value = 0.5;
      tilt.value = 0.5;
      return;
    }
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
  }, [reduced, sweep, band, tilt]);

  useEffect(() => {
    // Les reperes se posent a la phase des motifs, pas avant.
    marks.value = withDelay(
      phase >= 2 ? 120 : 0,
      withSpring(phase >= 2 ? 1 : 0, motion.springDrop),
    );
  }, [phase, marks]);

  const contourProps = useAnimatedProps(() => ({
    strokeDashoffset: FACE_LENGTH * (1 - sweep.value),
  }));

  // La bande traverse tout le repere, marges comprises.
  const bandProps = useAnimatedProps(() => ({
    y: -6 + band.value * (MARK_VIEWBOX + 2),
  }));


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
          {imageB64 && f.known ? (
            <SvgImage
              href={{ uri: `data:image/jpeg;base64,${imageB64}` }}
              x={f.imgX}
              y={f.imgY}
              width={f.imgW}
              height={f.imgH}
              preserveAspectRatio="none"
              opacity={0.62}
            />
          ) : (
            <Path d={FACE_CLOSED} fill={colors.surfaceSunken} />
          )}

          {/* Voile terre : la capture passe au second plan, le trace au premier. */}
          <Path
            d={FACE_CLOSED}
            fill={palette.terre}
            opacity={imageB64 && f.known ? 0.22 : 0.06}
          />

          {/* La bande de lecture. */}
          <AnimatedRect
            x={0}
            width={MARK_VIEWBOX}
            height={6}
            fill="url(#skyn-band)"
            animatedProps={bandProps}
          />

          {/* Les reperes vivent DANS le contour : rien ne peut se poser hors
              du visage, meme si une coordonnee derape.

              Pas de groupe anime autour d'eux : leur apparition est deja
              portee par `marks`, qui vaut zero avant la phase des motifs. Un
              groupe SVG dont on animerait l'opacite ajouterait une couche dont
              rien ne garantit qu'elle se propage pareil sur les trois cibles. */}
          {list.map((d, i) => (
            <DetectionMark key={i} d={d} progress={marks} index={i} frame={f} />
          ))}
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

      </Svg>
    </Animated.View>
  );
}

/** Un repere se pose au ressort, avec son halo, comme le point du symbole. */
function DetectionMark({
  d,
  progress,
  index,
  frame: f,
}: {
  d: Detection;
  progress: SharedValue<number>;
  index: number;
  frame: ReturnType<typeof frame>;
}) {
  const cx = f.markX(d.x);
  const cy = f.markY(d.y);
  // Un plancher de lisibilite : une lesion de 2 mm mesure moins d'un demi-point
  // dans ce repere, et un cercle plus fin que son trait ne se voit pas.
  const r = Math.max(1.2, f.markR(d.radius ?? 0.03) * 1.6);

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
