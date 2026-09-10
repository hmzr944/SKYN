import * as Haptics from "expo-haptics";
import { ReactNode } from "react";
import {
  Insets,
  LayoutChangeEvent,
  Platform,
  StyleProp,
  StyleSheet,
  ViewStyle,
} from "react-native";
import { Pressable } from "react-native-gesture-handler";
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { motion } from "@/src/theme";

type Props = {
  children: ReactNode;
  onPress?: () => void;
  /** Style de la partie DESSINEE : fond, bordure, rembourrage. */
  style?: StyleProp<ViewStyle>;
  /**
   * Style de la BOITE, celle qui participe a la mise en page du parent.
   *
   * `style` est pose sur la vue interne, celle qui s'enfonce a l'appui : y
   * mettre un `flex` ou une largeur n'a donc aucun effet, puisque c'est la
   * vue EXTERIEURE qui est l'enfant du parent. La distinction n'est pas un
   * detail — un `flex: 1` passe dans `style` est silencieusement ignore, et
   * l'element se dimensionne sur son contenu sans que rien ne le signale.
   */
  containerStyle?: StyleProp<ViewStyle>;
  scaleTo?: number;
  /**
   * Un ecrasement cartoon au lieu du scale uniforme habituel : anticipation
   * (un leger gonflement avant l'appui), ecrasement asymetrique (ca s'aplatit
   * en largeur, pas juste en taille), puis un rebond marque au relachement.
   *
   * RESERVE aux moments de recompense — la capture d'un scan, une case qui se
   * coche, une permission accordee. Partout ailleurs, l'app chuchote ; ce
   * n'est pas le comportement par defaut, il faut le demander explicitement.
   */
  squash?: boolean;
  disabled?: boolean;
  /** Retour haptique a l'appui. Coupe-le pour les elements secondaires. */
  haptic?: false | "light" | "medium" | "success";
  /** Mesure de la boite non transformee — l'echelle d'appui ne la fausse pas. */
  onLayout?: (e: LayoutChangeEvent) => void;
  /**
   * Ce que le lecteur d'ecran annonce. Indispensable des que le contenu n'est
   * pas du texte : un bouton a icone sans libelle s'annonce « bouton », et
   * rien de plus.
   */
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityState?: { selected?: boolean; disabled?: boolean; checked?: boolean };
  /** Par defaut un bouton. A changer pour un onglet ou une case a cocher. */
  accessibilityRole?: "button" | "tab" | "checkbox" | "link" | "switch";
  /** Elargit la zone tactile au-dela du dessin, sans changer le dessin. */
  hitSlop?: number | Insets;
  testID?: string;
};

function tap(kind: NonNullable<Props["haptic"]>) {
  if (Platform.OS === "web") return;
  if (kind === "success") {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    return;
  }
  const style =
    kind === "medium" ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light;
  Haptics.impactAsync(style).catch(() => {});
}

/**
 * L'element s'enfonce a l'appui et revient au ressort.
 *
 * L'enfoncement est immediat (timing court) pour que le doigt sente la reponse
 * sous les 100 ms ; le retour est un ressort, parce que c'est le relachement
 * qui doit paraitre vivant.
 *
 * Il porte AUSSI l'accessibilite de presque toute l'app : c'est le composant
 * par lequel passe chaque bouton. Il ne declarait aucun role, si bien qu'un
 * lecteur d'ecran annonçait du texte la ou il y avait un bouton, et rien du
 * tout sur les boutons a icone. Le role par defaut se declare donc ici, une
 * fois, plutot qu'a chaque appel.
 *
 * ────────────────────────────────────────────────────────────────────────
 * L'ETAT DESACTIVE SE VOIT, MAINTENANT.
 *
 * `disabled` ne faisait qu'ignorer l'appui. Le bouton gardait son opacite
 * pleine, son curseur en main sur le web, et son aspect de bouton : on
 * appuyait, il ne se passait rien, et rien n'expliquait pourquoi. C'est ce
 * qu'on lisait comme « l'app ne repond pas ».
 *
 * L'attenuation se pose donc ici, une fois, au lieu d'etre recopiee a chaque
 * appel — la ou elle etait recopiee, chaque ecran avait choisi sa propre
 * valeur, et deux boutons desactives cote a cote n'avaient pas la meme.
 * ────────────────────────────────────────────────────────────────────────
 */

