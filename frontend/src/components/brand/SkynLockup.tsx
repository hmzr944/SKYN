import { StyleProp, StyleSheet, Text, View, ViewStyle } from "react-native";

import { colors, type } from "@/src/theme";
import { SkynMark, SkynMarkStill } from "./SkynMark";

type Props = {
  size?: number;
  onDark?: boolean;
  /** Rejoue le balayage du symbole. */
  playKey?: number;
  still?: boolean;
  style?: StyleProp<ViewStyle>;
};

/**
 * Le verrouillage : le symbole a gauche, le mot a droite, jamais l'inverse.
 * La chasse tres ouverte du mot laisse respirer le symbole — les deux se
 * lisent comme une signature, pas comme un bloc.
 */
export function SkynLockup({ size = 30, onDark, playKey, still, style }: Props) {
  return (
    <View style={[styles.row, style]}>
      {still ? (
        <SkynMarkStill size={size} onDark={onDark} />
      ) : (
        <SkynMark size={size} onDark={onDark} playKey={playKey} />
      )}
      <Text
        style={[
          styles.word,
          { fontSize: size * 0.56, color: onDark ? colors.onInverse : colors.fg },
        ]}
      >
        SKYN
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 11 },
  word: { fontFamily: type.wordmark.fontFamily, letterSpacing: 6.4 },
});
