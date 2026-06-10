import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Platform,
  ActivityIndicator,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import * as Haptics from "expo-haptics";
import * as AppleAuthentication from "expo-apple-authentication";
import { useRouter } from "expo-router";

import { colors, fonts, spacing, radius } from "@/src/theme";
import { api } from "@/src/services/api";
import { useAuth } from "@/src/contexts/AuthContext";

export default function AuthScreen() {
  const router = useRouter();
  const { signInWithSessionToken } = useAuth();
  const [busy, setBusy] = useState<"google" | "apple" | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openProviderSheet = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setError(null);
    setSheetVisible(true);
  };

  const closeSheet = () => setSheetVisible(false);

  const handleGoogle = useCallback(async () => {
    setSheetVisible(false);
    setError(null);
    setBusy("google");
    try {
      const redirectUrl =
        Platform.OS === "web"
          ? window.location.origin + "/"
          : Linking.createURL("auth");
      const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(
        redirectUrl,
      )}`;

      if (Platform.OS === "web") {
        window.location.href = authUrl;
        return;
      }

      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
      if (result.type !== "success" || !result.url) {
        setBusy(null);
        return;
      }
      const url = result.url;
      const sidMatch = url.match(/[?#&]session_id=([^&]+)/);
      const sessionId = sidMatch?.[1];
      if (!sessionId) {
        setError("Aucune session reçue.");
        setBusy(null);
        return;
      }
      const data = await api.googleSession(sessionId);
      await signInWithSessionToken(data.session_token);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace("/profile-setup");
    } catch (e: any) {
      setError(e?.message || "Connexion impossible.");
      setBusy(null);
    }
  }, [router, signInWithSessionToken]);

  const handleApple = useCallback(async () => {
    setSheetVisible(false);
    setError(null);
    setBusy("apple");
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      const fullName = credential.fullName
        ? [credential.fullName.givenName, credential.fullName.familyName]
            .filter(Boolean)
            .join(" ")
        : undefined;
      if (!credential.identityToken) {
        setError("Connexion Apple indisponible sur cet appareil.");
        setBusy(null);
        return;
      }
      const data = await api.appleSession(
        credential.identityToken,
        credential.user,
        credential.email || undefined,
        fullName,
      );
      await signInWithSessionToken(data.session_token);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace("/profile-setup");
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") {
        setBusy(null);
        return;
      }
      setError("Connexion Apple indisponible sur cet appareil.");
      setBusy(null);
    }
  }, [router, signInWithSessionToken]);

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Hero */}
      <View style={styles.hero}>
        <Text style={styles.logo}>SKYN</Text>
        <View style={styles.hairline} />
        <Text style={styles.tagline}>L'analyse cutanée éditoriale</Text>
      </View>

      {/* Actions */}
      <View style={styles.actions}>
        {error ? (
          <View style={styles.errorBadge}>
            <Text style={styles.error} testID="auth-error">
              {error}
            </Text>
          </View>
        ) : null}

        <TouchableOpacity
          testID="auth-main-button"
          style={styles.primaryBtn}
          activeOpacity={0.8}
          onPress={openProviderSheet}
          disabled={busy !== null}
        >
          {busy ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.primaryBtnText}>Commencer l'analyse</Text>
          )}
        </TouchableOpacity>

        <Text style={styles.gdpr} testID="auth-gdpr">
          En continuant, vous créez votre dossier cutané chiffré. Vos photos
          sont analysées puis immédiatement supprimées.
        </Text>
      </View>

      {/* Provider Sheet */}
      <Modal
        visible={sheetVisible}
        transparent
        animationType="slide"
        onRequestClose={closeSheet}
      >
        <TouchableOpacity
          style={styles.backdrop}
          activeOpacity={1}
          onPress={closeSheet}
          testID="auth-sheet-backdrop"
        >
          <View style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Se connecter</Text>
            <Text style={styles.sheetSubtitle}>
              Choisissez un fournisseur d'identité
            </Text>

            <TouchableOpacity
              testID="auth-google-button"
              style={styles.sheetBtn}
              activeOpacity={0.75}
              onPress={handleGoogle}
            >
              <Text style={styles.sheetBtnText}>Continuer avec Google</Text>
            </TouchableOpacity>

            {Platform.OS === "ios" ? (
              <TouchableOpacity
                testID="auth-apple-button"
                style={[styles.sheetBtn, styles.sheetBtnOutline]}
                activeOpacity={0.75}
                onPress={handleApple}
              >
                <Text style={[styles.sheetBtnText, styles.sheetBtnTextOutline]}>
                  Continuer avec Apple
                </Text>
              </TouchableOpacity>
            ) : null}

            <TouchableOpacity onPress={closeSheet} style={styles.cancel}>
              <Text style={styles.cancelText}>Annuler</Text>
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.xl,
    justifyContent: "space-between",
  },
  hero: {
    marginTop: spacing.xxxl + spacing.xxl,
    alignItems: "center",
  },
  logo: {
    fontFamily: fonts.heading,
    fontSize: 108,
    color: colors.fg,
    letterSpacing: 12,
  },
  hairline: {
    width: 48,
    height: 1,
    backgroundColor: colors.borderMid,
    marginTop: spacing.l,
    marginBottom: spacing.m,
  },
  tagline: {
    fontFamily: fonts.headingItalic,
    fontSize: 15,
    color: colors.fgMuted,
    letterSpacing: 0.5,
  },
  actions: {
    paddingBottom: spacing.l,
    gap: spacing.m,
  },
  errorBadge: {
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.sm,
    paddingVertical: spacing.s,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.fgFaint,
  },
  error: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 0.5,
    textAlign: "center",
  },
  primaryBtn: {
    backgroundColor: colors.fg,
    paddingVertical: 20,
    alignItems: "center",
    borderRadius: radius.pill,
  },
  primaryBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.bg,
    fontSize: 13,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  gdpr: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
    paddingHorizontal: spacing.s,
  },
  backdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.surfaceRaised,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.xl + 16,
  },
  sheetHandle: {
    width: 36,
    height: 3,
    backgroundColor: colors.borderActive,
    opacity: 0.25,
    alignSelf: "center",
    borderRadius: 2,
    marginBottom: spacing.xl,
  },
  sheetTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 28,
    letterSpacing: -0.5,
    marginBottom: spacing.xs,
  },
  sheetSubtitle: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 13,
    marginBottom: spacing.l,
  },
  sheetBtn: {
    backgroundColor: colors.fg,
    paddingVertical: 17,
    alignItems: "center",
    borderRadius: radius.pill,
    marginBottom: spacing.m,
  },
  sheetBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.bg,
    fontSize: 13,
    letterSpacing: 1.8,
    textTransform: "uppercase",
  },
  sheetBtnOutline: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: colors.borderActive,
  },
  sheetBtnTextOutline: {
    color: colors.fg,
  },
  cancel: {
    paddingVertical: 14,
    alignItems: "center",
    marginTop: spacing.xs,
  },
  cancelText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
