import { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Svg, { Circle, G, Path } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { colors, palette } from "@/src/theme";
import { FACE_PATH, MARK_DOT, MARK_VIEWBOX } from "@/src/theme/mark";

const AnimatedG = Animated.createAnimatedComponent(G);

/**
 * Le relevé — l'élément graphique de la marque.
 *
 * C'est le contour du symbole, répété à des échelles décroissantes : la même
 * forme vue en profondeur, comme les courbes de niveau d'une carte. Le motif
 * ne vient pas d'un catalogue de formes décoratives, il vient de ce que fait
 * le produit — lire une surface couche par couche.
 *
 * Il reste volontairement en retrait. C'est un fond, pas une illustration :
 * s'il attire l'oeil, il a échoué.
 */

/** Nombre de niveaux. Au-dela, le motif devient une cible et non un relief. */
const LAYERS = 5;

type Props = {
  size: number;
  /** Rotation lente du relevé. A couper sur les ecrans denses. */
  drift?: boolean;
  /** Marque le point corail au centre du relevé. */
  withPoint?: boolean;
  /** Sur le bloc terre, le trait passe en creme. */
  onDark?: boolean;
  /** Opacite du niveau le plus marque. Les autres s'estompent. */
  intensity?: number;
  style?: StyleProp<ViewStyle>;
};

export function BrandField({
  size,
  drift = false,
  withPoint = false,
  onDark = false,
  intensity = 0.1,
  style,
}: Props) {
  const t = useSharedValue(0);

  useEffect(() => {
    if (!drift) return;
    // Une rotation d'un degre et demi, sur une minute : a peine perceptible,
    // suffisante pour que l'ecran ne soit jamais tout a fait immobile.
    t.value = withRepeat(
      withTiming(1, { duration: 60000, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [drift, t]);

  const driftProps = useAnimatedProps(() => ({
    // La rotation se fait autour du centre du repere, pas de l'angle.
    transform: [{ rotate: `${(t.value - 0.5) * 3}deg` }],
    originX: MARK_VIEWBOX / 2,
    originY: MARK_VIEWBOX / 2,
  }));

  const stroke = onDark ? palette.creme : palette.terre;

  return (
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      style={style}
      pointerEvents="none"
    >
      <AnimatedG animatedProps={driftProps as never}>
        {Array.from({ length: LAYERS }).map((_, i) => {
          // Chaque niveau est plus petit et plus pale que le precedent : la
          // profondeur se lit dans l'espacement, pas dans la couleur.
          const k = 1 - i * 0.17;
          const offset = (MARK_VIEWBOX * (1 - k)) / 2;
          return (
            <G key={i} transform={`translate(${offset}, ${offset}) scale(${k})`}>
              <Path
                d={FACE_PATH}
                fill="none"
                stroke={stroke}
                strokeWidth={1.1 / k}
                strokeLinecap="round"
                opacity={intensity * (1 - i * 0.16)}
              />
            </G>
          );
        })}
        {withPoint ? (
          <Circle cx={MARK_DOT.x} cy={MARK_DOT.y} r={2.6} fill={colors.accent} opacity={0.5} />
        ) : null}
      </AnimatedG>
    </Svg>
  );
}
