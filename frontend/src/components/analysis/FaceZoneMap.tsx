import { useEffect, useMemo } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import Svg, { Path, Ellipse, G, Circle, Defs, ClipPath } from "react-native-svg";
import Animated, {
  useAnimatedProps,
  useSharedValue,
  withDelay,
  withTiming,
} from "react-native-reanimated";

import { ease } from "@/src/animation/ease";
import { colors, fonts, spacing } from "@/src/theme";
import { FACE_EXTENT, facePathAt } from "@/src/theme/mark";
import type { Lesion, ZoneKey } from "@/src/types/analysis";
import { ZONE_LABEL } from "@/src/types/analysis";
import type { Confidence } from "@/src/types/skinMemory";

/**
 * Cartographie faciale : chaque zone est teintee par sa note, et les lesions
 * detectees sont reportees a leur position reelle.
 *
 * Les coordonnees des lesions arrivent normalisees 0..1 sur la boite
 * englobante du visage analyse. On les replace telles quelles sur le schema :
 * la correspondance n'est pas anatomiquement exacte d'un visage a l'autre,
 * mais elle restitue fidelement la repartition — c'est elle qui porte
 * l'information clinique (une acne mandibulaire ne se lit pas comme une acne
 * frontale).
 */

const VB_W = 200;
const VB_H = 260;

/**
 * Le contour est celui de la MARQUE, pas un visage dessine.
 *
 * Ce schema portait un ovale a son compte, avec deux yeux et une bouche par
 * dessus un degrade couleur peau. Resultat : un mannequin, ou un masque. Ce
 * n'est pas seulement laid, c'est faux — on ne mesure ni les yeux ni la
 * bouche, et les representer laisse croire le contraire.
 *
 * Il reste un contour, parce qu'il faut bien s'orienter : « joue gauche » ne
 * veut rien dire sans repere. Mais c'est le symbole de SKYN, remis a l'echelle
 * du releve, et il ne represente rien qu'on ne mesure pas.
 *
 * Le chemin est CALCULE aux coordonnees du schema, pas pose puis transforme.
 * Un `transform` sur le groupe d'un `clipPath` n'est pas repercute de la meme
 * façon partout : le decoupage retombait alors sur le carre d'origine, et la
 * carte se vidait entierement de son contenu.
 */
const MARK_SCALE = 4.83;
const FACE_PATH = facePathAt(100, 133, MARK_SCALE);

/** Encombrement du contour une fois pose : sert a placer les lesions. */
const FACE_BOX = {
  x: 100 - (FACE_EXTENT.w * MARK_SCALE) / 2,
  y: 133 - (FACE_EXTENT.h * MARK_SCALE) / 2,
  w: FACE_EXTENT.w * MARK_SCALE,
  h: FACE_EXTENT.h * MARK_SCALE,
};

type ZoneShape = { cx: number; cy: number; rx: number; ry: number; rot?: number };

// Position anatomique approximative de chaque zone sur le schema.
const ZONE_SHAPES: Record<ZoneKey, ZoneShape> = {
  front: { cx: 100, cy: 60, rx: 46, ry: 21 },
  glabelle: { cx: 100, cy: 87, rx: 11, ry: 9 },
  tempe_g: { cx: 46, cy: 76, rx: 15, ry: 19 },
  tempe_d: { cx: 154, cy: 76, rx: 15, ry: 19 },
  sous_yeux_g: { cx: 68, cy: 110, rx: 17, ry: 8 },
  sous_yeux_d: { cx: 132, cy: 110, rx: 17, ry: 8 },
  nez: { cx: 100, cy: 120, rx: 13, ry: 25 },
  joue_g: { cx: 58, cy: 142, rx: 24, ry: 27 },
  joue_d: { cx: 142, cy: 142, rx: 24, ry: 27 },
  peri_oral: { cx: 100, cy: 174, rx: 27, ry: 15 },
  machoire_g: { cx: 62, cy: 192, rx: 21, ry: 21 },
  machoire_d: { cx: 138, cy: 192, rx: 21, ry: 21 },
  menton: { cx: 100, cy: 210, rx: 21, ry: 17 },
};

/**
 * L'echelle de teinte : corail (zone la plus chargee) vers terre (peau nette).
 *
 * Elle finissait sur deux verts acides, restes d'une palette abandonnee, et
 * passait par des pastels si clairs qu'ecrits en texte sur le fond creme ils
 * devenaient illisibles — un score de 72 sortait en beige pale.
 *
 * Deux teintes de la marque, et rien entre les deux qui n'en soit un melange :
 * la charge se lit dans la SATURATION, pas dans un changement de famille de
 * couleur. Toutes les valeurs de l'echelle restent lisibles en texte.
 */
