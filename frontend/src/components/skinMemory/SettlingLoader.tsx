import { StyleSheet, Text, View } from "react-native";

import { PhaseHalo } from "@/src/components/skinMemory/PhaseHalo";
import { colors, spacing, type } from "@/src/theme";

/**
 * L'attente redevenue une part du rituel, pas une interruption.
 *
 * Remplace un ActivityIndicator générique sur les quatre écrans de la
 * mémoire de peau : le Halo respire déjà (voir PhaseHalo.tsx) — le même
 * objet qui représente la confiance de la Phase représente maintenant
 * aussi "SKYN est en train de regarder", au lieu d'un rond de chargement
 * qui ne dit rien de SKYN en particulier.
 */
export function SettlingLoader({ label }: { label?: string }) {
  return (
    <View style={styles.wrap}>
      <PhaseHalo size={72} tone="calm" />
      {label ? <Text style={styles.label}>{label}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center", gap: spacing.m },
  label: { ...type.bodySmall, color: colors.fgMuted },
});
