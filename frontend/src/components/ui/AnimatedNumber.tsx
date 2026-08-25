import { ease } from "@/src/animation/ease";
import { useEffect } from "react";
import { StyleProp, TextInput, TextStyle } from "react-native";
import Animated, {
  useAnimatedProps,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

const AnimatedInput = Animated.createAnimatedComponent(TextInput);
Animated.addWhitelistedNativeProps({ text: true });

type Props = {
  value: number;
  delay?: number;
  duration?: number;
  style?: StyleProp<TextStyle>;
};

/**
 * Le score compte jusqu'a sa valeur.
 *
 * Un chiffre qui apparait deja fixe est une donnee ; un chiffre qui monte est
 * un resultat qu'on vient d'obtenir. On passe par un TextInput non editable
 * parce que c'est le seul noeud dont reanimated peut ecrire le texte sans
 * repasser par le thread JS a chaque image.
 */
export function AnimatedNumber({ value, delay = 240, duration = 1000, style }: Props) {
  const n = useSharedValue(0);

  useEffect(() => {
    n.value = 0;
    n.value = withDelay(delay, withTiming(value, { duration, easing: ease.out }));
  }, [value, delay, duration, n]);

  const animatedProps = useAnimatedProps(() => ({
    text: String(Math.round(n.value)),
    defaultValue: String(Math.round(n.value)),
  }));

  return (
    <AnimatedInput
      editable={false}
      // Le champ n'est jamais saisissable : c'est un affichage, pas un controle.
      pointerEvents="none"
      underlineColorAndroid="transparent"
      style={style}
      animatedProps={animatedProps as never}
      value={String(value)}
    />
  );
}
