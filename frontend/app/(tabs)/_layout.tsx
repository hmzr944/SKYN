import { Tabs, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { LayoutChangeEvent, View, Text, StyleSheet } from "react-native";
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

/** Ordre d'affichage, la camera mise a part. */
const ORDER = ["dashboard", "routine", "history", "profile"] as const;

/** Le repere : un segment court, pas un point — a 3 px de haut il faut de la
 * longueur pour qu'un deplacement se lise. */
const MARK_W = 18;
const MARK_H = 3;

/** L'icone active se souleve : la selection a une epaisseur, pas seulement une couleur. */
function TabIcon({
  name,
  focused,
}: {
  name: keyof typeof Ionicons.glyphMap;
  focused: boolean;
}) {
  const t = useSharedValue(focused ? 1 : 0);
  useEffect(() => {
    t.value = withSpring(focused ? 1 : 0, motion.springDrop);
  }, [focused, t]);
  const aStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: -3 * t.value }, { scale: 1 + 0.09 * t.value }],
  }));
  return (
    <Animated.View style={aStyle}>
      <Ionicons
        name={focused ? name : (`${name}-outline` as keyof typeof Ionicons.glyphMap)}
        size={22}
        color={focused ? colors.accent : colors.fgDim}
      />
    </Animated.View>
  );
}

/**
 * La barre d'onglets.
 *
 * Le repere de position est UNIQUE et il se deplace. Quatre points qui
 * s'allument et s'eteignent chacun de leur cote ne disent que "c'est celui-la
 * maintenant" ; un seul repere qui parcourt la distance dit d'ou l'on vient et
 * ou l'on va. C'est la meme information, mais elle devient un mouvement — et
 * c'est ce mouvement qui rattache l'ecran precedent au suivant.
 *
 * Sa course est calculee sur les positions MESUREES des onglets : la barre
 * contient un bouton camera plus large que les autres, et toute position
 * devinee se decalerait des que la largeur d'ecran change.
 */
function CustomTabBar({ state, navigation }: BottomTabBarProps) {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  // Centre de chaque onglet, dans le repere de la barre.
  const [centers, setCenters] = useState<Record<string, number>>({});
  const x = useSharedValue(-MARK_W);
  const ready = useSharedValue(0);

  const active = state.routes[state.index]?.name;
  const target = active ? centers[active] : undefined;

  useEffect(() => {
    if (target == null) return;
    if (ready.value === 0) {
      // Premiere mesure : le repere se pose la, il ne traverse pas la barre.
      x.value = target - MARK_W / 2;
      ready.value = withSpring(1, motion.springDrop);
    } else {
      x.value = withSpring(target - MARK_W / 2, motion.spring);
    }
  }, [target, x, ready]);

  const sliderStyle = useAnimatedStyle(() => ({
    opacity: ready.value,
    transform: [{ translateX: x.value }, { scale: ready.value }],
  }));

  const measure = (routeName: string) => (e: LayoutChangeEvent) => {
    const { x: lx, width } = e.nativeEvent.layout;
    const center = lx + width / 2;
    setCenters((prev) =>
      Math.abs((prev[routeName] ?? -1) - center) < 0.5
        ? prev
        : { ...prev, [routeName]: center },
    );
  };

  const renderTab = (routeName: string) => {
    const index = state.routes.findIndex((r) => r.name === routeName);
    if (index === -1) return null;
    const route = state.routes[index];
    const focused = state.index === index;

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
        onLayout={measure(routeName)}
        style={styles.tab}
        scaleTo={0.92}
        haptic={false}
      >
        <TabIcon name={TAB_ICONS[routeName]} focused={focused} />
        <Text style={[styles.label, focused && styles.labelActive]}>
          {TAB_LABELS[routeName]}
        </Text>
      </AnimatedPressable>
    );
  };

  return (
    <View
      style={[
        styles.bar,
        // Le repere a besoin d'air sous lui : colle au bord de l'ecran il
        // paraissait tronque, et sur un appareil sans encoche il l'etait.
        { height: 66 + insets.bottom, paddingBottom: insets.bottom + spacing.s },
      ]}
    >
      <View style={styles.row}>
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

      {/* Le rail du repere : sa hauteur est reservee meme quand rien n'y est
          encore mesure, sinon la barre sauterait a la premiere mesure. */}
      <View style={styles.rail} pointerEvents="none">
        <Animated.View style={[styles.slider, sliderStyle]} />
      </View>
    </View>
  );
}

export default function TabsLayout() {
  return (
    <Tabs
      tabBar={(props) => <CustomTabBar {...props} />}
      // L'ecran glisse dans le sens du changement d'onglet, comme le repere de
      // la barre. Sans cela l'ecran se remplace d'un coup pendant que le
      // repere voyage, et les deux racontent deux choses differentes.
      screenOptions={{ headerShown: false, animation: "shift" }}
    >
      {ORDER.map((name) => (
        <Tabs.Screen key={name} name={name} />
      ))}
    </Tabs>
  );
}

const styles = StyleSheet.create({
  bar: {
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    paddingTop: spacing.xs,
  },
  row: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
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
  rail: { height: MARK_H, marginTop: spacing.xs },
  slider: {
    position: "absolute",
    left: 0,
    width: MARK_W,
    height: MARK_H,
    borderRadius: MARK_H / 2,
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
