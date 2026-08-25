import { useEffect, useMemo } from "react";
import { useReducedMotion, useSharedValue, type SharedValue } from "react-native-reanimated";

import { ease } from "./ease";
import { timeline } from "./timeline";

/**
 * La sequence d'ouverture, ecrite en un seul endroit.
 *
 * Elle etait dispersee : la maree et le trace dans le composant de vague, le
 * mot et la sortie dans l'ecran, chacun avec ses retards calcules a la main.
 * Personne ne pouvait lire la sequence en entier, et c'est comme ça qu'on
 * arrive a une vague qui se retire pendant que le logo se dessine dans le
 * vide.
 *
 * Ici la sequence SE LIT : chaque etape est placee par rapport a la
 * precedente ou a un repere. Rallonger la maree decale tout ce qui suit, sans
 * qu'aucun autre nombre ne bouge.
 */

export interface IntroValues {
  /** 0 : la maree est en bas et agitee. 1 : elle est sortie par le bas. */
  tide: SharedValue<number>;
  /** Fondu de securite des vagues. */
  fade: SharedValue<number>;
  /** Le point corail se pose. */
  drop: SharedValue<number>;
  /** Le S se deroule. */
  draw: SharedValue<number>;
  /** Le mot se pose sous la marque. */
  word: SharedValue<number>;
  /** Le bloc entier s'eleve et s'efface. */
  exit: SharedValue<number>;
}

/** Duree de la maree, montee et retrait compris, en secondes. */
const MAREE = 2.25;

export function useIntroTimeline() {
  const tide = useSharedValue(0);
  const fade = useSharedValue(0);
  const drop = useSharedValue(0);
  const draw = useSharedValue(0);
  const word = useSharedValue(0);
  const exit = useSharedValue(0);
  const reduced = useReducedMotion();

  const valeurs: IntroValues = useMemo(
    () => ({ tide, fade, drop, draw, word, exit }),
    [tide, fade, drop, draw, word, exit],
  );

  /**
   * On construit d'abord, on joue ensuite.
   *
   * La construction seule donne la duree totale, dont l'ecran a besoin pour
   * savoir quand basculer. Ce nombre etait auparavant recopie a la main a
   * cote de la sequence, et se desynchronisait a chaque reglage.
   */
  const tl = useMemo(() => construire(valeurs, reduced), [valeurs, reduced]);

  useEffect(() => tl.play(), [tl]);

  return { valeurs, duree: tl.duration() };
}

function construire(v: IntroValues, reduced: boolean) {
  const tl = timeline({
    defaults: { duration: 0.6, ease: ease.out },
    reduced,
  });

  tl
    // La maree avance a vitesse constante : sa forme — montee, crete, retrait,
    // apaisement — est deja dessinee image par image dans le composant. Une
    // courbe d'acceleration par-dessus deformerait ce decoupage.
    .to(v.tide, 1, { duration: MAREE, ease: ease.none }, 0)

    // Repere : le moment ou la crete vient de passer le centre de l'ecran.
    // Tout ce qui concerne la marque s'accroche a lui, pas a un chiffre.
    .label("crete", MAREE * 0.45)

    // Le point tombe dans l'eau qui se retire, avec un depassement franc.
    .to(v.drop, 1, { duration: 0.55, ease: ease.dropStrong }, "crete+=0.25")

    // Le S se deroule a partir du point, pendant que l'eau descend.
    .to(v.draw, 1, { duration: 0.78, ease: ease.expoOut }, "<0.1")

    // Filet de securite : sur un ecran tres court, le retrait ne suffit pas a
    // sortir les vagues du cadre.
    .to(v.fade, 1, { duration: 0.42 }, MAREE - 0.2)

    // Le mot se pose une fois le trace fini, pas pendant.
    .label("marque", ">")
    .to(v.word, 1, { duration: 0.42 }, "marque-=0.1")

    // La sortie commence pendant que le mot finit : pas de temps mort.
    .to(v.exit, 1, { duration: 0.28, ease: ease.in }, ">-=0.12");

  return tl;
}
