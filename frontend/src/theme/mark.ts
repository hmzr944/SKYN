/**
 * La geometrie de la marque, et celle du scan.
 *
 * DEUX FORMES, deux roles, et il ne faut pas les confondre :
 *
 *   · Le S — c'est le LOGO. Il ne sert qu'a signer.
 *   · L'ovale de visage — c'est un OUTIL. Il cadre un visage a l'ecran de
 *     scan et sert de repere sur la cartographie. Il ne signe rien.
 *
 * Le logo etait auparavant cet ovale. C'etait elegant, mais un contour de
 * visage sur un ecran d'accueil ne dit pas le nom de la marque, et il entrait
 * en concurrence avec la fenetre de visee qui a exactement la meme forme.
 */

/**
 * Le S.
 *
 * Pas la lettre d'une fonte : une courbe a tension variable, largement ouverte
 * en haut et refermee court en bas, dessinee d'un seul trait. Le point corail
 * est pose sur le PROLONGEMENT du terminus superieur — il n'est pas a cote du
 * S, il vient d'en sortir. Un mouvement inscrit dans une forme immobile, et le
 * point de depart tout trouve pour l'animation d'ouverture.
 *
 * Le trace commence a ce terminus : dessiner le S de 100 % a 0 % de decalage
 * le fait donc naitre du point.
 */
export const MARK_PATH =
  "M43,21 C38,11 25,9 19,17 C13,25 21,32 31,34 " +
  "C42,36 46,42 42,48 C38,54 28,56 21,49";

/**
 * Longueur du trace, mesuree au navigateur (getTotalLength = 100,39) puis
 * arrondie au-dessus : react-native-svg n'expose pas getTotalLength, et une
 * valeur trop courte laisserait un bout de trait visible au repos.
 */
export const MARK_LENGTH = 100.5;

/** Le point corail, sur la trajectoire du terminus superieur. */
export const MARK_DOT = { x: 48.5, y: 14.5, r: 4.2 } as const;

/** Encombrement visuel du logo, point et epaisseur de trait compris. */
export const MARK_EXTENT = { x: 14.8, y: 10.3, w: 37.9, h: 45.3 } as const;
/** Centre optique du logo, pour le centrer sans le decaler. */
export const MARK_CENTER = { x: 33.8, y: 32.9 } as const;

/**
 * L'ovale de visage, cote outil.
 *
 * Repere : viewBox 0 0 64 64. Largeur aux tempes 36, hauteur 44 — les
 * proportions d'un visage. Le menton est large et arrondi : deux flancs qui
 * convergeraient en un point donneraient une epingle de carte, pas un visage.
 */

/**
 * Le contour ouvert. Part de la pommette droite, descend la machoire,
 * contourne le menton, remonte le flanc gauche et traverse le front. Il
 * s'arrete avant d'avoir referme — la breche accueille le point corail.
 */
export const FACE_PATH =
  "M49.5,26 C50.4,33.5 49,42 45,47.6 C42,51.2 37.4,53.6 32,54.5 " +
  "C26.6,53.6 22,51.2 19,47.6 C15,42 13.6,33.5 14.5,26 " +
  "C15.6,17.5 22,10.6 30,10.2 C32.6,10.05 35.7,10.1 38,10.3";

/**
 * Longueur du trace ouvert, mesuree au navigateur (getTotalLength = 107,134)
 * puis arrondie au-dessus : react-native-svg n'expose pas getTotalLength, et
 * une valeur trop courte laisserait un bout de contour visible au repos.
 */
export const FACE_LENGTH = 107.2;

/** Le meme ovale, referme — sert de masque pour la photo et les zones. */
export const FACE_CLOSED =
  "M32,10.2 C40,10.4 49,17.5 49.5,26 C50.4,33.5 49,42 45,47.6 " +
  "C42,51.2 37.4,53.6 32,54.5 C26.6,53.6 22,51.2 19,47.6 " +
  "C15,42 13.6,33.5 14.5,26 C15.6,17.5 24,10.4 32,10.2 Z";

/** Le repere du dessin : tout est exprime dans ce carre. */
export const MARK_VIEWBOX = 64;

/**
 * Epaisseur du trait et taille du point, selon la taille de rendu.
 *
 * Plus le logo est petit, plus le trait doit epaissir en proportion : a 20 px,
 * un trait a l'echelle exacte du dessin devient un cheveu et la forme
 * disparait.
 */
export function markMetrics(size: number) {
  if (size < 24) return { stroke: 6.6, dot: 5.6 };
  if (size < 34) return { stroke: 5.4, dot: 5.0 };
  if (size < 56) return { stroke: 4.6, dot: 4.6 };
  return { stroke: 4.2, dot: 4.2 };
}

/**
 * Le contour ferme, decompose en nombres, et de quoi le reconstruire ailleurs.
 *
 * L'ecran de scan doit poser ce contour sur le visage detecte, et le suivre
 * image par image. Passer par un `transform` SVG anime supposerait que la
 * couche web repercute bien un attribut de transformation sur un groupe, ce
 * dont on n'a aucune garantie ; recalculer la chaine `d` ne suppose rien : ce
 * n'est qu'une propriete texte comme une autre.
 *
 * L'ordre est celui du chemin : deux nombres pour le point de depart, puis six
 * par courbe cubique.
 */
export const FACE_CLOSED_NUMBERS = [32, 10.2, 40, 10.4, 49, 17.5, 49.5, 26, 50.4, 33.5, 49, 42, 45, 47.6, 42, 51.2, 37.4, 53.6, 32, 54.5, 26.6, 53.6, 22, 51.2, 19, 47.6, 15, 42, 13.6, 33.5, 14.5, 26, 15.6, 17.5, 24, 10.4, 32, 10.2] as const;

/** Le centre de l'encombrement du contour, mesure au navigateur (getBBox). */
export const FACE_CENTER = { x: 32.0, y: 32.35 } as const;
/** Encombrement du contour : 35,524 x 44,3 dans le repere de 64. */
export const FACE_EXTENT = { w: 35.524, h: 44.3 } as const;

/**
 * Le contour ferme, centre en (cx, cy) et mis a l'echelle k.
 *
 * Worklet : il est appele depuis le thread d'animation, a chaque image.
 */
export function facePathAt(cx: number, cy: number, k: number): string {
  "worklet";
  const n = FACE_CLOSED_NUMBERS;
  const X = (v: number) => (v - FACE_CENTER.x) * k + cx;
  const Y = (v: number) => (v - FACE_CENTER.y) * k + cy;
  let d = `M${X(n[0]).toFixed(2)},${Y(n[1]).toFixed(2)}`;
  for (let i = 2; i < n.length; i += 6) {
    d +=
      ` C${X(n[i]).toFixed(2)},${Y(n[i + 1]).toFixed(2)}` +
      ` ${X(n[i + 2]).toFixed(2)},${Y(n[i + 3]).toFixed(2)}` +
      ` ${X(n[i + 4]).toFixed(2)},${Y(n[i + 5]).toFixed(2)}`;
  }
  return d + "Z";
}
