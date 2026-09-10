import { useEffect } from "react";
import { Image, ImageSourcePropType, StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import Svg, { Path } from "react-native-svg";

import { colors, motion } from "@/src/theme";
import { onboardingPalette } from "@/src/theme/onboardingPalette";

/**
 * La grille bento du premier ecran.
 *
 * Remplace le disque unique (voir Figure.tsx, toujours utilise sur les
 * pages sans photo) par plusieurs tuiles RECTANGULAIRES a coins arrondis —
 * la demande explicite apres le premier passage : pas de rond, du contenu
 * photo reel, de la couleur, et une interface qui bouge vraiment plutot
 * qu'un simple fondu d'entree.
 *
 * Chaque tuile-photo derive lentement en echelle (Ken Burns) en continu,
 * independamment de son entree — une photo fixe dans une appli qui bouge
 * partout ailleurs se voit, et se lit comme un import brut plutot que comme
 * une image "vivante".
 */

const RAYON = 24;

function KenBurns({ children }: { children: React.ReactNode }) {
  const reduced = useReducedMotion();
  const s = useSharedValue(1);

  useEffect(() => {
    if (reduced) return;
    s.value = withRepeat(
      withTiming(1.09, { duration: 9000, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [reduced, s]);

  const aStyle = useAnimatedStyle(() => ({ transform: [{ scale: s.value }] }));

  return <Animated.View style={[StyleSheet.absoluteFill, aStyle]}>{children}</Animated.View>;
}

type TileProps = {
  delay: number;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
};

/** Une tuile qui se pose en ressort, decalee de ses voisines — jamais toutes
 * a la fois, sinon la grille apparait comme une seule image decoupee. */
function Tile({ delay, style, children }: TileProps) {
  const reduced = useReducedMotion();
  const t = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      t.value = 1;
      return;
    }
    t.value = withDelay(delay, withSpring(1, motion.springDrop));
  }, [delay, reduced, t]);

  const aStyle = useAnimatedStyle(() => ({
    opacity: Math.min(1, t.value),
    transform: [
      { scale: 0.88 + Math.min(1, t.value) * 0.12 },
      { translateY: (1 - Math.min(1, t.value)) * 18 },
    ],
  }));

  return (
    <Animated.View style={[styles.tile, style, aStyle]}>
      {children}
    </Animated.View>
  );
}

function PhotoTile({
  source,
  delay,
  style,
}: {
  source: ImageSourcePropType;
  delay: number;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Tile delay={delay} style={style}>
      <KenBurns>
        <Image source={source} style={styles.photo} resizeMode="cover" />
      </KenBurns>
    </Tile>
  );
}

/** L'etoile a quatre branches, reprise de Figure.tsx — meme vocabulaire de
 * marque, pas un second symbole invente pour la grille. */
function etoile(cx: number, cy: number, r: number, creux = 0.28) {
  const k = r * creux;
  return (
    `M${cx},${cy - r} C${cx + k},${cy - k} ${cx + k},${cy - k} ${cx + r},${cy} ` +
    `C${cx + k},${cy + k} ${cx + k},${cy + k} ${cx},${cy + r} ` +
    `C${cx - k},${cy + k} ${cx - k},${cy + k} ${cx - r},${cy} ` +
    `C${cx - k},${cy - k} ${cx - k},${cy - k} ${cx},${cy - r} Z`
  );
}

/** La tuile de couleur, pour que la grille ne soit pas QUE des photos — un
 * chiffre du produit, sur un aplat pastel derive de la photo (voir
 * onboardingPalette). */
function StatTile({ value, label, delay, style }: { value: string; label: string; delay: number; style?: StyleProp<ViewStyle> }) {
  const reduced = useReducedMotion();
  const eclat = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      eclat.value = 1;
      return;
    }
    eclat.value = withDelay(
      delay + 500,
      withRepeat(withTiming(1, { duration: 1800, easing: Easing.inOut(Easing.sin) }), -1, true),
    );
  }, [delay, reduced, eclat]);

  const scintille = useAnimatedStyle(() => ({
    opacity: 0.5 + eclat.value * 0.5,
    transform: [{ scale: 0.85 + eclat.value * 0.25 }],
  }));

  return (
    <Tile delay={delay} style={[style, { backgroundColor: onboardingPalette.blush }]}>
      <View style={styles.statInner}>
        <Animated.View style={[styles.statSpark, scintille]}>
          <Svg width={16} height={16} viewBox="0 0 26 26">
            <Path d={etoile(13, 13, 11)} fill={colors.accent} />
          </Svg>
        </Animated.View>
        <Animated.Text style={styles.statValue}>{value}</Animated.Text>
        <Animated.Text style={styles.statLabel}>{label}</Animated.Text>
      </View>
    </Tile>
  );
}

export function BentoGrid({
  hero,
  joy,
  hand,
  delay = 0,
}: {
  hero: ImageSourcePropType;
  joy: ImageSourcePropType;
  hand: ImageSourcePropType;
  delay?: number;
}) {
  return (
    <View style={styles.grid}>
      <PhotoTile source={hero} delay={delay} style={styles.big} />
      <View style={styles.row}>
        <PhotoTile source={joy} delay={delay + 90} style={styles.small} />
        <PhotoTile source={hand} delay={delay + 150} style={styles.small} />
        <StatTile value="13" label={"zones\nsuivies"} delay={delay + 210} style={styles.small} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { width: "100%", gap: 10 },
  row: { flexDirection: "row", gap: 10 },
  tile: {
    borderRadius: RAYON,
    overflow: "hidden",
    backgroundColor: onboardingPalette.sable,
  },
  big: { width: "100%", height: 176 },
  small: { flex: 1, height: 104 },
  photo: { width: "100%", height: "100%" },
  statInner: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 6,
  },
  statSpark: { position: "absolute", top: 8, right: 10 },
  statValue: {
    fontFamily: "Fraunces_600SemiBold",
    fontSize: 26,
    color: colors.accent,
    letterSpacing: -0.5,
  },
  statLabel: {
    fontFamily: "Outfit_500Medium",
    fontSize: 10,
    letterSpacing: 0.6,
    textTransform: "uppercase",
    color: colors.accent,
    textAlign: "center",
    marginTop: 2,
    opacity: 0.82,
  },
});
