import { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  NativeSyntheticEvent,
  NativeScrollEvent,
  ActivityIndicator,
  Platform,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { storage } from "@/src/utils/storage";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { GoogleLogo } from "@/src/components/icons/GoogleLogo";
import { useProviderAuth } from "@/src/hooks/useProviderAuth";
import {
  PromiseIllustration,
  TechIllustration,
  PrivacyIllustration,
  CaptureIllustration,
} from "@/src/components/illustrations/OnboardingIllustrations";

const PAGE_COUNT = 5;
const CONTENT_MAX_W = 480;

const SLIDES = [
  {
    title: "Votre peau,\ndécryptée.",
    helper:
      "SKYN analyse votre peau en quelques secondes et vous révèle ce qu'elle a vraiment à dire.",
  },
  {
    Illustration: PromiseIllustration,
    title: "Un diagnostic\nqui vous ressemble",
    helper:
      "Calibré sur votre âge, votre environnement et vos priorités pour des recommandations vraiment personnalisées.",
  },
  {
    Illustration: TechIllustration,
    title: "Une technologie\nde pointe",
    helper:
      "Notre moteur cartographie votre peau zone par zone et détecte les micro-patterns invisibles à l'œil nu.",
  },
  {
    Illustration: PrivacyIllustration,
    title: "Vos données\nvous appartiennent",
    helper:
      "Vos photos sont analysées puis immédiatement supprimées. Rien n'est partagé, rien n'est conservé.",
  },
  {
    Illustration: CaptureIllustration,
    title: "Prêt à découvrir\nvotre peau ?",
    helper: "Créez votre dossier cutané chiffré pour commencer votre premier bilan.",
  },
] as const;

export default function OnboardingScreen() {
  const { width: SCREEN_W, height: SCREEN_H } = useWindowDimensions();
  const scrollRef = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const { busy, error, handleGoogle } = useProviderAuth();
  const isNarrow = SCREEN_W < 380;
  const isShort = SCREEN_H < 700;
  const horizontalPadding = isNarrow ? spacing.m : spacing.xl;
  const illustrationSize = isShort ? 116 : isNarrow ? 136 : 160;
  const titleSize = isShort || isNarrow ? 30 : 36;
  const titleLineHeight = isShort || isNarrow ? 35 : 42;

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

  const goToPage = (p: number) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    scrollRef.current?.scrollTo({ x: p * SCREEN_W, animated: true });
    setPage(p);
  };

  const onMomentumEnd = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const p = Math.round(e.nativeEvent.contentOffset.x / SCREEN_W);
    if (p !== page) {
      setPage(p);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }
  };

  const finishOnboarding = () => storage.setItem("skyn_onboarding_seen", "1");

  const isLast = page === PAGE_COUNT - 1;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Decorative animated blobs */}
      <Animated.View style={[styles.blob, styles.blobA, blobStyleA]} pointerEvents="none">
        <LinearGradient
          colors={[colors.accent, "rgba(255,77,109,0)"]}
          style={styles.blobFill}
          start={{ x: 0.3, y: 0.2 }}
          end={{ x: 1, y: 1 }}
        />
      </Animated.View>
      <Animated.View style={[styles.blob, styles.blobB, blobStyleB]} pointerEvents="none">
        <LinearGradient
          colors={[colors.lime, "rgba(200,240,74,0)"]}
          style={styles.blobFill}
          start={{ x: 0.2, y: 0.2 }}
          end={{ x: 1, y: 1 }}
        />
      </Animated.View>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.wordmark}>SKYN</Text>
        {page === 0 ? (
          <TouchableOpacity
            testID="onboarding-signin-link"
            onPress={() => {
              finishOnboarding();
              goToPage(PAGE_COUNT - 1);
            }}
            hitSlop={8}
          >
            <Text style={styles.skip}>Déjà un compte ?</Text>
          </TouchableOpacity>
        ) : !isLast ? (
          <TouchableOpacity
            testID="onboarding-skip-btn"
            onPress={() => {
              finishOnboarding();
              goToPage(PAGE_COUNT - 1);
            }}
            hitSlop={8}
          >
            <Text style={styles.skip}>Passer</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ height: 18 }} />
        )}
      </View>

      {/* Pages */}
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onMomentumEnd}
        scrollEnabled={false}
      >
        {SLIDES.map((slide, i) => {
          const Illustration = "Illustration" in slide ? slide.Illustration : null;
          return (
            <View key={i} style={[styles.page, { width: SCREEN_W }]}>
              <View
                style={[
                  styles.pageContent,
                  {
                    maxWidth: CONTENT_MAX_W,
                    paddingHorizontal: horizontalPadding,
                    paddingVertical: isShort ? spacing.s : spacing.m,
                  },
                ]}
              >
                {Illustration ? (
                  <FadeIn distance={16}>
                    <View
                      style={[
                        styles.illustration,
                        {
                          width: illustrationSize,
                          height: illustrationSize,
                          marginBottom: isShort ? spacing.s : spacing.m,
                        },
                      ]}
                    >
                      <Illustration />
                    </View>
                  </FadeIn>
                ) : (
                  <FadeIn distance={16}>
                    <View
                      style={[
                        styles.hairlineWrap,
                        {
                          height: illustrationSize,
                          marginBottom: isShort ? spacing.s : spacing.m,
                        },
                      ]}
                    >
                      <View style={styles.hairline} />
                    </View>
                  </FadeIn>
                )}
                <FadeIn delay={60} distance={16}>
                  <Text style={[styles.title, { fontSize: titleSize, lineHeight: titleLineHeight }]}>
                    {slide.title}
                  </Text>
                </FadeIn>
                <FadeIn delay={120}>
                  <Text
                    style={[
                      styles.helper,
                      {
                        fontSize: isShort ? 14 : 15,
                        lineHeight: isShort ? 20 : 22,
                        marginTop: isShort ? spacing.s : spacing.m,
                      },
                    ]}
                  >
                    {slide.helper}
                  </Text>
                </FadeIn>

                {i === PAGE_COUNT - 1 ? (
                  <FadeIn delay={200} distance={10}>
                    <View style={[styles.authBlock, { marginTop: isShort ? spacing.m : spacing.xl }]}>
                      {error ? (
                        <View style={styles.errorBadge}>
                          <Text style={styles.error} testID="onboarding-auth-error">
                            {error}
                          </Text>
                        </View>
                      ) : null}

                      <AnimatedPressable
                        testID="onboarding-google-button"
                        style={[styles.googleBtn, busy !== null && styles.btnDisabled]}
                        onPress={() => {
                          finishOnboarding();
                          handleGoogle();
                        }}
                        disabled={busy !== null}
                      >
                        <View style={styles.googleBtnInner}>
                          {busy === "google" ? (
                            <ActivityIndicator color={colors.fg} size="small" />
                          ) : (
                            <>
                              <GoogleLogo size={20} />
                              <Text style={styles.googleBtnText}>Continuer avec Google</Text>
                            </>
                          )}
                        </View>
                      </AnimatedPressable>

                      <Text style={styles.gdpr} testID="onboarding-gdpr">
                        En continuant, vous créez votre dossier cutané chiffré. Vos photos
                        sont analysées puis immédiatement supprimées.
                      </Text>
                    </View>
                  </FadeIn>
                ) : null}
              </View>
            </View>
          );
        })}
      </ScrollView>

      {/* Footer */}
      {!isLast ? (
        <View
          style={[
            styles.footer,
            {
              paddingHorizontal: horizontalPadding,
              paddingTop: isShort ? spacing.s : spacing.m,
              paddingBottom:
                Platform.OS === "ios"
                  ? isShort
                    ? spacing.m
                    : spacing.l
                  : isShort
                    ? spacing.m
                    : spacing.xl,
            },
          ]}
        >
          {page > 0 ? (
            <TouchableOpacity
              testID="onboarding-back-btn"
              onPress={() => goToPage(page - 1)}
              style={styles.backBtn}
              activeOpacity={0.6}
            >
              <Text style={styles.backText}>← Retour</Text>
            </TouchableOpacity>
          ) : (
            <View style={{ width: 80 }} />
          )}

          <View style={styles.dotsRow}>
            {Array.from({ length: PAGE_COUNT }).map((_, i) => (
              <View key={i} style={[styles.dot, page === i && styles.dotActive]} />
            ))}
          </View>

          <AnimatedPressable
            testID="onboarding-next-btn"
            onPress={() => goToPage(page + 1)}
            style={[
              styles.nextBtn,
              {
                minWidth: isNarrow ? 104 : 120,
                paddingHorizontal: isNarrow ? spacing.l : spacing.xl,
                paddingVertical: isShort ? 14 : 16,
              },
            ]}
          >
            <Text style={styles.nextText}>Suivant</Text>
          </AnimatedPressable>
        </View>
      ) : (
        <View
          style={[
            styles.footerDots,
            {
              paddingTop: isShort ? spacing.s : spacing.m,
              paddingBottom:
                Platform.OS === "ios"
                  ? isShort
                    ? spacing.m
                    : spacing.l
                  : isShort
                    ? spacing.m
                    : spacing.xl,
            },
          ]}
        >
          {Array.from({ length: PAGE_COUNT }).map((_, i) => (
            <View key={i} style={[styles.dot, page === i && styles.dotActive]} />
          ))}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, overflow: "hidden" },
  blob: { position: "absolute", borderRadius: 999, overflow: "hidden" },
  blobFill: { flex: 1, borderRadius: 999 },
  blobA: { width: 280, height: 280, top: -80, right: -90, opacity: 0.3 },
  blobB: { width: 240, height: 240, bottom: 60, left: -100, opacity: 0.25 },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.xs,
    minHeight: 36,
  },
  wordmark: {
    fontFamily: fonts.logo,
    fontSize: 18,
    color: colors.fg,
    letterSpacing: 6,
  },
  skip: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgDim,
  },
  page: {
    alignItems: "center",
    justifyContent: "center",
  },
  pageContent: {
    width: "100%",
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    alignSelf: "center",
  },
  illustration: {
    width: 160,
    height: 160,
    marginBottom: spacing.m,
    alignItems: "center",
    justifyContent: "center",
  },
  hairlineWrap: {
    height: 160,
    marginBottom: spacing.m,
    alignItems: "center",
    justifyContent: "center",
  },
  hairline: {
    width: 64,
    height: 2,
    backgroundColor: colors.accent,
    borderRadius: 1,
  },
  title: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 36,
    lineHeight: 42,
    letterSpacing: -0.5,
    textAlign: "center",
  },
  helper: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 15,
    marginTop: spacing.m,
    lineHeight: 22,
    textAlign: "center",
  },
  authBlock: { marginTop: spacing.xl, width: "100%", gap: spacing.m },
  errorBadge: {
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.sm,
    paddingVertical: spacing.s,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.surface,
  },
  error: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 0.5,
    textAlign: "center",
  },
  btnDisabled: { opacity: 0.6 },
  googleBtn: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: 16,
    alignItems: "center",
    borderRadius: radius.pill,
    ...shadow.card,
  },
  googleBtnInner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    minHeight: 22,
  },
  googleBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 14,
    letterSpacing: 0.3,
  },
  gdpr: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
    paddingHorizontal: spacing.s,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingBottom: Platform.OS === "ios" ? spacing.l : spacing.xl,
    paddingTop: spacing.m,
    gap: spacing.s,
  },
  footerDots: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 6,
    paddingBottom: Platform.OS === "ios" ? spacing.l : spacing.xl,
    paddingTop: spacing.m,
  },
  backBtn: { paddingVertical: 12, paddingRight: spacing.m },
  backText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    letterSpacing: 0.5,
  },
  dotsRow: { flexDirection: "row", gap: 6 },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.borderMid,
  },
  dotActive: { backgroundColor: colors.accent, width: 20 },
  nextBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: 32,
    paddingVertical: 16,
    borderRadius: radius.pill,
    minWidth: 120,
    alignItems: "center",
    ...shadow.button,
  },
  nextText: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
});
