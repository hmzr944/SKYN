import { useEffect } from "react";
import { StyleSheet, useWindowDimensions, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";

import { colors, motion, palette } from "@/src/theme";
import { MARK_DOT, MARK_LENGTH, MARK_PATH, MARK_VIEWBOX, markMetrics } from "@/src/theme/mark";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/**
 * L'ouverture : une maree qui monte, se calme, et depose la marque.
 *
 * Trois vagues traversent l'ecran du bas vers le haut, decalees en phase et en
 * vitesse. A mi-parcours leur amplitude s'effondre et elles convergent vers la
 * ligne centrale : l'eau se calme. C'est dans ce calme que le point corail se
 * pose et que le S se deroule a partir de lui.
 *
 * Pourquoi une maree plutot qu'un logo qui apparait : SKYN lit une surface. Une
 * surface agitee ne se lit pas — il faut qu'elle s'apaise d'abord. L'ouverture
 * raconte donc la condition du produit, elle ne decore pas son nom.
 *
 * ────────────────────────────────────────────────────────────────────────
 * COMMENT C'EST DESSINE : chaque vague est une sinusoide echantillonnee en
 * huit segments CUBIQUES, dont les points de controle viennent de la DERIVEE
 * de la sinusoide. Huit segments suffisent alors a une courbe parfaitement
 * lisse, la ou une polyligne en demanderait quarante et facetterait quand
 * meme. Le tout est recalcule a chaque image sur le thread d'animation.
 * ────────────────────────────────────────────────────────────────────────
 */

/** Segments cubiques par vague. Huit suffisent quand les tangentes sont justes. */
const SEG = 8;

/**
 * Une sinusoide, en chemin SVG lisse.
 *
 * `k` est le nombre de demi-periodes sur la largeur : 3 donne une crete et
 * demie, ce qui se lit comme une vague et non comme une ondulation reguliere.
 */
function wavePath(
  w: number,
  h: number,
  baseY: number,
  amp: number,
  phase: number,
  k: number,
  ferme: boolean,
): string {
  "worklet";
  const omega = (Math.PI * k) / w;
  const y = (x: number) => baseY + Math.sin(omega * x + phase) * amp;
  const dy = (x: number) => Math.cos(omega * x + phase) * amp * omega;

  const step = w / SEG;
  let d = `M0,${y(0).toFixed(1)}`;
  for (let i = 0; i < SEG; i++) {
    const x0 = i * step;
    const x1 = x0 + step;
    const c = step / 3;
    d +=
      ` C${(x0 + c).toFixed(1)},${(y(x0) + dy(x0) * c).toFixed(1)}` +
      ` ${(x1 - c).toFixed(1)},${(y(x1) - dy(x1) * c).toFixed(1)}` +
      ` ${x1.toFixed(1)},${y(x1).toFixed(1)}`;
  }
  // Une vague pleine se referme sous le bas de l'ecran : c'est le remplissage
  // qui donne la matiere, le trait seul resterait un trait.
  return ferme ? `${d} L${w.toFixed(1)},${(h + 40).toFixed(1)} L0,${(h + 40).toFixed(1)} Z` : d;
}

/** Les trois couches : profondeur, vitesse et teinte differentes. */
const COUCHES = [
  { retard: 0, k: 3, ampMax: 0.075, vitesse: 1.0, teinte: palette.corail, alpha: 0.1, ferme: true },
  { retard: 0.08, k: 4, ampMax: 0.055, vitesse: 1.22, teinte: palette.corail, alpha: 0.16, ferme: true },
  { retard: 0.16, k: 5, ampMax: 0.04, vitesse: 1.5, teinte: palette.terre, alpha: 0.22, ferme: false },
];

/** Duree de la maree, montee et retrait compris. */
export const TIDE_MS = 2250;
/** Duree totale de la sequence d'ouverture, mot compris. */
export const INTRO_DURATION = 2500;

/** Le point se pose quand la crete vient de passer le centre. */
const DOT_AT = 1250;
const DRAW_AT = 1350;
const DRAW_MS = 780;

export function WaveIntro({ markSize = 96 }: { markSize?: number }) {
  const { width, height } = useWindowDimensions();
  const reduced = useReducedMotion();
  const { stroke, dot } = markMetrics(markSize);

  /** 0 : la maree est en bas et agitee. 1 : elle est au centre et plate. */
  const tide = useSharedValue(0);
  /** Fondu de sortie des vagues, une fois la marque en place. */
  const fade = useSharedValue(0);
  const drop = useSharedValue(0);
  const draw = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      // Aucune maree : la marque se pose, et c'est tout.
      tide.value = 1;
      fade.value = 1;
      drop.value = 1;
      draw.value = 1;
      return;
    }
    // Progression LINEAIRE, volontairement : la forme du mouvement (montee,
    // crete, retrait, apaisement) est deja calculee image par image plus bas.
    // Une courbe d'acceleration par-dessus deformait ce decoupage — la crete
    // arrivait au tiers du temps et l'ecran etait vide aux deux tiers.
    tide.value = withTiming(1, { duration: TIDE_MS, easing: Easing.linear });
    // Les vagues sortent d'elles-memes par le bas ; ce fondu n'est qu'un
    // filet de securite sur les tres petits ecrans, ou le retrait est court.
    fade.value = withDelay(TIDE_MS - 200, withTiming(1, { duration: 420 }));
    drop.value = withDelay(DOT_AT, withSpring(1, motion.springDrop));
    draw.value = withDelay(
      DRAW_AT,
      withTiming(1, { duration: DRAW_MS, easing: Easing.bezier(0.33, 1, 0.68, 1) }),
    );
  }, [reduced, tide, fade, drop, draw]);

  const dotProps = useAnimatedProps(() => ({ r: dot * drop.value }));
  const drawProps = useAnimatedProps(() => ({
    strokeDashoffset: MARK_LENGTH * (1 - draw.value),
    opacity: draw.value > 0 ? 1 : 0,
  }));

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      {!reduced ? (
        <Svg width={width} height={height} style={StyleSheet.absoluteFill}>
          {COUCHES.map((c, i) => (
            <Vague key={i} c={c} tide={tide} fade={fade} w={width} h={height} />
          ))}
        </Svg>
      ) : null}

      <View style={styles.center}>
        <Svg width={markSize} height={markSize} viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}>
          <AnimatedPath
            d={MARK_PATH}
            fill="none"
            stroke={palette.terre}
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
      </View>
    </View>
  );
}