/** Ce qu'on voit d'un controle hors service. */
const ETEINT = 0.42;

export function AnimatedPressable({
  children,
  onPress,
  style,
  containerStyle,
  scaleTo = 0.96,
  squash = false,
  disabled,
  haptic = "light",
  onLayout,
  accessibilityLabel,
  accessibilityHint,
  accessibilityState,
  accessibilityRole = "button",
  hitSlop,
  testID,
}: Props) {
  const scale = useSharedValue(1);
  // N'existent que pour le mode `squash` — deux axes separes, parce qu'un
  // ecrasement cartoon deforme, il ne redimensionne pas uniformement.
  const sx = useSharedValue(1);
  const sy = useSharedValue(1);
  const reduced = useReducedMotion();

  const aStyle = useAnimatedStyle(() => ({
    transform: squash ? [{ scaleX: sx.value }, { scaleY: sy.value }] : [{ scale: scale.value }],
  }));

  return (
    <Pressable
      testID={testID}
      style={containerStyle as never}
      onPress={onPress}
      onLayout={onLayout}
      disabled={disabled}
      hitSlop={hitSlop}
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!disabled, ...accessibilityState }}
      // `accessibilityState` ne descend pas jusqu'aux attributs ARIA sur le
      // web : mesure faite, `aria-disabled` restait vide et un lecteur d'ecran
      // annoncait un bouton ordinaire la ou il n'y avait plus d'action. Pose a
      // la main, en plus de la prop native.
      aria-disabled={!!disabled || accessibilityState?.disabled}
      onPressIn={() => {
        if (haptic) tap(haptic);
        if (squash && !reduced) {
          // Anticipation : un leger etirement vers le haut avant l'ecrasement,
          // comme un ressort qu'on arme en sens inverse. Puis ca s'aplatit —
          // plus large, moins haut, comme presse du doigt — jamais l'inverse,
          // sinon on lit un pincement, pas un ecrasement.
          sx.value = withSequence(
            withTiming(0.96, { duration: 55, easing: ease.out }),
            withTiming(1.14, { duration: 90, easing: ease.in }),
          );
          sy.value = withSequence(
            withTiming(1.05, { duration: 55, easing: ease.out }),
            withTiming(0.88, { duration: 90, easing: ease.in }),
          );
        } else if (squash) {
          sx.value = withTiming(scaleTo, { duration: motion.instant });
          sy.value = withTiming(scaleTo, { duration: motion.instant });
        } else {
          scale.value = withTiming(scaleTo, { duration: motion.instant });
        }
      }}
      onPressOut={() => {
        if (squash) {
          sx.value = withSpring(1, reduced ? motion.springPress : motion.springCartoon);
          sy.value = withSpring(1, reduced ? motion.springPress : motion.springCartoon);
        } else {
          scale.value = withSpring(1, motion.springPress);
        }
      }}
    >
      <Animated.View style={[style, aStyle, disabled && styles.eteint]}>{children}</Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  eteint: {
    opacity: ETEINT,
    // Sur le web, le curseur est la moitie de l'information : une main au
    // dessus d'un bouton mort promet une action qui n'arrivera pas.
    //
    // React Native ne connait que « auto » et « pointer » ; « not-allowed » est
    // un curseur du web, que react-native-web transmet tel quel. La conversion
    // est donc explicite plutot que subie.
    ...(Platform.OS === "web" ? ({ cursor: "not-allowed" } as unknown as ViewStyle) : null),
  },
});
