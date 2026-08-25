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

import { INTRO_DURATION, WaveIntro } from "@/src/components/brand/WaveIntro";
import { track } from "@/src/services/analytics";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, motion, type } from "@/src/theme";

/** Le mot se pose une fois le S deroule, pas pendant. */
const WORD_AT = INTRO_DURATION - 480;

/** Le bloc part pendant que le mot finit : pas de temps mort. */
const EXIT_AT = INTRO_DURATION - 60;
const EXIT_MS = 280;
const HOLD = EXIT_AT + EXIT_MS;

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();

  // Les lettres s'ecartent a leur place pendant que la maree se retire :
  // le mot se pose, il n'apparait pas.
  const word = useSharedValue(0);
  // Le bloc entier s'eleve et s'efface : l'ecran suivant prend sa suite au
  // lieu de le remplacer d'un coup.
  const exit = useSharedValue(0);

  useEffect(() => {
    track("app_opened");
  }, []);

  useEffect(() => {
    word.value = withDelay(
      WORD_AT,
      withTiming(1, { duration: motion.slow, easing: Easing.out(Easing.cubic) }),
    );
    exit.value = withDelay(
      EXIT_AT,
      withTiming(1, { duration: EXIT_MS, easing: Easing.in(Easing.cubic) }),
    );
  }, [word, exit]);

  const wordStyle = useAnimatedStyle(() => {
    const tracking = 3 + word.value * 8;
    return {
      opacity: word.value,
      letterSpacing: tracking,
      // La chasse ajoute une gouttiere APRES le N : sans compensation a
      // gauche, le mot se decale du symbole a mesure qu'il s'ecarte.
      paddingLeft: tracking,
      transform: [{ translateY: (1 - word.value) * 8 }],
    };
  });

  const exitStyle = useAnimatedStyle(() => ({
    opacity: 1 - exit.value,
    transform: [{ translateY: -exit.value * 20 }, { scale: 1 - exit.value * 0.04 }],
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
    <Animated.View style={[styles.container, exitStyle]} testID="splash-screen">
      <WaveIntro markSize={96} />
      <View style={styles.wordSlot} pointerEvents="none">
        <Animated.Text style={[styles.word, wordStyle]}>SKYN</Animated.Text>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  // Le mot vit sous le symbole, qui est centre dans tout l'ecran : on le pose
  // dans la moitie basse plutot que de le coller au dessin.
  wordSlot: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 138,
  },
  word: {
    fontFamily: type.wordmark.fontFamily,
    fontSize: 22,
    color: colors.fg,
  },
});
