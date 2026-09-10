import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, {
  Circle,
  ClipPath,
  Defs,
  G,
  LinearGradient,
  Path,
  RadialGradient,
  Rect,
  Stop,
} from "react-native-svg";
import Animated, {
  useReducedMotion,
  SharedValue,
  useAnimatedProps,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { colors, motion } from "@/src/theme";
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
  detections?: Detection[];
  /** La boite du visage dans la photo. Absente sur les analyses anciennes.
   * Sert uniquement a positionner les reperes de lesions — la photo elle-meme
   * n'est plus affichee (voir la note sur `ScanField` plus bas). */
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
    // Pas encore de boite : l'analyse tourne toujours, ou c'est un scan
    // enregistre avant son ajout. La photo s'affiche quand meme, cadree au
    // plus juste sur le contour — c'est le navigateur qui fait le
    // recouvrement, on n'a pas besoin de connaitre ses proportions.
    //
    // La version precedente n'affichait RIEN dans ce cas : pendant les trois
    // premieres phases, on regardait un ovale gris en attendant. Or c'est
    // precisement le moment ou l'on veut voir sa propre photo etre lue.
    return {
      known: false,
      imgX: OVAL.x,
      imgY: OVAL.y,
      imgW: OVAL.w,
      imgH: OVAL.h,
      markX: (nx: number) => OVAL.x + nx * OVAL.w,
      markY: (ny: number) => OVAL.y + ny * OVAL.h,
      markR: (nr: number) => nr * OVAL.h,
    };
  }
  // Recouvrement : la boite du visage couvre au moins celle du contour, le
  // debord est rogne par le contour lui-meme.
  const s = Math.max(OVAL.w / box.w, OVAL.h / box.h);
  return {
    known: true,
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
 * C'est le symbole de la marque, agrandi : meme contour, meme breche. Le
 * trace tourne autour du visage pendant que la bande de lecture le parcourt
 * de haut en bas, puis les reperes corail se posent la ou le moteur a trouve
 * quelque chose.
 *
 * Il portait aussi cinq cercles blancs censes montrer le decoupage en zones.
 * Ils etaient a des positions fixes pendant qu'un texte annonçait treize
 * regions : ils n'indiquaient rien, et encombraient la capture.
 *
 * Il affichait aussi la PROPRE PHOTO de la personne, sous un voile terre, avec
 * une legere rotation 3D continue — voir sa photo osciller pendant qu'un
 * calcul tourne dessus se lit comme un bug, pas comme une analyse en cours.
 * Retire : le contour reste seul, avec un halo qui respire a la place — la
 * meme idee que PhaseHalo ailleurs dans l'app, pas une photo qui bouge.
 */
export function ScanField({ size, phase, detections = [], faceBox, style }: Props) {
  const f = frame(faceBox);
  // Le contour se trace en boucle : le balayage n'est pas fini tant que
  // l'analyse tourne. Il se fige a la derniere phase.
  const sweep = useSharedValue(0);
  // La bande de lecture descend puis remonte.
  const band = useSharedValue(0);
  // La pose des reperes.
  const marks = useSharedValue(0);
  // Le halo qui respire, a la place de l'ancienne oscillation 3D.
  const glow = useSharedValue(0);

  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      // Le contenu reste, le mouvement s'arrete : le contour se pose entier,
      // la bande et le halo ne bougent plus.
      sweep.value = withTiming(1, { duration: motion.slow });
      band.value = 0.5;
      glow.value = 0.5;
      return;
    }
    sweep.value = withRepeat(
      withSequence(
        withTiming(1, { duration: motion.sweep, easing: ease.expoOut }),
        withTiming(1, { duration: 260 }),
        withTiming(0, { duration: 0 }),
      ),
      -1,
      false,
    );
    band.value = withRepeat(
      withTiming(1, { duration: 1600, easing: ease.sineInOut }),
      -1,
      true,
    );
    glow.value = withRepeat(
      withTiming(1, { duration: 2200, easing: ease.sineInOut }),
      -1,
      true,
    );
  }, [reduced, sweep, band, glow]);

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

  const glowProps = useAnimatedProps(() => ({
    opacity: 0.18 + glow.value * 0.22,
  }));

  const list = detections.length > 0 ? detections : [];

  return (
    <Animated.View style={style}>
      <Svg width={size} height={size} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}>
        <Defs>
          <ClipPath id="skyn-face">
            <Path d={FACE_CLOSED} />
          </ClipPath>
          <RadialGradient id="skyn-glow" cx="50%" cy="46%" r="55%">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0.5" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="0" />
          </RadialGradient>
          <LinearGradient id="skyn-band" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0" />
            <Stop offset="0.5" stopColor={colors.accent} stopOpacity="0.85" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="0" />
          </LinearGradient>
        </Defs>

        <G clipPath="url(#skyn-face)">
          <Path d={FACE_CLOSED} fill={colors.surfaceSunken} />

          {/* Le halo qui respire — la vie de l'ecran, a la place d'une photo
              qui bougeait sans qu'on comprenne pourquoi. */}
          <AnimatedRect
            x={0}
            y={0}
            width={MARK_VIEWBOX}
            height={MARK_VIEWBOX}
            fill="url(#skyn-glow)"
            animatedProps={glowProps}
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
