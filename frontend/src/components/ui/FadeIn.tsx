import { ReactNode } from "react";
import { StyleProp, ViewStyle } from "react-native";

import { motion } from "@/src/theme";
import { Reveal } from "./Reveal";

type Props = {
  children: ReactNode;
  delay?: number;
  duration?: number;
  distance?: number;
  style?: StyleProp<ViewStyle>;
};

/**
 * Entree simple : le contenu monte a sa place en apparaissant.
 *
 * Ce n'est plus qu'un alias de Reveal — garder deux implementations menait a
 * deux rythmes differents dans la meme app, et seule l'une des deux respectait
 * "Reduire les animations".
 */
export function FadeIn({ children, delay = 0, duration = motion.slow, distance = 14, style }: Props) {
  return (
    <Reveal delay={delay} duration={duration} distance={distance} from="up" style={style}>
      {children}
    </Reveal>
  );
}