/** Une couche de la maree. */
function Vague({
  c,
  tide,
  fade,
  w,
  h,
}: {
  c: (typeof COUCHES)[number];
  tide: SharedValue<number>;
  fade: SharedValue<number>;
  w: number;
  h: number;
}) {
  const props = useAnimatedProps(() => {
    // Chaque couche part avec un retard : la maree n'arrive pas d'un bloc.
    const t = Math.max(0, Math.min(1, (tide.value - c.retard) / (1 - c.retard)));

    // Une vague MONTE puis SE RETIRE. La premiere version s'arretait a
    // mi-hauteur et y restait : on obtenait un bloc rose immobile coupe par
    // une ligne droite, l'exact contraire d'une maree.
    //
    // Elle monte donc jusqu'au-dessus du centre, puis redescend hors de
    // l'ecran — et c'est ce retrait qui decouvre la marque.
    // Le retrait couvre plus de temps que la montee, et il est cale pour que
    // l'eau descende PENDANT que le S se dessine : c'est le retrait qui le
    // decouvre.
    //
    // La distance de retrait s'arrete juste sous le bord bas. Elle valait
    // d'abord 0,95 h : la vague quittait l'ecran aux trois quarts du temps
    // imparti et finissait sa course dans le vide, si bien qu'on regardait un
    // fond creme pendant que le trace se faisait.
    const MONTEE = 0.45;
    const baseY =
      t < MONTEE
        ? h * 1.22 - (t / MONTEE) * h * 0.8
        : h * 0.42 + ((t - MONTEE) / (1 - MONTEE)) ** 1.05 * h * 0.66;

    // L'amplitude enfle a la montee, s'apaise au retrait : l'eau se leve, puis
    // se calme en repartant.
    const enfle = Math.min(1, t / 0.28);
    const calme = Math.max(0, 1 - Math.max(0, (t - MONTEE) / (1 - MONTEE)) ** 1.4);
    const amp = h * c.ampMax * enfle * (0.35 + 0.65 * calme);

    // La phase avance en continu : c'est ce qui fait avancer la vague
    // lateralement pendant qu'elle monte.
    const phase = t * Math.PI * 2.4 * c.vitesse;

    return {
      d: wavePath(w, h, baseY, amp, phase, c.k, c.ferme),
      opacity: c.alpha * (1 - fade.value),
    };
  });

  return c.ferme ? (
    <AnimatedPath fill={c.teinte} animatedProps={props} />
  ) : (
    <AnimatedPath fill="none" stroke={c.teinte} strokeWidth={2} animatedProps={props} />
  );
}

const styles = StyleSheet.create({
  center: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
});
