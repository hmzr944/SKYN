import { useEffect } from "react";
import { Image, ImageSourcePropType, StyleSheet, View } from "react-native";
import Svg, {
  Circle,
  Defs,
  Ellipse,
  LinearGradient,
  Path,
  Rect,
  Stop,
} from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { duration, spring } from "@/src/animation/motion";
import { colors, palette } from "@/src/theme";

/**
 * La figure ronde de l'onboarding.
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QU'ELLE EMPRUNTE A LA REFERENCE, ET CE QU'ELLE EN CHANGE.
 *
 * La reference pose un disque photographique traverse par un filet elliptique
 * tres fin, avec une petite etoile a quatre branches en accent. C'est ce
 * vocabulaire qui est repris : un rond, une orbite, une scintille.
 *
 * Ce qui change, c'est la matiere. La reference remplit le disque d'une photo ;
 * ici il peut aussi contenir une MATIERE DESSINEE — trois galets translucides
 * qui se recouvrent, comme des depots de serum sur une plaque. C'est plus
 * leger qu'une image, ca ne se pixellise jamais, et surtout ca BOUGE : les
 * bulles montent, l'orbite tourne. Une photo est un objet mort dans un ecran ;
 * une matiere qui derive donne l'impression que l'app respire.
 *
 * Le disque photo reste disponible : passe une source et elle prend la place.
 * ────────────────────────────────────────────────────────────────────────
 */

/** L'etoile a quatre branches, dessinee a partir de son centre. */
function etoile(cx: number, cy: number, r: number, creux = 0.28) {
  const k = r * creux;
  return (
    `M${cx},${cy - r} C${cx + k},${cy - k} ${cx + k},${cy - k} ${cx + r},${cy} ` +
    `C${cx + k},${cy + k} ${cx + k},${cy + k} ${cx},${cy + r} ` +
    `C${cx - k},${cy + k} ${cx - k},${cy + k} ${cx - r},${cy} ` +
    `C${cx - k},${cy - k} ${cx - k},${cy - k} ${cx},${cy - r} Z`
  );
}

/** Une bulle qui derive dans la matiere. */
function Bulle({
  cx,
  cy,
  r,
  delai,
  reduced,
}: {
  cx: number;
  cy: number;
  r: number;
  delai: number;
  reduced: boolean;
}) {
  const t = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    // Une derive lente et sans fin. Chaque bulle a sa propre periode, sinon
    // elles montent au garde-a-vous et on voit la machine.
    t.value = withDelay(
      delai,
      withRepeat(
        withTiming(1, { duration: 5200 + delai * 6, easing: Easing.inOut(Easing.quad) }),
        -1,
        true,
      ),
    );
  }, [t, delai, reduced]);

  const aProps = useAnimatedStyle(() => ({
    transform: [{ translateY: -t.value * 5 }, { translateX: t.value * 2 }],
    opacity: 0.5 + t.value * 0.35,
  }));

  return (
    <Animated.View style={[StyleSheet.absoluteFill, aProps]} pointerEvents="none">
      <Svg width="100%" height="100%" viewBox="0 0 100 100">
        <Circle cx={cx} cy={cy} r={r} fill={palette.creme} opacity={0.55} />
        <Circle cx={cx - r * 0.3} cy={cy - r * 0.3} r={r * 0.34} fill={palette.creme} />
      </Svg>
    </Animated.View>
  );
}

/**
 * Trois galets translucides qui se recouvrent.
 *
 * Les teintes sortent toutes de la palette : creme, corail, terre. Aucune
 * couleur nouvelle n'entre par la petite porte — c'est ce qui fait qu'une
 * illustration appartient a une app plutot que de s'y poser.
 */
