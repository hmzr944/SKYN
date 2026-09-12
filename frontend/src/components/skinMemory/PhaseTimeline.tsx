import { Text, View, StyleSheet } from "react-native";

import { colors, fonts, spacing } from "@/src/theme";
import type { CheckpointMarker, CheckpointStatus } from "@/src/services/skinMemory";

/**
 * J0 → J7 → J14 → J30 — où l'utilisateur en est dans la boucle de suivi
 * d'une Phase, jamais un jugement sur ce qu'elle raconte. Aucune couleur
 * neuve : le plein (terre) marque un rendez-vous honoré, le corail
 * marque le prochain, le contour marque ce qui arrive, l'estompé marque
 * une échéance passée sans scan — jamais "raté" au sens négatif, voir la
 * doctrine dans skinMemory.ts.
 */
function dotStyle(status: CheckpointStatus) {
  switch (status) {
    case "done":
      return { backgroundColor: colors.fg, borderColor: colors.fg };
    case "next":
      return { backgroundColor: colors.accent, borderColor: colors.accent };
    case "upcoming":
      return { backgroundColor: "transparent", borderColor: colors.borderMid };
    case "missed":
      return { backgroundColor: colors.fgFaint, borderColor: colors.fgFaint };
  }
}

function dayLabel(day: CheckpointMarker["day"]): string {
  return day === 0 ? "J0" : `J+${day}`;
}

export function PhaseTimeline({ markers }: { markers: CheckpointMarker[] }) {
  return (
    <View style={styles.row}>
      {markers.map((m, i) => (
        <View key={m.day} style={styles.step}>
          {i > 0 ? (
            <View
              style={[
                styles.line,
                { backgroundColor: m.status === "upcoming" ? colors.borderSubtle : colors.borderMid },
              ]}
            />
          ) : null}
          <View style={styles.dotWrap}>
            <View style={[styles.dot, dotStyle(m.status)]} />
            <Text style={[styles.dayText, m.status === "next" && styles.dayTextNext]}>{dayLabel(m.day)}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
  step: { flex: 1, flexDirection: "row", alignItems: "center" },
  line: { flex: 1, height: 1.5 },
  dotWrap: { alignItems: "center", gap: 6 },
  dot: { width: 12, height: 12, borderRadius: 6, borderWidth: 1.5 },
  dayText: { fontFamily: fonts.body, fontSize: 10, color: colors.fgDim },
  dayTextNext: { fontFamily: fonts.bodyMedium, color: colors.accent },
});
