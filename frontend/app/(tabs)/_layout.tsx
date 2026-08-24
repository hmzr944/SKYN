import { Tabs, useRouter } from "expo-router";
import { useEffect } from "react";
import { View, Text, StyleSheet } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import type { BottomTabBarProps } from "@react-navigation/bottom-tabs";

import { colors, fonts, motion, radius, shadow, spacing } from "@/src/theme";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const TAB_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  dashboard: "home",
  routine: "checkmark-circle",
  history: "time",
  profile: "person",
};

const TAB_LABELS: Record<string, string> = {
  dashboard: "Accueil",
  routine: "Routine",
  history: "Suivi",
  profile: "Profil",
};

/** Le point de l'onglet actif se pose au ressort, comme le point du symbole. */
function TabDot({ focused }: { focused: boolean }) {
  const t = useSharedValue(focused ? 1 : 0);
  useEffect(() => {
    t.value = withSpring(focused ? 1 : 0, motion.springDrop);
  }, [focused, t]);
  const aStyle = useAnimatedStyle(() => ({
    opacity: t.value,
    transform: [{ scale: t.value }],
  }));
  return <Animated.View style={[styles.tabDot, aStyle]} />;
}

function CustomTabBar({ state, navigation }: BottomTabBarProps) {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const renderTab = (routeName: string) => {
    const index = state.routes.findIndex((r) => r.name === routeName);
    if (index === -1) return null;
    const route = state.routes[index];
    const focused = state.index === index;
    const icon = TAB_ICONS[routeName];

    const onPress = () => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const event = navigation.emit({
        type: "tabPress",
        target: route.key,
        canPreventDefault: true,
      });
      if (!focused && !event.defaultPrevented) {
        navigation.navigate(route.name);
      }
    };

    return (
      <AnimatedPressable
        key={routeName}
        testID={`tab-${routeName}`}
        onPress={onPress}
        style={styles.tab}
        scaleTo={0.92}
        haptic={false}
      >
        <Ionicons
          name={focused ? icon : (`${icon}-outline` as keyof typeof Ionicons.glyphMap)}
          size={22}
          color={focused ? colors.accent : colors.fgDim}
        />
        <Text style={[styles.label, focused && styles.labelActive]}>
          {TAB_LABELS[routeName]}
        </Text>
        <TabDot focused={focused} />
      </AnimatedPressable>
    );
  };

  return (
    <View
      style={[
        styles.bar,
        { height: 56 + insets.bottom, paddingBottom: insets.bottom },
      ]}
    >
      {renderTab("dashboard")}
      {renderTab("routine")}

      <AnimatedPressable
        testID="tab-analyser"
        style={styles.fab}
        scaleTo={0.92}
        haptic={false}
        onPress={() => {
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
          router.push("/camera");
        }}
      >
        <Ionicons name="camera" size={22} color={colors.onAccent} />
      </AnimatedPressable>

      {renderTab("history")}
      {renderTab("profile")}
    </View>
  );
}

export default function TabsLayout() {
  return (
    <Tabs
      tabBar={(props) => <CustomTabBar {...props} />}
      screenOptions={{ headerShown: false }}
    >
      <Tabs.Screen name="dashboard" />
      <Tabs.Screen name="routine" />
      <Tabs.Screen name="history" />
      <Tabs.Screen name="profile" />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    paddingTop: spacing.xs,
  },
  tab: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  label: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.fgDim,
  },
  labelActive: {
    color: colors.accent,
  },
  tabDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.accent,
  },
  fab: {
    width: 52,
    height: 52,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    transform: [{ translateY: -12 }],
    ...shadow.button,
  },
});