export function Matiere({ variante = 0 }: { variante?: number }) {
  const reduced = useReducedMotion();
  const decale = variante * 7;

  return (
    <View style={StyleSheet.absoluteFill}>
      <Svg width="100%" height="100%" viewBox="0 0 100 100">
        {/* Aucun contenant. La reference ne montre pas une boule remplie de
            matiere : elle montre trois coupelles posees sur le fond, qu'on
            reconnait a leurs bords et a leurs recouvrements. Un disque plein
            derriere elles les aplatissait en une seule tache.

            Les trois depots.
            Les remplissages restent tres bas et ce sont les LISIERES qui
            portent la lecture. Une matiere translucide se reconnait a son bord,
            pas a sa couleur : en remontant les fonds, les trois galets se
            confondaient en une seule tache rose et on ne voyait plus qu'un
            aplat. Ici on lit trois epaisseurs qui se recouvrent. */}
        <Circle cx={31 + decale} cy={52} r={27} fill={colors.accent} opacity={0.13} />
        <Circle cx={50} cy={44 - decale * 0.4} r={29} fill={palette.creme} opacity={0.72} />
        <Circle cx={50} cy={44 - decale * 0.4} r={29} fill={palette.terre} opacity={0.05} />
        <Circle cx={70 - decale} cy={56} r={25} fill={colors.accent} opacity={0.1} />

        <Circle cx={31 + decale} cy={52} r={27} fill="none" stroke={colors.accent} strokeWidth={0.7} opacity={0.5} />
        <Circle cx={50} cy={44 - decale * 0.4} r={29} fill="none" stroke={palette.terre} strokeWidth={0.6} opacity={0.26} />
        <Circle cx={70 - decale} cy={56} r={25} fill="none" stroke={colors.accent} strokeWidth={0.7} opacity={0.42} />

        {/* Le reflet, sur le galet du milieu : une matiere sans lumiere est un
            aplat. */}
        <Circle cx={41} cy={31} r={8} fill={palette.creme} opacity={0.75} />
      </Svg>

      <Bulle cx={40} cy={46} r={3.4} delai={0} reduced={reduced} />
      <Bulle cx={62} cy={62} r={2.2} delai={420} reduced={reduced} />
      <Bulle cx={54} cy={34} r={1.6} delai={900} reduced={reduced} />
      <Bulle cx={72} cy={48} r={2.8} delai={1300} reduced={reduced} />
    </View>
  );
}

