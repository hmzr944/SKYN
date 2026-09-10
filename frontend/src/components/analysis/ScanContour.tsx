import { useEffect, useMemo } from "react";
import { Canvas, Group, Path, Skia, SweepGradient, vec } from "@shopify/react-native-skia";
import {
  Easing,
  useDerivedValue,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { colors } from "@/src/theme";
import { FACE_CLOSED, MARK_VIEWBOX } from "@/src/theme/mark";

/**
 * Le contour du champ d'analyse — sur Skia, pas sur react-native-svg.
 *
 * L'ancienne version tracait le contour OUVERT (FACE_PATH, avec la breche de
 * la marque) du neant jusqu'au complet, tenait une pose, puis revenait a zero
 * en UNE frame (`withTiming(0, {duration: 0})`) pour reboucler. Deux defauts
 * se cumulaient : la breche faisait que le trace ne se refermait jamais
 * vraiment, et le retour instantane se voyait comme un sursaut plutot que
 * comme une boucle — signale deux fois : « ca tourne mais ca va pas jusqu'au
 * bout de la boucle ».
 *
 * Ici, deux calques sur le contour FERME (FACE_CLOSED) :
 *  - un anneau complet, discret, TOUJOURS entier — plus jamais l'impression
 *    d'un tour qui ne se termine pas ;
 *  - une comete qui tourne sans fin, un degrade conique (SweepGradient) dont
 *    on fait pivoter l'origine en continu. Une rotation complete boucle par
 *    construction : il n'y a pas de redemarrage a masquer, donc pas de
 *    sursaut a produire.
 */
export function ScanContour({ size }: { size: number }) {
  const reduced = useReducedMotion();
  const angle = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    angle.value = withRepeat(
      withTiming(Math.PI * 2, { duration: 2600, easing: Easing.linear }),
      -1,
      false,
    );
  }, [reduced, angle]);

  const facePath = useMemo(() => Skia.Path.MakeFromSVGString(FACE_CLOSED)!, []);
  const center = useMemo(() => {
    const b = facePath.getBounds();
    return vec(b.x + b.width / 2, b.y + b.height / 2);
  }, [facePath]);

  const transform = useDerivedValue(() => [{ rotate: angle.value }], [angle]);
  const scale = size / MARK_VIEWBOX;

  return (
    <Canvas style={{ width: size, height: size }} pointerEvents="none">
      <Group transform={[{ scale }]}>
        {/* L'anneau, entier en permanence. */}
        <Path
          path={facePath}
          style="stroke"
          strokeWidth={1}
          strokeCap="round"
          color={colors.accent}
          opacity={0.24}
        />
        {/* La comete : meme trace, coloree par un degrade conique qui tourne. */}
        <Path path={facePath} style="stroke" strokeWidth={1.4} strokeCap="round">
          <SweepGradient
            c={center}
            colors={["transparent", "transparent", colors.accent, "transparent"]}
            positions={[0, 0.62, 0.86, 1]}
            origin={center}
            transform={transform}
          />
        </Path>
      </Group>
    </Canvas>
  );
}

// Export par defaut : WithSkiaWeb (voir ScanField.tsx) importe ce composant
// dynamiquement APRES le chargement de CanvasKit sur le web — necessaire ici
// specifiquement, puisque l'objet `Skia` du module web se construit une
// seule fois, a l'evaluation du fichier qui l'importe. Un import statique
// depuis ScanField.tsx evaluerait ce module trop tot, avant que le WASM soit
// pret, et figerait un `Skia` casse pour toute la duree de vie de l'appli.
export default ScanContour;
