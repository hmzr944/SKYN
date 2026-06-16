import { useCallback, useState } from "react";
import { Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import * as Haptics from "expo-haptics";
import * as AppleAuthentication from "expo-apple-authentication";
import { useRouter } from "expo-router";

import { supabase } from "@/src/services/supabase";

WebBrowser.maybeCompleteAuthSession();

async function persistSessionFromUrl(url: string): Promise<string | null> {
  const codeMatch = url.match(/[?&]code=([^&]+)/);
  const accessTokenMatch = url.match(/[#&]access_token=([^&]+)/);
  const refreshTokenMatch = url.match(/[#&]refresh_token=([^&]+)/);

  if (codeMatch) {
    const { error } = await supabase.auth.exchangeCodeForSession(
      decodeURIComponent(codeMatch[1]),
    );
    return error?.message ?? null;
  }

  if (accessTokenMatch && refreshTokenMatch) {
    const { error } = await supabase.auth.setSession({
      access_token: decodeURIComponent(accessTokenMatch[1]),
      refresh_token: decodeURIComponent(refreshTokenMatch[1]),
    });
    return error?.message ?? null;
  }

  return "Aucune session recue.";
}

export function useProviderAuth() {
  const router = useRouter();
  const [busy, setBusy] = useState<"google" | "apple" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGoogle = useCallback(async () => {
    setError(null);
    setBusy("google");
    try {
      const redirectUrl =
        Platform.OS === "web"
          ? `${window.location.origin}/auth/callback`
          : Linking.createURL("auth/callback");

      const { data, error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: redirectUrl, skipBrowserRedirect: true },
      });

      if (oauthError || !data?.url) {
        setError(oauthError?.message || "Connexion impossible.");
        setBusy(null);
        return;
      }


      if (Platform.OS === "web") {
        window.location.href = data.url;
        return;
      }

      if (__DEV__) {
        const { Alert } = require("react-native");
        Alert.alert("Debug Auth - data.url", data.url);
      }

      const result = await WebBrowser.openAuthSessionAsync(data.url, redirectUrl);
      if (result.type !== "success" || !result.url) {
        setBusy(null);
        return;
      }

      const sessionError = await persistSessionFromUrl(result.url);
      if (sessionError) {
        setError(sessionError);
        setBusy(null);
        return;
      }

      const { data: sessionData } = await supabase.auth.getSession();
      if (!sessionData.session) {
        setError("Aucune session recue.");
        setBusy(null);
        return;
      }

      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace("/profile-setup");
    } catch (e: any) {
      setError(e?.message || "Connexion impossible.");
      setBusy(null);
    }
  }, [router]);

  const handleApple = useCallback(async () => {
    setError(null);
    setBusy("apple");
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      if (!credential.identityToken) {
        setError("Connexion Apple indisponible sur cet appareil.");
        setBusy(null);
        return;
      }
      const { error: signInError } = await supabase.auth.signInWithIdToken({
        provider: "apple",
        token: credential.identityToken,
      });
      if (signInError) {
        setError(signInError.message || "Connexion Apple indisponible sur cet appareil.");
        setBusy(null);
        return;
      }

      const { data: sessionData } = await supabase.auth.getSession();
      if (!sessionData.session) {
        setError("Aucune session recue.");
        setBusy(null);
        return;
      }

      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace("/profile-setup");
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") {
        setBusy(null);
        return;
      }
      setError("Connexion Apple indisponible sur cet appareil.");
      setBusy(null);
    }
  }, [router]);

  return { busy, error, setError, handleGoogle, handleApple };
}
