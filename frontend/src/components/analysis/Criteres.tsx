import { useEffect } from "react";
import { StyleSheet, Text, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { colors, fonts, spacing } from "@/src/theme";

/**
 * La checklist en direct, sous l'ovale de cadrage.
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QU'ELLE REPREND DE LA REFERENCE, ET CE QU'ELLE EN CHANGE.
 *
 * La reference (Dior/Musemind) affiche trois criteres qui se cochent en
 * direct — luminosite, alignement, position — avant qu'une prise ne parte.
 * C'est ce principe qui manquait ici : SKYN avait deja un texte d'etat
 * ("Ne bougez plus") mais rien qui dise CE QUI est valide et ce qui ne l'est
 * pas encore. Un visage mal cadre pouvait afficher "Ne bougez plus" alors
 * que la prise n'allait jamais partir — le texte et la realite divergeaient.
 *
 * Les trois criteres ne sont pas ceux de la reference au mot pres : SKYN ne
 * demande jamais de "regarder droit", puisque le principe meme du scan est
 * de TOURNER la tete. Ils sont donc :
 *   - visage trouve ;
 *   - bien cadre (distance et position, calcule par `framingOk`) ;
 *   - lumiere suffisante — un critere qui n'existait nulle part avant, et
 *     dont l'absence pouvait degrader une analyse sans que personne ne
 *     sache pourquoi.
 *
 * Pas de croix rouge : sur un ecran qui montre le visage de quelqu'un, un
 * signal d'echec appuye est deplace. Un critere qui n'est pas encore acquis
 * reste neutre — il s'allume, il ne s'alarme pas.
 * ────────────────────────────────────────────────────────────────────────
 */

export type CriteresEtat = {
  detecte: boolean;
  cadre: boolean;
  /** null tant que la premiere mesure n'est pas encore faite. */
  lumiere: boolean | null;
};

function Chip({ label, ok }: { label: string; ok: boolean }) {
  const reduced = useReducedMotion();
  const t = useSharedValue(ok ? 1 : 0);

  useEffect(() => {
    t.value = withTiming(ok ? 1 : 0, { duration: reduced ? 0 : 260, easing: ease.out });
  }, [ok, reduced, t]);

  const pastille = useAnimatedStyle(() => ({
    backgroundColor: ok ? colors.accent : "transparent",
    borderColor: ok ? colors.accent : "rgba(255,246,240,0.46)",
    transform: [{ scale: 0.9 + t.value * 0.1 }],
  }));

  const texte = useAnimatedStyle(() => ({
    opacity: 0.62 + t.value * 0.38,
  }));

  return (
    <View style={styles.chip}>
      <Animated.View style={[styles.pastille, pastille]}>
        {ok ? <Text style={styles.coche}>✓</Text> : null}
      </Animated.View>
      <Animated.Text style={[styles.label, texte]} numberOfLines={1}>
        {label}
      </Animated.Text>
    </View>
  );
}

export function Criteres({ etat }: { etat: CriteresEtat }) {
  return (
    <View style={styles.rangee} accessibilityRole="none">
      <Chip label="Visage trouvé" ok={etat.detecte} />
      <Chip label="Bien cadré" ok={etat.cadre} />
      {/* Tant que la premiere mesure n'est pas faite, le critere reste
          silencieux plutot que d'afficher un « non » qui n'a pas de sens. */}
      <Chip label="Lumière" ok={etat.lumiere === true} />
    </View>
  );
}

const styles = StyleSheet.create({
  rangee: {
    flexDirection: "row",
    justifyContent: "center",
    gap: spacing.m,
    paddingHorizontal: spacing.l,
    paddingTop: spacing.s,
  },
  chip: { flexDirection: "row", alignItems: "center", gap: 6 },
  pastille: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 1.4,
    alignItems: "center",
    justifyContent: "center",
  },
  coche: {
    color: colors.onAccent,
    fontSize: 10,
    fontFamily: fonts.headingMedium,
    lineHeight: 12,
  },
  label: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.onInverse,
  },
});
