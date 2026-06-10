import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";

import { api } from "@/src/services/api";
import { supabase } from "@/src/services/supabase";
import { colors, fonts, spacing } from "@/src/theme";

export default function AuthCallbackScreen() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function finishSignIn() {
      try {
        if (typeof window !== "undefined") {
          const currentUrl = new URL(window.location.href);
          const code = currentUrl.searchParams.get("code");
          const accessToken = currentUrl.hash.match(/[#&]access_token=([^&]+)/)?.[1];
          const refreshToken = currentUrl.hash.match(/[#&]refresh_token=([^&]+)/)?.[1];

          if (code) {
            const { error: codeError } = await supabase.auth.exchangeCodeForSession(code);
            if (codeError) throw codeError;
          } else if (accessToken && refreshToken) {
            const { error: tokenError } = await supabase.auth.setSession({
              access_token: decodeURIComponent(accessToken),
              refresh_token: decodeURIComponent(refreshToken),
            });
            if (tokenError) throw tokenError;
          }
        }

        const { data, error: sessionError } = await supabase.auth.getSession();
        if (sessionError) throw sessionError;
        if (!data.session) throw new Error("Aucune session recue.");

        try {
          const profile = await api.getProfile();
          if (mounted) router.replace(profile?.onboarded ? "/dashboard" : "/profile-setup");
        } catch {
          if (mounted) router.replace("/profile-setup");
        }
      } catch (e: any) {
        if (mounted) setError(e?.message || "Connexion impossible.");
      }
    }

    finishSignIn();

    return () => {
      mounted = false;
    };
  }, [router]);

  return (
    <View style={styles.container}>
      {error ? (
        <>
          <Text style={styles.title}>Connexion interrompue</Text>
          <Text style={styles.message}>{error}</Text>
        </>
      ) : (
        <>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.message}>Connexion en cours...</Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.m,
    padding: spacing.xl,
    backgroundColor: colors.bg,
  },
  title: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 24,
    textAlign: "center",
  },
  message: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
});
