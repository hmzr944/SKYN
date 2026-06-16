import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { useFonts } from "expo-font";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider } from "@/src/contexts/AuthContext";
import { colors } from "@/src/theme";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [iconsLoaded, iconsError] = useIconFonts();
  const [fontsLoaded, fontsError] = useFonts({
    ClashDisplay_500Medium: require("@/assets/fonts/ClashDisplay-Medium.ttf"),
    ClashDisplay_600SemiBold: require("@/assets/fonts/ClashDisplay-SemiBold.ttf"),
    GeneralSans_400Regular: require("@/assets/fonts/GeneralSans-Regular.ttf"),
    GeneralSans_500Medium: require("@/assets/fonts/GeneralSans-Medium.ttf"),
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
              animation: "fade",
              animationDuration: 400,
            }}
          />
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
