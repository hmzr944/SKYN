import { useRouter } from "expo-router";
import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { SkynMark } from "@/src/components/brand/SkynMark";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, motion, type } from "@/src/theme";

/** Le temps que le symbole finisse de se tracer avant de basculer. */
const HOLD = 1950;

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();

  // Les lettres s'ecartent a leur place pendant que le trace se termine :
  // le mot se pose, il n'apparait pas.
  const word = useSharedValue(0);

  useEffect(() => {
    word.value = withDelay(
      1020,
      withTiming(1, { duration: motion.slow, easing: Easing.out(Easing.cubic) }),
    );
  }, [word]);

  const wordStyle = useAnimatedStyle(() => ({
    opacity: word.value,
    letterSpacing: 3 + word.value * 8,
    transform: [{ translateY: (1 - word.value) * 6 }],
  }));

  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      if (cancelled) return;
      if (!user) {
        router.replace("/auth");
      } else if (!profile?.onboarded) {
        router.replace("/profile-setup");
      } else {
        router.replace("/dashboard");
      }
    }, HOLD);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [loading, user, profile, router]);

  return (
    <View style={styles.container} testID="splash-screen">
      <SkynMark size={92} />
      <Animated.Text style={[styles.word, wordStyle]}>SKYN</Animated.Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
    gap: 26,
  },
  word: {
    fontFamily: type.wordmark.fontFamily,
    fontSize: 22,
    color: colors.fg,
  },
});
