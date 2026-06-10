import { useEffect } from "react";
import { View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withDelay,
  withTiming,
  withSequence,
  Easing,
} from "react-native-reanimated";

import { useAuth } from "@/src/contexts/AuthContext";
import { colors, fonts } from "@/src/theme";
import { FadeIn } from "@/src/components/ui/FadeIn";

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();

  const dotScale = useSharedValue(0);
  const dotOpacity = useSharedValue(0);

  useEffect(() => {
    dotOpacity.value = withDelay(500, withTiming(1, { duration: 200 }));
    dotScale.value = withDelay(
      500,
      withSequence(
        withTiming(1.6, { duration: 350, easing: Easing.out(Easing.ease) }),
        withTiming(1, { duration: 250, easing: Easing.inOut(Easing.ease) }),
      ),
    );
  }, [dotOpacity, dotScale]);

  const dotStyle = useAnimatedStyle(() => ({
    opacity: dotOpacity.value,
    transform: [{ scale: dotScale.value }],
  }));

  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      if (!user) {
        if (cancelled) return;
        router.replace("/auth");
      } else if (!profile?.onboarded) {
        router.replace("/profile-setup");
      } else {
        router.replace("/dashboard");
      }
    }, 1200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [loading, user, profile, router]);

  return (
    <View style={styles.container} testID="splash-screen">
      <FadeIn distance={18}>
        <Text style={styles.logo}>SKYN</Text>
      </FadeIn>
      <Animated.View style={[styles.dot, dotStyle]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 64,
    color: colors.onAccent,
    letterSpacing: 14,
    fontWeight: "600",
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.lime,
    marginTop: 24,
  },
});
