import { useEffect } from "react";
import { View, Text, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/AuthContext";
import { colors, fonts } from "@/src/theme";

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/auth");
    } else if (!profile?.onboarded) {
      router.replace("/profile-setup");
    } else {
      router.replace("/dashboard");
    }
  }, [loading, user, profile, router]);

  return (
    <View style={styles.container} testID="splash-screen">
      <Text style={styles.logo}>SKYN</Text>
      <View style={styles.divider} />
      <Text style={styles.tagline}>{"L'analyse cutanée éditoriale"}</Text>
      <ActivityIndicator color={colors.fg} style={styles.spinner} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  logo: {
    fontFamily: fonts.heading,
    fontSize: 56,
    color: colors.fg,
    letterSpacing: 8,
  },
  divider: {
    width: 40,
    height: 1,
    backgroundColor: colors.borderSubtle,
    marginVertical: 20,
  },
  tagline: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgMuted,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  spinner: { marginTop: 48 },
});
