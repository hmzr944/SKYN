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
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { childDelay, stagger } from "@/src/animation/motion";
import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { SkynMarkStill } from "@/src/components/brand/SkynMark";
import { useAuth } from "@/src/contexts/AuthContext";

/**
 * Une lettre du mot, qui monte a sa place.
 *
 * Le mot ne s'affiche pas : il se compose. Chaque lettre arrive avec un
 * decalage, de sorte que l'oeil suit la construction de gauche a droite au
 * lieu de recevoir un bloc deja fait. C'est le seul endroit de l'app ou le
 * logotype est a cette taille — il vaut la peine d'etre pose.
 *
 * Le decalage est court. Cet ecran arrive PENDANT que la marque de l'ouverture
 * finit son vol : si le mot mettait une seconde a se construire, on verrait
 * deux constructions successives au lieu d'un seul geste.
 */
function Letter({ char, index }: { char: string; index: number }) {
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withDelay(
      childDelay(index, stagger.letters, 60),
      withSpring(1, { damping: 15, stiffness: 170, mass: 0.9 }),
    );
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
      300,
      withTiming(1, { duration: 420, easing: ease.out }),
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
        {/* La marque ne rejoue RIEN ici : elle est deja tracee, deja a sa
            place. C'est celle de l'ouverture qui vient de se poser exactement
            sur elle — la redessiner ferait clignoter le meme objet et
            annoncerait la couture. */}
        <SkynMarkStill size={84} style={styles.mark} />
        <View style={styles.logoRow}>
          {"SKYN".split("").map((letter, i) => (
            <Letter key={i} char={letter} index={i} />
          ))}
        </View>
        <Animated.View style={[styles.hairline, ruleStyle]} />
        <FadeIn delay={childDelay(0, stagger.blocks, 240)}>
          <Text style={styles.tagline}>{"L'analyse cutanée éditoriale"}</Text>
        </FadeIn>
      </View>

      {/* Actions */}
      <View style={styles.actions}>
        <FadeIn delay={childDelay(1, stagger.blocks, 240)}>
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

        <FadeIn delay={childDelay(2, stagger.blocks, 240)}>
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

        <FadeIn delay={childDelay(3, stagger.blocks, 240)}>
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
  mark: { alignSelf: "center", marginBottom: spacing.l },
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
