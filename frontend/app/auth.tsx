import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { SkynMark } from "@/src/components/brand/SkynMark";
import { useAuth } from "@/src/contexts/AuthContext";

export default function AuthScreen() {
  const router = useRouter();
  const { continueAsGuest } = useAuth();
  const [starting, setStarting] = useState(false);

  const blobT = useSharedValue(0);
  useEffect(() => {
    blobT.value = withRepeat(
      withTiming(1, { duration: 6000, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [blobT]);
  const blobStyleA = useAnimatedStyle(() => ({
    transform: [
      { translateY: blobT.value * -18 },
      { scale: 1 + blobT.value * 0.06 },
    ],
  }));
  const blobStyleB = useAnimatedStyle(() => ({
    transform: [
      { translateY: blobT.value * 16 },
      { scale: 1 - blobT.value * 0.05 },
    ],
  }));

  const startOnboarding = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setStarting(true);
    router.replace("/onboarding");
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Decorative animated blobs */}
      <Animated.View style={[styles.blob, styles.blobA, blobStyleA]} pointerEvents="none">
        <LinearGradient
          colors={[colors.accent, "rgba(255,107,74,0)"]}
          style={styles.blobFill}
          start={{ x: 0.3, y: 0.2 }}
          end={{ x: 1, y: 1 }}
        />
      </Animated.View>
      <Animated.View style={[styles.blob, styles.blobB, blobStyleB]} pointerEvents="none">
        <LinearGradient
          colors={[colors.accentSoft, "rgba(255, 77, 109, 0)"]}
          style={styles.blobFill}
          start={{ x: 0.2, y: 0.2 }}
          end={{ x: 1, y: 1 }}
        />
      </Animated.View>

      {/* Hero */}
      <View style={styles.hero}>
        <FadeIn delay={80} distance={18}>
          <SkynMark size={84} style={{ alignSelf: "center", marginBottom: spacing.l }} />
          <Text style={styles.logo}>SKYN</Text>
        </FadeIn>
        <FadeIn delay={200}>
          <View style={styles.hairline} />
        </FadeIn>
        <FadeIn delay={260}>
          <Text style={styles.tagline}>{"L'analyse cutanée éditoriale"}</Text>
        </FadeIn>
      </View>

      {/* Actions */}
      <View style={styles.actions}>
        <FadeIn delay={360}>
          <AnimatedPressable
            testID="auth-main-button"
            style={[styles.primaryBtn, starting && styles.primaryBtnDisabled]}
            onPress={startOnboarding}
            disabled={starting}
          >
            {starting ? (
              <ActivityIndicator color={colors.onAccent} />
            ) : (
              <Text style={styles.primaryBtnText}>Commencer</Text>
            )}
          </AnimatedPressable>
        </FadeIn>

        <FadeIn delay={410}>
          <AnimatedPressable
            testID="auth-guest-button"
            style={styles.guestBtn}
            haptic={false}
            onPress={async () => {
              await continueAsGuest();
              router.replace("/profile-setup");
            }}
          >
            <Text style={styles.guestBtnText}>Tester sans compte</Text>
          </AnimatedPressable>
        </FadeIn>

        <FadeIn delay={440}>
          <Text style={styles.gdpr} testID="auth-gdpr">
            En continuant, vous créez votre dossier cutané chiffré. Vos photos
            sont analysées puis immédiatement supprimées.
          </Text>
        </FadeIn>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.xl,
    justifyContent: "space-between",
    overflow: "hidden",
  },
  blob: {
    position: "absolute",
    borderRadius: 999,
    overflow: "hidden",
  },
  guestBtn: { alignItems: "center", paddingVertical: spacing.m },
  guestBtnText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fgMuted,
    textDecorationLine: "underline",
  },
  blobFill: { flex: 1, borderRadius: 999 },
  blobA: { width: 280, height: 280, top: -80, right: -90, opacity: 0.35 },
  blobB: { width: 240, height: 240, bottom: 60, left: -100, opacity: 0.3 },
  hero: {
    marginTop: spacing.xxxl + spacing.xxl,
    alignItems: "center",
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 62,
    color: colors.fg,
    letterSpacing: 13,
    // La chasse ajoute une gouttiere apres la derniere lettre : on la
    // compense a gauche pour que le mot soit optiquement centre.
    paddingLeft: 13,
  },
  hairline: {
    width: 48,
    height: 2,
    backgroundColor: colors.accent,
    borderRadius: 1,
    marginTop: spacing.l,
    marginBottom: spacing.m,
  },
  tagline: {
    fontFamily: fonts.body,
    fontSize: 15,
    color: colors.fgMuted,
    letterSpacing: 0.5,
  },
  actions: {
    paddingBottom: spacing.l,
    gap: spacing.m,
  },
  primaryBtn: {
    backgroundColor: colors.accent,
    paddingVertical: 20,
    alignItems: "center",
    borderRadius: radius.pill,
    ...shadow.button,
  },
  primaryBtnDisabled: { opacity: 0.6 },
  primaryBtnText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  gdpr: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
    paddingHorizontal: spacing.s,
  },
});
