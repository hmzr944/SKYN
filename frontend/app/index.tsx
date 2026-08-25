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

import { INTRO_DURATION, MarkIntro } from "@/src/components/brand/MarkIntro";
import { track } from "@/src/services/analytics";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, motion, type } from "@/src/theme";

/** Le mot se pose juste avant que le contour finisse de se refermer. */
const WORD_AT = INTRO_DURATION - 160;

/** Le bloc commence a partir pendant que le mot finit : pas de temps mort. */
const EXIT_AT = WORD_AT + 520;
const EXIT_MS = 260;

/** Le temps que toute la sequence se joue avant de basculer. */
const HOLD = EXIT_AT + EXIT_MS;

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();

  // Les lettres s'ecartent a leur place pendant que le trace se termine :
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
      // gauche, le mot se decale visuellement du symbole a mesure qu'il
      // s'ecarte, et l'ensemble finit desaxe.
      paddingLeft: tracking,
      transform: [{ translateY: (1 - word.value) * 6 }],
    };
  });

  const exitStyle = useAnimatedStyle(() => ({
    opacity: 1 - exit.value,
    transform: [
      { translateY: -exit.value * 18 },
      { scale: 1 - exit.value * 0.03 },
    ],
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
      <Animated.View style={[styles.block, exitStyle]}>
        <MarkIntro size={92} />
        {/* Le dessin deborde de son carre pour laisser entrer le point ;
            on remonte le mot de ce debord pour qu'il reste colle a la marque. */}
        <Animated.Text style={[styles.word, wordStyle]}>SKYN</Animated.Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  block: { alignItems: "center" },
  word: {
    fontFamily: type.wordmark.fontFamily,
    fontSize: 22,
    color: colors.fg,
    marginTop: -20,
  },
});