export function Figure({
  size,
  source,
  variante = 0,
  delay = 0,
}: {
  size: number;
  /** Une photo. Sans elle, le disque contient la matiere dessinee. */
  source?: ImageSourcePropType | null;
  variante?: number;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  const pose = useSharedValue(0);
  const tour = useSharedValue(0);
  const eclat = useSharedValue(0);

  // L'orbite deborde du disque : c'est ce debord qui donne la profondeur.
  // Le facteur reste modeste — l'ellipse tourne, et une boite qui tourne
  // occupe la diagonale de son carre, pas son cote.
  const boite = size * 1.26;

  useEffect(() => {
    if (reduced) {
      pose.value = 1;
      eclat.value = 1;
      return;
    }
    pose.value = withDelay(delay, withSpring(1, spring.gentle));
    // Une rotation lente et continue. Pas une boucle d'effet : une orbite.
    // Trop rapide, elle attire l'oeil au lieu de l'accompagner.
    tour.value = withRepeat(withTiming(1, { duration: 21000, easing: Easing.linear }), -1, false);
    eclat.value = withDelay(
      delay + 420,
      withRepeat(
        withSequence(
          withTiming(1, { duration: duration.slow, easing: ease.out }),
          withTiming(0.55, { duration: 1400, easing: ease.sineInOut }),
          withTiming(1, { duration: 1400, easing: ease.sineInOut }),
        ),
        -1,
        true,
      ),
    );
  }, [delay, reduced, pose, tour, eclat]);

  const disque = useAnimatedStyle(() => ({
    opacity: pose.value,
    transform: [{ scale: 0.86 + pose.value * 0.14 }],
  }));

  const orbite = useAnimatedStyle(() => ({
    opacity: pose.value * 0.9,
    transform: [{ rotate: `${tour.value * 360}deg` }],
  }));

  const scintille = useAnimatedStyle(() => ({
    opacity: eclat.value,
    transform: [{ scale: 0.7 + eclat.value * 0.3 }, { rotate: `${eclat.value * 18}deg` }],
  }));

  return (
    <View style={{ width: boite, height: boite, alignItems: "center", justifyContent: "center" }}>
      {/* L'orbite : une ellipse tres fine, inclinee, qui tourne sans fin. */}
      <Animated.View style={[StyleSheet.absoluteFill, orbite]} pointerEvents="none">
        <Svg width="100%" height="100%" viewBox="0 0 100 100">
          <Ellipse
            cx={50}
            cy={50}
            rx={48}
            ry={31}
            fill="none"
            stroke={colors.accentLine}
            strokeWidth={0.42}
            transform="rotate(-24 50 50)"
          />
        </Svg>
      </Animated.View>

      <Animated.View
        style={[
          source
            ? {
                width: size,
                height: size,
                borderRadius: size / 2,
                overflow: "hidden",
                backgroundColor: colors.accentSofter,
              }
            : // La matiere n'a pas de contenant : elle occupe la boite, bords
              // compris, et c'est le fond de la page qui passe entre les
              // galets. Un masque rond ici en referait une pastille.
              { width: boite, height: boite },
          disque,
        ]}
      >
        {source ? (
          <Image source={source} style={styles.photo} resizeMode="cover" />
        ) : (
          <Matiere variante={variante} />
        )}
      </Animated.View>

      {/* La scintille, posee sur la lisiere haute du disque. */}
      <Animated.View
        style={[styles.scintille, { top: boite * 0.12, right: boite * 0.1 }, scintille]}
        pointerEvents="none"
      >
        <Svg width={26} height={26} viewBox="0 0 26 26">
          <Path d={etoile(13, 13, 12)} fill={colors.accent} />
        </Svg>
      </Animated.View>
    </View>
  );
}

/**
 * La meme matiere, mais sur toute la page et sur fond terre.
 *
 * C'est l'ecran « pleine page » de la reference : une image qui occupe tout,
 * un titre en creme par dessus. Le fond sombre n'est pas un effet de style,
 * c'est ce qui garantit le contraste du titre — creme sur terre est la paire
 * inversee de l'app, deja mesuree.
 */
export function MatiereEntiere() {
  const reduced = useReducedMotion();
  const derive = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    derive.value = withRepeat(
      withTiming(1, { duration: 14000, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [derive, reduced]);

  const a = useAnimatedStyle(() => ({ transform: [{ translateX: derive.value * 16 - 8 }] }));
  const b = useAnimatedStyle(() => ({ transform: [{ translateX: 6 - derive.value * 14 }] }));

  return (
    <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.inverse }]}>
      {/* Les galets occupent le HAUT. Le titre vient se poser dans le bas, et
          il ne doit jamais avoir a se battre avec un bord de disque : le
          contraste du texte se garantit par la composition, pas par un espoir. */}
      <Animated.View style={[StyleSheet.absoluteFill, a]}>
        <Svg width="100%" height="100%" viewBox="0 0 100 216" preserveAspectRatio="xMidYMid slice">
          <Circle cx={30} cy={56} r={25} fill={colors.accent} opacity={0.2} />
          <Circle cx={30} cy={56} r={25} fill="none" stroke={colors.accent} strokeWidth={0.35} opacity={0.55} />
          <Circle cx={78} cy={96} r={19} fill={palette.creme} opacity={0.06} />
          <Circle cx={78} cy={96} r={19} fill="none" stroke={palette.creme} strokeWidth={0.3} opacity={0.26} />
        </Svg>
      </Animated.View>
      <Animated.View style={[StyleSheet.absoluteFill, b]}>
        <Svg width="100%" height="100%" viewBox="0 0 100 216" preserveAspectRatio="xMidYMid slice">
          <Circle cx={66} cy={46} r={22} fill={palette.creme} opacity={0.09} />
          <Circle cx={66} cy={46} r={22} fill="none" stroke={palette.creme} strokeWidth={0.3} opacity={0.32} />
          <Circle cx={22} cy={104} r={15} fill={colors.accent} opacity={0.14} />
          <Circle cx={22} cy={104} r={15} fill="none" stroke={colors.accent} strokeWidth={0.3} opacity={0.4} />
        </Svg>
      </Animated.View>

      {/* Le voile. Meme avec les galets en haut, une lisiere peut descendre :
          ce degrade rend le bas franchement opaque, donc le titre creme y est
          toujours a son contraste mesure sur terre pleine. */}
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        <Svg width="100%" height="100%" preserveAspectRatio="none" viewBox="0 0 10 100">
          <Defs>
            <LinearGradient id="voile" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={palette.terre} stopOpacity={0} />
              <Stop offset="0.42" stopColor={palette.terre} stopOpacity={0.55} />
              <Stop offset="0.68" stopColor={palette.terre} stopOpacity={0.94} />
              <Stop offset="1" stopColor={palette.terre} stopOpacity={1} />
            </LinearGradient>
          </Defs>
          <Rect x={0} y={0} width={10} height={100} fill="url(#voile)" />
        </Svg>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  photo: { width: "100%", height: "100%" },
  scintille: { position: "absolute" },
});
