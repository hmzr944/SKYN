import { useEffect } from "react";
import { StyleSheet } from "react-native";
import Animated, {
  interpolateColor,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { colors, motion, radius, spacing, type } from "@/src/theme";

/**
 * Une pastille a selectionner.
 *
 * La selection se FAIT, elle ne se constate pas : le fond se remplit et le
 * texte bascule pendant que la pastille se detend, au lieu de changer d'etat
 * d'une image a l'autre. C'est un demi-quart de seconde, et c'est la
 * difference entre un formulaire et quelque chose qui repond.
 *
 * Le meme composant sert au journal et au suivi d'introduction, qui en avaient
 * chacun leur copie — deux copies veut dire deux comportements le jour ou l'on
 * en touche une seule.
 */
export function Chip({
  label,
  on,
  onPress,
  testID,
}: {
  label: string;
  on: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const t = useSharedValue(on ? 1 : 0);

  useEffect(() => {
    t.value = withSpring(on ? 1 : 0, motion.springPress);
  }, [on, t]);

  const box = useAnimatedStyle(() => ({
    backgroundColor: interpolateColor(t.value, [0, 1], ["rgba(42,29,24,0)", colors.fg]),
    borderColor: interpolateColor(t.value, [0, 1], [colors.borderMid, colors.fg]),
  }));

  const text = useAnimatedStyle(() => ({
    color: interpolateColor(t.value, [0, 1], [colors.fgMuted, colors.onInverse]),
  }));

  return (
    <AnimatedPressable testID={testID} onPress={onPress} scaleTo={0.94} style={styles.hit}>
      <Animated.View style={[styles.chip, box]}>
        <Animated.Text style={[styles.label, text]}>{label}</Animated.Text>
      </Animated.View>
    </AnimatedPressable>
  );
}

const styles = StyleSheet.create({
  hit: { minHeight: 44, justifyContent: "center" },
  chip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingVertical: 10,
    paddingHorizontal: spacing.m,
    minHeight: 44,
    justifyContent: "center",
  },
  label: { ...type.label },
});
