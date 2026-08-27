import { useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { colors, fonts, radius, spacing } from "@/src/theme";

/**
 * Une demande d'autorisation, posee dans l'onboarding.
 *
 * ────────────────────────────────────────────────────────────────────────
 * POURQUOI ICI PLUTOT QU'AU MOMENT DU BESOIN.
 *
 * L'app demandait la camera au moment ou l'on ouvrait le scan : la boite de
 * dialogue du systeme tombait sur un ecran noir, sans un mot d'explication, et
 * la seule chose qu'on avait a decider c'etait « oui » ou « non » a une app
 * dont on ne savait encore rien. Un refus a ce moment-la est definitif : iOS ne
 * repose la question qu'une fois, ensuite il faut aller dans les Reglages.
 *
 * Ici, la demande arrive APRES la promesse et APRES l'ecran sur la vie privee.
 * On sait ce qu'on echange et contre quoi. Et le refus n'est pas un cul-de-sac
 * — on continue, la demande se reposera au moment utile.
 *
 * L'etat se voit ensuite : accorde, refuse, ou pas encore demande. Une demande
 * dont on ne voit pas le resultat pousse a reappuyer dans le vide.
 * ────────────────────────────────────────────────────────────────────────
 */

/** Au-dela, on cesse de faire tourner le bouton : la question ne viendra pas. */
const ATTENTE_MAX = 12000;

export type Etat = "attente" | "accorde" | "refuse" | "impossible";

export function Autorisation({
  etat,
  onDemander,
  libelle,
  motAccorde,
  motRefuse,
  motImpossible,
  testID,
}: {
  etat: Etat;
  onDemander: () => Promise<void>;
  /** Le texte du bouton, quand il reste quelque chose a demander. */
  libelle: string;
  motAccorde: string;
  motRefuse: string;
  /** Ce qu'on dit quand la plateforme ne sait pas le faire du tout. */
  motImpossible: string;
  testID?: string;
}) {
  const [enCours, setEnCours] = useState(false);

  if (etat === "impossible") {
    return (
      <View style={styles.bloc}>
        <View style={[styles.etat, styles.etatNeutre]}>
          <Text style={styles.etatTexte} testID={testID ? `${testID}-impossible` : undefined}>
            {motImpossible}
          </Text>
        </View>
      </View>
    );
  }

  if (etat === "accorde") {
    return (
      <View style={styles.bloc}>
        <View style={[styles.etat, styles.etatOk]}>
          <Text style={styles.puce}>✓</Text>
          <Text style={styles.etatTexte} testID={testID ? `${testID}-accorde` : undefined}>
            {motAccorde}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.bloc}>
      <AnimatedPressable
        testID={testID}
        style={styles.bouton}
        haptic="medium"
        disabled={enCours}
        onPress={async () => {
          setEnCours(true);
          try {
            // Le systeme repond toujours a une demande d'autorisation — sauf
            // quand le navigateur bloque la question sans le dire, et la la
            // promesse ne se resout jamais. Sans cette borne, le bouton tourne
            // indefiniment et l'ecran parait plante. Mesure faite : en
            // navigateur sans invite, l'attente ne rendait jamais la main.
            await Promise.race([
              onDemander(),
              new Promise((r) => setTimeout(r, ATTENTE_MAX)),
            ]);
          } finally {
            setEnCours(false);
          }
        }}
      >
        {enCours ? (
          <ActivityIndicator color={colors.onAccent} size="small" />
        ) : (
          <Text style={styles.boutonTexte}>{libelle}</Text>
        )}
      </AnimatedPressable>

      {/* Un refus n'arrete rien. On le dit, plutot que de laisser croire que
          l'ecran est bloque tant qu'on n'a pas accepte. */}
      {etat === "refuse" ? (
        <Text style={styles.refus} testID={testID ? `${testID}-refuse` : undefined}>
          {motRefuse}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bloc: { width: "100%", marginTop: spacing.l, gap: spacing.s },
  bouton: {
    backgroundColor: colors.accent,
    paddingVertical: 17,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    minHeight: 52,
  },
  boutonTexte: {
    fontFamily: fonts.headingMedium,
    color: colors.onAccent,
    fontSize: 12,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  etat: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    paddingVertical: 15,
    paddingHorizontal: spacing.m,
    borderRadius: radius.md,
    minHeight: 52,
  },
  etatOk: { backgroundColor: colors.accentSofter, borderWidth: 1, borderColor: colors.accentLine },
  etatNeutre: { backgroundColor: colors.surfaceSunken },
  puce: { color: colors.accent, fontSize: 15, fontFamily: fonts.bodyMedium },
  etatTexte: { flex: 1, fontFamily: fonts.body, fontSize: 13, lineHeight: 19, color: colors.fgMuted },
  refus: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 18,
    color: colors.fgDim,
  },
});
