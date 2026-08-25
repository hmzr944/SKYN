import Animated, { SharedValue, useAnimatedProps } from "react-native-reanimated";
import { Line } from "react-native-svg";

import { colors } from "@/src/theme";

const AnimatedLine = Animated.createAnimatedComponent(Line);

/**
 * La couronne de traits, façon enregistrement Face ID.
 *
 * Chaque trait represente une direction de rotation. Ils s'allument a mesure
 * que la tete balaie l'amplitude : le geste devient evident sans explication,
 * parce qu'une couronne ne dit pas seulement COMBIEN il reste, elle dit aussi
 * DE QUEL COTE aller.
 *
 * Position, rayon et progression arrivent en valeurs animees : la couronne
 * suit le visage image par image, sans repasser par le rendu React. C'est ce
 * qui lui permet de coller au mouvement au lieu de sauter.
 */

/** Assez de traits pour lire une progression continue, pas assez pour moutonner. */
const TICKS = 36;

type Geo = {
  cx: SharedValue<number>;
  cy: SharedValue<number>;
  radius: SharedValue<number>;
  /** Part de l'amplitude couverte, entre 0 et 1. */
  progress: SharedValue<number>;
};

function Tick({ index, cx, cy, radius, progress }: Geo & { index: number }) {
  // On part du haut et on tourne : c'est le sens de lecture d'un cadran.
  const angle = (index / TICKS) * Math.PI * 2 - Math.PI / 2;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  // Distance au sommet dans les deux sens : le remplissage est symetrique,
  // il ne privilegie aucun cote.
  const fromTop = Math.min(index, TICKS - index);

  /** Allumage continu plutot que binaire : la transition se lit mieux. */
  const litness = () => {
    "worklet";
    return Math.max(0, Math.min(1, (progress.value * TICKS - fromTop * 2) / 2));
  };

  const baseProps = useAnimatedProps(() => {
    const r = radius.value;
    const len = Math.max(6, r * 0.07);
    return {
      x1: cx.value + cos * r,
      y1: cy.value + sin * r,
      x2: cx.value + cos * (r + len),
      y2: cy.value + sin * (r + len),
    };
  });

  const litProps = useAnimatedProps(() => {
    const r = radius.value;
    const len = Math.max(6, r * 0.07);
    const l = litness();
    // Un trait allume s'allonge : le relief se voit du coin de l'oeil, pendant
    // qu'on regarde son propre visage.
    return {
      x1: cx.value + cos * r,
      y1: cy.value + sin * r,
      x2: cx.value + cos * (r + len * (1 + 0.6 * l)),
      y2: cy.value + sin * (r + len * (1 + 0.6 * l)),
      opacity: l,
    };
  });

  return (
    <>
      <AnimatedLine
        stroke={colors.fg}
        strokeWidth={2}
        strokeLinecap="round"
        opacity={0.16}
        animatedProps={baseProps}
      />
      {/* Le trait allume est superpose : on evite d'animer une couleur, ce qui
          coute cher et rend mal sur certains navigateurs. */}
      <AnimatedLine
        stroke={colors.accent}
        strokeWidth={2.4}
        strokeLinecap="round"
        animatedProps={litProps}
      />
    </>
  );
}

export function ScanRing(geo: Geo) {
  return (
    <>
      {Array.from({ length: TICKS }).map((_, i) => (
        <Tick key={i} index={i} {...geo} />
      ))}
    </>
  );
}
