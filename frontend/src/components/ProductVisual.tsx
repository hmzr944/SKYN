import Svg, { Circle, Path, Rect, Text as SvgText } from "react-native-svg";

import { colors, palette } from "@/src/theme";
import type { ProductPick } from "@/src/types/analysis";

/**
 * Le visuel d'un produit.
 *
 * Ce n'est PAS une photographie, et c'est assume. Les photos fiables n'existent
 * pas pour ce catalogue : sur les 56 produits, une base ouverte n'en couvre que
 * cinq avec une correspondance sure. Afficher la photo d'un autre produit a
 * cote d'une recommandation de soin serait pire que de ne rien afficher — on
 * enverrait quelqu'un acheter le mauvais flacon.
 *
 * On dessine donc une silhouette propre a l'etape (un flacon pompe n'est pas un
 * tube), avec l'initiale de la marque. Ca identifie le produit d'un coup d'oeil
 * dans une liste, sans jamais pretendre montrer l'objet reel.
 */

/** Chaque etape a sa forme : c'est elle qui rend la liste lisible. */
function shape(step: ProductPick["step"], stroke: string) {
  const common = { fill: "none", stroke, strokeWidth: 2, strokeLinejoin: "round" as const };
  switch (step) {
    case "nettoyant":
      // Flacon pompe, haut et etroit.
      return (
        <>
          <Rect x={17} y={22} width={22} height={30} rx={4} {...common} />
          <Path d="M24,22 V16 h8 v6" {...common} />
          <Path d="M28,16 V11 h6" {...common} />
        </>
      );
    case "serum":
    case "traitement":
      // Compte-gouttes : col fin et pipette.
      return (
        <>
          <Rect x={20} y={26} width={16} height={26} rx={3} {...common} />
          <Path d="M25,26 V19 h6 v7" {...common} />
          <Rect x={24} y={9} width={8} height={10} rx={3} {...common} />
        </>
      );
    case "hydratant":
      // Pot large et bas.
      return (
        <>
          <Rect x={14} y={28} width={28} height={22} rx={5} {...common} />
          <Path d="M14,34 h28" {...common} />
          <Rect x={18} y={20} width={20} height={8} rx={3} {...common} />
        </>
      );
    case "protection":
      // Tube avec bouchon rabattable, et un soleil.
      return (
        <>
          <Path d="M20,24 h16 v24 a4,4 0 0 1 -4,4 h-8 a4,4 0 0 1 -4,-4 z" {...common} />
          <Rect x={22} y={16} width={12} height={8} rx={2} {...common} />
          <Circle cx={40} cy={16} r={5} {...common} />
        </>
      );
    default:
      // Masque : sachet.
      return (
        <>
          <Path d="M16,20 h24 v30 a2,2 0 0 1 -2,2 h-20 a2,2 0 0 1 -2,-2 z" {...common} />
          <Path d="M16,26 h24" {...common} />
        </>
      );
  }
}

export function ProductVisual({ product, size = 56 }: { product: ProductPick; size?: number }) {
  const initial = (product.brand || "?").trim().charAt(0).toUpperCase();
  return (
    <Svg width={size} height={size} viewBox="0 0 56 64">
      <Rect x={0} y={0} width={56} height={64} rx={12} fill={colors.surfaceSunken} />
      {shape(product.step, palette.terre)}
      <SvgText
        x={28}
        y={62}
        fontSize={9}
        fontWeight="700"
        fill={colors.fgDim}
        textAnchor="middle"
      >
        {initial}
      </SvgText>
    </Svg>
  );
}
