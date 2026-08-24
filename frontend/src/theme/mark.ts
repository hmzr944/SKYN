/**
 * La geometrie de la marque, partagee.
 *
 * Le symbole et l'ecran d'analyse tracent le MEME contour : le logo n'illustre
 * pas le scan, il est le scan. C'est ce qui fait qu'une capture ressemble a la
 * marque et que la marque ressemble a ce que fait l'app.
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

/** Le point corail, dans la breche. */
export const MARK_DOT = { x: 45, y: 16.5 } as const;

/** Le repere du dessin : tout est exprime dans ce carre. */
export const MARK_VIEWBOX = 64;

/**
 * Le cap arrondi mange stroke/2 de chaque cote de la breche : plus le trait est
 * epais, plus le point doit grossir pour rester lisible en face de lui.
 */
export function markMetrics(size: number) {
  if (size < 24) return { stroke: 7.4, dot: 7.4 };
  if (size < 34) return { stroke: 5.6, dot: 6 };
  if (size < 56) return { stroke: 4.4, dot: 5.2 };
  return { stroke: 3.4, dot: 4.6 };
}
