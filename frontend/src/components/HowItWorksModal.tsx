import { Modal, View, Text, StyleSheet } from "react-native";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const STEPS = [
  "Détection des patterns lumineux à la surface de la peau.",
  "Cartographie des zones faciales (front, joues, menton, contour).",
  "Calcul d'un score multi-facteurs : hydratation, éclat, texture, imperfections.",
  "Génération de recommandations personnalisées selon vos résultats.",
];

export function HowItWorksModal({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet} testID="how-it-works-sheet">
          <View style={styles.handle} />
          <Text style={styles.title}>Technologie SKYN.</Text>

          {STEPS.map((step, i) => (
            <FadeIn key={i} delay={i * 60} distance={8}>
              <View style={styles.row}>
                <View style={styles.numberCircle}>
                  <Text style={styles.numberText}>{i + 1}</Text>
                </View>
                <Text style={styles.stepText}>{step}</Text>
              </View>
            </FadeIn>
          ))}

          <AnimatedPressable
            testID="how-it-works-close"
            style={styles.closeBtn}
            onPress={onClose}
            scaleTo={0.98}
          >
            <Text style={styles.closeText}>FERMER</Text>
          </AnimatedPressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.xl + 16,
    ...shadow.raised,
  },
  handle: {
    width: 32,
    height: 4,
    backgroundColor: colors.borderMid,
    alignSelf: "center",
    borderRadius: 2,
    marginTop: 12,
    marginBottom: spacing.l,
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 24,
    color: colors.fg,
    marginBottom: spacing.l,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.m,
    marginBottom: spacing.m,
  },
  numberCircle: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  numberText: {
    fontFamily: fonts.heading,
    fontSize: 18,
    color: colors.onLime,
  },
  stepText: {
    flex: 1,
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.fg,
    lineHeight: 20,
    paddingTop: 6,
  },
  closeBtn: {
    borderWidth: 1.5,
    borderColor: colors.accent,
    borderRadius: radius.pill,
    height: 52,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.l,
  },
  closeText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 12,
    letterSpacing: 1.5,
  },
});
