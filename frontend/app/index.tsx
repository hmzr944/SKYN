import { useRouter } from "expo-router";
import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, { useAnimatedStyle } from "react-native-reanimated";

import { useIntroTimeline } from "@/src/animation/introTimeline";
import { WaveIntro } from "@/src/components/brand/WaveIntro";
import { track } from "@/src/services/analytics";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, type } from "@/src/theme";

/**
 * L'ecran d'ouverture.
 *
 * Il ne contient plus aucun retard : la sequence entiere vit dans la timeline
 * d'ouverture, qui rend aussi sa duree. C'est cette duree qui decide du moment
 * de la bascule — elle etait auparavant recopiee a la main a cote, et se
 * desynchronisait au premier reglage.
 */
export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();
  const { valeurs, duree } = useIntroTimeline();

  useEffect(() => {
    track("app_opened");
  }, []);

  const wordStyle = useAnimatedStyle(() => {
    const chasse = 3 + valeurs.word.value * 8;
    return {
      opacity: valeurs.word.value,
      letterSpacing: chasse,
      // La chasse ajoute une gouttiere APRES le N : sans compensation a
      // gauche, le mot se decale du symbole a mesure qu'il s'ecarte.
      paddingLeft: chasse,
      transform: [{ translateY: (1 - valeurs.word.value) * 8 }],
    };
  });

  const exitStyle = useAnimatedStyle(() => ({
    opacity: 1 - valeurs.exit.value,
    transform: [
      { translateY: -valeurs.exit.value * 20 },
      { scale: 1 - valeurs.exit.value * 0.04 },
    ],
  }));

  useEffect(() => {
    if (loading) return;
    let annule = false;
    const t = setTimeout(() => {
      if (annule) return;
      if (!user) {
        router.replace("/auth");
      } else if (!profile?.onboarded) {
        router.replace("/profile-setup");
      } else {
        router.replace("/dashboard");
      }
    }, Math.round(duree * 1000));
    return () => {
      annule = true;
      clearTimeout(t);
    };
  }, [loading, user, profile, router, duree]);

  return (
    <Animated.View style={[styles.container, exitStyle]} testID="splash-screen">
      <WaveIntro values={valeurs} markSize={96} />
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
