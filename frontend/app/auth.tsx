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
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { SkynMark } from "@/src/components/brand/SkynMark";
import { useAuth } from "@/src/contexts/AuthContext";

/**
 * Une lettre du mot, qui monte a sa place.
 *
 * Le mot ne s'affiche pas : il se compose. Chaque lettre arrive avec un
 * decalage, de sorte que l'oeil suit la construction de gauche a droite au
 * lieu de recevoir un bloc deja fait. C'est le seul endroit de l'app ou le
 * logotype est a cette taille — il vaut la peine d'etre pose.
 */
function Letter({ char, index }: { char: string; index: number }) {
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withDelay(340 + index * 90, withSpring(1, { damping: 15, stiffness: 170, mass: 0.9 }));
  }, [t, index]);

  const aStyle = useAnimatedStyle(() => ({
    opacity: t.value,
    transform: [{ translateY: reduced ? 0 : (1 - t.value) * 30 }],
  }), [reduced]);

  return (
    <Animated.Text style={[styles.logo, aStyle]}>{char}</Animated.Text>
  );
}

export default function AuthScreen() {
  const router = useRouter();
  const { continueAsGuest } = useAuth();
  const [starting, setStarting] = useState(false);

  // Le filet se trace au lieu de s'allumer : un trait qui apparait d'un bloc
  // n'a pas ete pose par quelqu'un, il a ete affiche.
  const rule = useSharedValue(0);
  useEffect(() => {
    rule.value = withDelay(
      760,
      withTiming(1, { duration: 460, easing: Easing.out(Easing.cubic) }),
    );
  }, [rule]);
  const ruleStyle = useAnimatedStyle(() => ({
    opacity: rule.value > 0 ? 1 : 0,
    transform: [{ scaleX: rule.value }],
  }));

  const startOnboarding = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setStarting(true);
    router.replace("/onboarding");
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Hero */}
      <View style={styles.hero}>
        <FadeIn delay={80} distance={18}>
          <SkynMark size={84} style={{ alignSelf: "center", marginBottom: spacing.l }} />
        </FadeIn>
        <View style={styles.logoRow}>
          {"SKYN".split("").map((letter, i) => (
            <Letter key={i} char={letter} index={i} />
          ))}
        </View>
        <Animated.View style={[styles.hairline, ruleStyle]} />
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
  guestBtn: { alignItems: "center", paddingVertical: spacing.m },
  guestBtnText: {
    fontFamily: fonts.bodyMedium,
    fontSize: 13,
    color: colors.fgMuted,
    textDecorationLine: "underline",
  },
  hero: {
    marginTop: spacing.xxxl + spacing.xxl,
    alignItems: "center",
  },
  logo: {
    fontFamily: fonts.logo,
    fontSize: 62,
    color: colors.fg,
  },
  // La chasse est portee par l'espacement de la rangee, pas par la lettre :
  // ainsi il n'y a pas de gouttiere apres le N, et le mot est centre sans
  // compensation.
  logoRow: { flexDirection: "row", justifyContent: "center", gap: 13 },
  hairline: {
    alignSelf: "center",
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
