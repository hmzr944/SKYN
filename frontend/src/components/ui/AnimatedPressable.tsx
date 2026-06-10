import { ReactNode } from "react";
import { StyleProp, ViewStyle } from "react-native";
import { Pressable } from "react-native-gesture-handler";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

const AnimatedView = Animated.createAnimatedComponent(Animated.View);

type Props = {
  children: ReactNode;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  scaleTo?: number;
  disabled?: boolean;
  testID?: string;
};

export function AnimatedPressable({
  children,
  onPress,
  style,
  scaleTo = 0.96,
  disabled,
  testID,
}: Props) {
  const scale = useSharedValue(1);

  const aStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled}
      onPressIn={() => {
        scale.value = withTiming(scaleTo, { duration: 100 });
      }}
      onPressOut={() => {
        scale.value = withTiming(1, { duration: 150 });
      }}
    >
      <AnimatedView style={[style, aStyle]}>{children}</AnimatedView>
    </Pressable>
  );
}