const SCALE: { at: number; hex: string }[] = [
  { at: 0, hex: "#FF4D6D" },
  { at: 40, hex: "#D14A5C" },
  { at: 70, hex: "#8C3D42" },
  { at: 100, hex: "#2A1D18" },
];

function hexToRgb(h: string) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function scoreColor(score: number): string {
  const s = Math.max(0, Math.min(100, score));
  let lo = SCALE[0];
  let hi = SCALE[SCALE.length - 1];
  for (let i = 0; i < SCALE.length - 1; i++) {
    if (s >= SCALE[i].at && s <= SCALE[i + 1].at) {
      lo = SCALE[i];
      hi = SCALE[i + 1];
      break;
    }
  }
  const span = hi.at - lo.at || 1;
  const t = (s - lo.at) / span;
  const a = hexToRgb(lo.hex);
  const b = hexToRgb(hi.hex);
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

const LESION_COLOR: Record<string, string> = {
  papule: "#E23A59",
  pustule: "#FFB020",
  comedon: "#5C4A42",
  marque_rouge: "#FF8FA3",
  marque_brune: "#A8724F",
};

interface Props {
  zoneScores: Partial<Record<ZoneKey, number>>;
  lesions?: Lesion[];
  /** Zone mise en avant (tap ou selection externe). */
  selected?: ZoneKey | null;
  onSelectZone?: (zone: ZoneKey | null) => void;
  showLesions?: boolean;
  size?: number;
  /**
   * Confiance de mesure par zone (Personal Skin Map, chantier 5) — quand
   * fournie, une zone "low" se dessine en pointillé au lieu d'être teintée :
   * "pas encore assez mesurée", jamais "mauvais état". N'affecte aucun appel
   * existant qui ne passe pas cette prop.
   */
  zoneConfidence?: Partial<Record<ZoneKey, Confidence>>;
}

const AnimatedEllipse = Animated.createAnimatedComponent(Ellipse);

/** Zone pas encore assez mesurée : un contour qui se trace, jamais un remplissage. */
function ZoneOutline({ shape, delay }: { shape: ZoneShape; delay: number }) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withDelay(delay, withTiming(1, { duration: 460, easing: ease.out }));
  }, [t, delay]);
  const props = useAnimatedProps(() => ({ opacity: 0.5 * t.value }));
  return (
    <AnimatedEllipse
      cx={shape.cx}
      cy={shape.cy}
      rx={shape.rx}
      ry={shape.ry}
      fill="none"
      stroke={colors.fgDim}
      strokeWidth={1}
      strokeDasharray="2 3"
      animatedProps={props}
    />
  );
}

/**
 * Une zone qui s'allume.
 *
 * L'opacite est portee par une valeur animee plutot que posee directement :
 * la carte se revele zone par zone, ce qui donne a lire un releve en train de
 * se construire au lieu d'une image deja faite.
 */
function ZoneEllipse({
  shape,
  fill,
  opacity,
  selected,
  delay,
}: {
  shape: ZoneShape;
  fill: string;
  opacity: number;
  selected: boolean;
  delay: number;
}) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withDelay(delay, withTiming(1, { duration: 460, easing: ease.out }));
  }, [t, delay]);

  const props = useAnimatedProps(() => ({ opacity: opacity * t.value }));

  return (
    <AnimatedEllipse
      cx={shape.cx}
      cy={shape.cy}
      rx={shape.rx}
      ry={shape.ry}
      fill={fill}
      stroke={selected ? colors.fg : "transparent"}
      strokeWidth={selected ? 1.6 : 0}
      animatedProps={props}
    />
  );
}

