import { AnimatePresence, MotiView } from "moti";
import { ReactNode } from "react";
import { StyleProp, View, ViewStyle } from "react-native";
import { useReducedMotion } from "react-native-reanimated";

import { spring } from "@/src/animation/motion";
import { motion } from "@/src/theme";

/**
 * Le passage d'un etat a un autre, dessine.
 *
 * ────────────────────────────────────────────────────────────────────────
 * POURQUOI CE COMPOSANT EXISTE.
 *
 * Partout dans l'app, un ecran passe d'un etat a un autre par un simple
 * ternaire : `loading ? <rond qui tourne/> : <contenu/>`. React demonte le
 * premier et monte le second dans la meme image. Rien ne relie les deux —
 * le contenu ne remplace pas l'attente, il la fait disparaitre.
 *
 * C'est ce que le skill appelle le role d'`AnimatePresence` : ce qui s'en va
 * doit avoir le temps de s'en aller. Ici le sortant monte legerement en
 * s'effacant, l'entrant arrive par en dessous, et `exitBeforeEnter` garantit
 * qu'ils ne se chevauchent jamais dans la mise en page — sinon la hauteur du
 * bloc sauterait pendant le croisement.
 *
 * La sortie est plus courte que l'entree. Une sortie qui traine donne
 * l'impression que l'app hesite.
 * ────────────────────────────────────────────────────────────────────────
 */
export function Swap({
  etat,
  children,
  style,
  distance = 10,
  fill = false,
}: {
  /** Le nom de l'etat courant. Il change quand le contenu change. */
  etat: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  distance?: number;
  /**
   * Le contenu occupe toute la hauteur restante.
   *
   * A mettre des que l'enfant est une liste defilante : sans cela elle se
   * retrouve dans une boite de hauteur libre et ne defile plus.
   */
  fill?: boolean;
}) {
  const reduced = useReducedMotion();
  const plein = fill ? ({ flex: 1 } as const) : undefined;

  if (reduced) return <View style={[plein, style]}>{children}</View>;

  return (
    <View style={[plein, style]}>
      <AnimatePresence exitBeforeEnter>
        <MotiView
          key={etat}
          style={plein}
          // Les valeurs de repos sont ECRITES dans `animate` : sans elles, la
          // sortie n'a pas de point de depart et saute directement a sa cible.
          from={{ opacity: 0, translateY: distance }}
          animate={{ opacity: 1, translateY: 0 }}
          exit={{ opacity: 0, translateY: -distance * 0.6 }}
          transition={spring.gentle}
          exitTransition={{ type: "timing", duration: motion.exit }}
        >
          {children}
        </MotiView>
      </AnimatePresence>
    </View>
  );
}
