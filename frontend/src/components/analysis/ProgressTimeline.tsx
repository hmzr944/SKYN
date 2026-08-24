import { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, useWindowDimensions } from "react-native";
import Svg, { Path, Circle, Defs, LinearGradient, Stop, Line } from "react-native-svg";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { getScans, type ScanEntry } from "@/src/services/routineStore";
import { scoreColor } from "./FaceZoneMap";

/**
 * Evolution du score cutane d'un scan a l'autre.
 *
 * Le graphe ne s'affiche qu'a partir de deux scans : une courbe a un point ne
 * dit rien, et afficher un "+0 %" au premier scan donnerait l'impression que
 * rien ne bouge alors que rien n'a encore ete mesure deux fois.
 */

interface Props {
  /** Scans injectes (sinon lus depuis le stockage local). */
  scans?: ScanEntry[];
}

export function ProgressTimeline({ scans: injected }: Props) {
  const { width } = useWindowDimensions();
  const [scans, setScans] = useState<ScanEntry[]>(injected ?? []);

  useEffect(() => {
    if (injected) return;
    let alive = true;
    getScans().then((s) => alive && setScans(s));
    return () => {
      alive = false;
    };
  }, [injected]);

  const chartW = width - spacing.l * 2 - spacing.l * 2;
  const chartH = 96;

  const geometry = useMemo(() => {
    if (scans.length < 2) return null;
    const pts = scans.slice(-12);
    const vals = pts.map((s) => s.global_score);
    // Fenetre verticale elargie de quelques points pour que la courbe ne
    // touche jamais les bords du cadre.
    const lo = Math.max(0, Math.min(...vals) - 6);
    const hi = Math.min(100, Math.max(...vals) + 6);
    const span = hi - lo || 1;

    const xy = pts.map((s, i) => ({
      x: pts.length === 1 ? chartW / 2 : (i / (pts.length - 1)) * chartW,
      y: chartH - ((s.global_score - lo) / span) * chartH,
      s,
    }));

    // Courbe lissee (Catmull-Rom converti en cubiques de Bezier)
    let d = `M${xy[0].x},${xy[0].y}`;
    for (let i = 0; i < xy.length - 1; i++) {
      const p0 = xy[Math.max(0, i - 1)];
      const p1 = xy[i];
      const p2 = xy[i + 1];
      const p3 = xy[Math.min(xy.length - 1, i + 2)];
      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2.x},${p2.y}`;
    }
    const area = `${d} L${xy[xy.length - 1].x},${chartH} L${xy[0].x},${chartH} Z`;
    return { xy, d, area, first: pts[0], last: pts[pts.length - 1] };
  }, [scans, chartW]);

  if (scans.length === 0) return null;

  if (!geometry) {
    return (
      <View style={styles.card}>
        <Text style={styles.eyebrow}>Progression</Text>
        <Text style={styles.singleHint}>
          Premier scan enregistré · {scans[0].global_score}/100. Refaites un scan
          dans deux à trois semaines pour voir la courbe se dessiner.
        </Text>
      </View>
    );
  }

  const { xy, d, area, first, last } = geometry;
  const delta = last.global_score - first.global_score;
  const lesionDelta = last.lesion_total - first.lesion_total;
  const positive = delta > 0;

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.eyebrow}>Progression · {scans.length} scans</Text>
        <View
          style={[
            styles.deltaPill,
            { backgroundColor: positive ? colors.okSoft : colors.accentSofter },
          ]}
        >
          <Text
            style={[
              styles.deltaText,
              { color: positive ? colors.onOk : colors.accentDark },
            ]}
          >
            {delta > 0 ? "+" : ""}
            {delta} pts
          </Text>
        </View>
      </View>

      <Svg width={chartW} height={chartH + 8}>
        <Defs>
          <LinearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0.18" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="0.01" />
          </LinearGradient>
        </Defs>
        {/* Repères horizontaux discrets */}
        {[0.25, 0.5, 0.75].map((f) => (
          <Line
            key={f}
            x1={0}
            y1={chartH * f}
            x2={chartW}
            y2={chartH * f}
            stroke={colors.fgFaint}
            strokeWidth={1}
          />
        ))}
        <Path d={area} fill="url(#areaFill)" />
        <Path d={d} stroke={colors.accent} strokeWidth={2.4} fill="none" strokeLinecap="round" />
        {xy.map((p, i) => {
          const isLast = i === xy.length - 1;
          return (
            <Circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={isLast ? 5.5 : 3}
              fill={isLast ? scoreColor(p.s.global_score) : colors.bg}
              stroke={colors.accent}
              strokeWidth={isLast ? 2.5 : 1.8}
            />
          );
        })}
      </Svg>

      <View style={styles.footRow}>
        <View>
          <Text style={styles.footLabel}>Premier scan</Text>
          <Text style={styles.footValue}>{first.global_score}</Text>
          <Text style={styles.footDate}>
            {new Date(first.date).toLocaleDateString("fr-FR", {
              day: "numeric",
              month: "short",
            })}
          </Text>
        </View>
        <View style={styles.footArrow}>
          <Text style={styles.footArrowText}>→</Text>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={styles.footLabel}>Aujourd'hui</Text>
          <Text style={[styles.footValue, { color: scoreColor(last.global_score) }]}>
            {last.global_score}
          </Text>
          <Text style={styles.footDate}>
            {new Date(last.date).toLocaleDateString("fr-FR", {
              day: "numeric",
              month: "short",
            })}
          </Text>
        </View>
      </View>

      {lesionDelta !== 0 && (
        <Text style={styles.lesionNote}>
          {lesionDelta < 0
            ? `${Math.abs(lesionDelta)} lésions de moins qu'au premier scan.`
            : `${lesionDelta} lésions de plus qu'au premier scan.`}{" "}
          Un actif met huit à douze semaines à donner sa pleine mesure : les
          variations d'une semaine à l'autre sont normales.
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    marginHorizontal: spacing.l,
    marginBottom: spacing.m,
    padding: spacing.l,
    ...shadow.card,
  },
  head: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.m,
  },
  eyebrow: {
    fontFamily: fonts.bodyMedium,
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: colors.fgDim,
  },
  deltaPill: {
    borderRadius: radius.pill,
    paddingHorizontal: spacing.m,
    paddingVertical: 4,
  },
  deltaText: { fontFamily: fonts.headingMedium, fontSize: 12 },
  singleHint: {
    fontFamily: fonts.body,
    fontSize: 13,
    lineHeight: 20,
    color: colors.fgMuted,
  },
  footRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.m,
  },
  footLabel: { fontFamily: fonts.body, fontSize: 10, color: colors.fgDim },
  footValue: {
    fontFamily: fonts.heading,
    fontSize: 26,
    color: colors.fg,
    letterSpacing: -0.8,
  },
  footDate: { fontFamily: fonts.body, fontSize: 10, color: colors.fgDim },
  footArrow: { flex: 1, alignItems: "center" },
  footArrowText: { fontFamily: fonts.body, fontSize: 18, color: colors.fgDim },
  lesionNote: {
    fontFamily: fonts.body,
    fontSize: 11,
    lineHeight: 17,
    color: colors.fgMuted,
    marginTop: spacing.m,
  },
});