export function FaceZoneMap({
  zoneScores,
  lesions = [],
  selected = null,
  onSelectZone,
  showLesions = true,
  size = 260,
  zoneConfidence,
}: Props) {
  const height = size * (VB_H / VB_W);

  const entries = useMemo(
    () => (Object.keys(ZONE_SHAPES) as ZoneKey[]).map((k) => ({
      key: k,
      shape: ZONE_SHAPES[k],
      score: zoneScores[k],
    })),
    [zoneScores],
  );

  const analysed = entries.filter((e) => typeof e.score === "number");
  const worst = useMemo(() => {
    if (!analysed.length) return null;
    return analysed.reduce((a, b) => ((a.score ?? 100) <= (b.score ?? 100) ? a : b));
  }, [analysed]);

  return (
    <View style={styles.wrap}>
      <Svg width={size} height={height} viewBox={`0 0 ${VB_W} ${VB_H}`}>
        <Defs>
          <ClipPath id="faceClip">
            <Path d={FACE_PATH} />
          </ClipPath>
        </Defs>

        <G clipPath="url(#faceClip)">
          {entries.map(({ key, shape, score }, i) => {
            const measured = typeof score === "number";
            if (measured && zoneConfidence?.[key] === "low") {
              return <ZoneOutline key={key} shape={shape} delay={i * 55} />;
            }
            const isSel = selected === key;
            // L'opacite suit la charge de la zone, pas seulement sa teinte. Une
            // zone saine doit s'effacer dans le fond : peindre en vert vif ce
            // qui va bien attire l'oeil au mauvais endroit. Ce qui demande de
            // l'attention est ce qui doit ressortir.
            const burden = measured ? 1 - (score as number) / 100 : 0;
            // En dessous de ce seuil, la zone n'est PAS peinte du tout.
            // Auparavant toute zone mesuree recevait un fond, meme nette :
            // treize taches grises dont douze ne signalaient rien, et l'oeil
            // ne savait plus ou regarder. Une carte de charge ne montre que
            // ce qui est charge.
            const SEUIL = 0.2;
            const visible = measured && (burden > SEUIL || isSel);
            const opacity = visible
              ? Math.min(0.9, ((burden - SEUIL) / (1 - SEUIL)) * 0.85 + (isSel ? 0.22 : 0.06))
              : 0;
            return (
              <ZoneEllipse
                key={key}
                shape={shape}
                fill={measured ? scoreColor(score as number) : "transparent"}
                opacity={opacity}
                selected={isSel}
                // Les zones s'allument l'une apres l'autre : une carte qui
                // apparait d'un bloc ressemble a une image, pas a un releve.
                delay={i * 55}
              />
            );
          })}

          {showLesions &&
            lesions.map((l, i) => (
              <Circle
                key={`l${i}`}
                cx={FACE_BOX.x + l.x * FACE_BOX.w}
                cy={FACE_BOX.y + l.y * FACE_BOX.h}
                // Un plancher plus haut qu'avant : a 1,8 unite sur un schema
                // de 200, une lesion disparaissait dans la teinte de sa zone.
                r={Math.max(3.2, Math.min(6, l.radius * 150))}
                fill={LESION_COLOR[l.type] ?? colors.fg}
                stroke={colors.bg}
                strokeWidth={1.2}
                opacity={0.95}
              />
            ))}
        </G>

        {/* Le contour, par dessus. Rien d'autre : ni yeux, ni bouche, ni teint. */}
        <Path d={FACE_PATH} fill="none" stroke={colors.fg} strokeWidth={2} opacity={0.5} />
      </Svg>

      {/* Zones cliquables, superposees au SVG */}
      {onSelectZone && (
        <View style={[StyleSheet.absoluteFill, { width: size, height }]} pointerEvents="box-none">
          {entries.map(({ key, shape, score }) => {
            if (typeof score !== "number") return null;
            const sx = size / VB_W;
            return (
              <Pressable
                key={`hit-${key}`}
                accessibilityRole="button"
                accessibilityLabel={`${ZONE_LABEL[key]}, note ${score} sur 100`}
                onPress={() => onSelectZone(selected === key ? null : key)}
                style={{
                  position: "absolute",
                  left: (shape.cx - shape.rx) * sx,
                  top: (shape.cy - shape.ry) * sx,
                  width: shape.rx * 2 * sx,
                  height: shape.ry * 2 * sx,
                  borderRadius: shape.rx * sx,
                }}
              />
            );
          })}
        </View>
      )}

      {worst && (
        <Text style={styles.caption}>
          Zone la plus chargée : {ZONE_LABEL[worst.key]} · {worst.score}/100
        </Text>
      )}
    </View>
  );
}

/** Legende de l'echelle de couleur. */
export function ZoneLegend() {
  const stops = [40, 60, 75, 88, 100];
  return (
    <View style={styles.legend}>
      <Text style={styles.legendEnd}>Chargée</Text>
      <View style={styles.legendBar}>
        {stops.map((s) => (
          <View key={s} style={[styles.legendChip, { backgroundColor: scoreColor(s) }]} />
        ))}
      </View>
      <Text style={styles.legendEnd}>Nette</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center" },
  caption: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.fgMuted,
    marginTop: spacing.s,
    textAlign: "center",
  },
  legend: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    marginTop: spacing.s,
  },
  legendBar: { flexDirection: "row", gap: 3 },
  legendChip: { width: 22, height: 7, borderRadius: 4 },
  legendEnd: {
    fontFamily: fonts.body,
    fontSize: 10,
    color: colors.fgDim,
    letterSpacing: 0.4,
  },
});
