import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider } from "@/src/contexts/AuthContext";
import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { colors, motion } from "@/src/theme";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [iconsLoaded, iconsError] = useIconFonts();
  // Une seule famille pour toute l'app : la hierarchie vient de la graisse.
  const [fontsLoaded, fontsError] = useFonts({
    Outfit_300Light: require("@/assets/fonts/Outfit-Light.ttf"),
    Outfit_400Regular: require("@/assets/fonts/Outfit-Regular.ttf"),
    Outfit_500Medium: require("@/assets/fonts/Outfit-Medium.ttf"),
    Outfit_600SemiBold: require("@/assets/fonts/Outfit-SemiBold.ttf"),
    Outfit_700Bold: require("@/assets/fonts/Outfit-Bold.ttf"),
  });

  useEffect(() => {
    if ((iconsLoaded || iconsError) && (fontsLoaded || fontsError)) {
      SplashScreen.hideAsync();
    }
  }, [iconsLoaded, iconsError, fontsLoaded, fontsError]);

  if ((!iconsLoaded && !iconsError) || (!fontsLoaded && !fontsError)) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.bg }}>
      <SafeAreaProvider>
        <AuthProvider>
          <StatusBar style="dark" />
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: colors.bg },
              // Avancer glisse vers la gauche : le sens porte la profondeur.
              animation: "slide_from_right",
              animationDuration: motion.base,
              gestureEnabled: true,
            }}
          >
            {/* Le splash se fond : il n'y a rien derriere lui. */}
            <Stack.Screen name="index" options={{ animation: "fade" }} />
            {/* L'onboarding et l'auth ouvrent l'app, ils ne s'empilent pas. */}
            <Stack.Screen name="onboarding" options={{ animation: "fade" }} />
            <Stack.Screen name="auth" options={{ animation: "fade" }} />
            <Stack.Screen name="(tabs)" options={{ animation: "fade" }} />
            {/* La camera monte du bas : c'est un outil qu'on sort. */}
            <Stack.Screen
              name="camera"
              options={{ animation: "fade_from_bottom", gestureEnabled: false }}
            />
            {/* L'analyse ne se quitte pas au geste : elle doit aller au bout. */}
            <Stack.Screen
              name="analysis"
              options={{ animation: "fade", gestureEnabled: false }}
            />
            {/* Le rapport est la conclusion : il arrive par le bas, comme un verdict. */}
            <Stack.Screen name="report" options={{ animation: "fade_from_bottom" }} />
            <Stack.Screen name="scan-result" options={{ animation: "fade_from_bottom" }} />
          </Stack>
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
