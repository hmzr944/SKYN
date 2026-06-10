import Svg, { Circle, Ellipse, Rect, Path, Line } from "react-native-svg";

import { colors } from "@/src/theme";

const SIZE = 160;

export function PromiseIllustration() {
  return (
    <Svg width={SIZE} height={SIZE} viewBox="0 0 160 160">
      <Circle cx={70} cy={64} r={52} fill={colors.accent} opacity={0.15} />
      <Circle cx={96} cy={100} r={42} fill={colors.lime} opacity={0.2} />
      <Circle
        cx={70}
        cy={64}
        r={52}
        fill="none"
        stroke={colors.accent}
        strokeWidth={1}
      />
    </Svg>
  );
}

export function TechIllustration() {
  const dots = [];
  for (let x = 12; x < SIZE; x += 16) {
    for (let y = 12; y < SIZE; y += 16) {
      dots.push(<Circle key={`${x}-${y}`} cx={x} cy={y} r={1} fill={colors.fg} opacity={0.08} />);
    }
  }
  return (
    <Svg width={SIZE} height={SIZE} viewBox="0 0 160 160">
      {dots}
      <Rect x={20} y={20} width={48} height={36} rx={10} fill={colors.lime} opacity={0.3} />
      <Rect x={92} y={20} width={48} height={36} rx={10} fill={colors.lime} opacity={0.3} />
      <Rect x={20} y={70} width={48} height={36} rx={10} fill={colors.lime} opacity={0.3} />
      <Rect x={92} y={70} width={48} height={36} rx={10} fill={colors.lime} opacity={0.3} />
      <Line x1={16} y1={130} x2={144} y2={130} stroke={colors.accent} strokeWidth={1} />
      <Line x1={32} y1={144} x2={128} y2={144} stroke={colors.accent} strokeWidth={1} />
    </Svg>
  );
}

export function PrivacyIllustration() {
  return (
    <Svg width={SIZE} height={SIZE} viewBox="0 0 160 160">
      <Path
        d="M80 16 L136 36 V80 C136 114 112 138 80 148 C48 138 24 114 24 80 V36 Z"
        fill="none"
        stroke={colors.fg}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      <Path
        d="M58 80 L74 96 L104 62"
        fill="none"
        stroke={colors.lime}
        strokeWidth={6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export function CaptureIllustration() {
  return (
    <Svg width={SIZE} height={SIZE} viewBox="0 0 160 160">
      <Ellipse cx={80} cy={80} rx={56} ry={68} fill={colors.surface} stroke={colors.accent} strokeWidth={2} />
      <Path d="M52 50 L62 50 L62 60" stroke={colors.accent} strokeWidth={1.5} fill="none" opacity={0.4} />
      <Path d="M108 50 L98 50 L98 60" stroke={colors.accent} strokeWidth={1.5} fill="none" opacity={0.4} />
      <Path d="M73 118 L87 118" stroke={colors.accent} strokeWidth={1.5} fill="none" opacity={0.4} />
    </Svg>
  );
}
