import { ReactNode, useEffect, useState } from "react";
import { LayoutChangeEvent, Pressable, StyleSheet, Text, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { colors, motion, spacing, type } from "@/src/theme";

/**
 * Une explication qu'on ouvre si on veut.
 *
 * Les cartes de l'app portaient chacune un paragraphe d'explication en clair,
 * toujours affiche. On le lit une fois ; ensuite il ne fait qu'eloigner les
 * boutons et donner a chaque ecran la meme silhouette de pave de texte.
 *
 * Le texte n'est pas supprime pour autant : quelqu'un qui suit une reaction
 * cutanee a le droit de savoir POURQUOI on lui demande ca. Il est juste plie,
 * et l'ouverture se voit — c'est le depliage qui dit qu'il y avait quelque
 * chose la, pas une ligne de plus.
 */
export function Disclosure({
  label = "Pourquoi ?",
  children,
  testID,
}: {
  label?: string;
  children: ReactNode;
  testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const [height, setHeight] = useState(0);
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withTiming(open ? 1 : 0, {
      duration: reduced ? 0 : motion.base,
      easing: Easing.out(Easing.cubic),
    });
  }, [open, t, reduced]);

  // La hauteur est MESUREE, jamais devinee : le texte se replie differemment
  // selon la largeur de l'ecran et le corps choisi par le systeme.
  const onMeasure = (e: LayoutChangeEvent) => {
    const h = Math.ceil(e.nativeEvent.layout.height);
    setHeight((prev) => (Math.abs(prev - h) < 1 ? prev : h));
  };

  const body = useAnimatedStyle(() => ({
    height: t.value * height,
    opacity: t.value,
  }));

  const sign = useAnimatedStyle(() => ({
    transform: [{ rotate: `${t.value * 45}deg` }],
  }));

  return (
    <View>
      <Pressable
        testID={testID}
        onPress={() => setOpen((v) => !v)}
        style={styles.trigger}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
      >
        <Text style={styles.label}>{label}</Text>
        <Animated.Text style={[styles.sign, sign]}>+</Animated.Text>
      </Pressable>

      <Animated.View style={[styles.clip, body]}>
        <View onLayout={onMeasure} style={styles.content}>
          {children}
        </View>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 32,
  },
  label: { ...type.bodySmall, color: colors.fgDim, textDecorationLine: "underline" },
  sign: { ...type.bodySmall, color: colors.fgDim, lineHeight: 16 },
  clip: { overflow: "hidden" },
  content: { paddingTop: spacing.xs },
});
