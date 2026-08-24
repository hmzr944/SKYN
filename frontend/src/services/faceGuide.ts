/**
 * Le guidage live.
 *
 * Le principe est celui de l'enregistrement Face ID : une seule session
 * continue pendant laquelle on tourne lentement la tete, et l'app echantillonne
 * toute seule au fur et a mesure. Il n'y a pas de "prise de photo" — pas de
 * compte a rebours, pas de declencheur, pas d'etapes numerotees. On tourne, la
 * couverture se remplit, c'est fini.
 *
 * L'echantillonnage sous plusieurs angles n'est pas cosmetique : de face, les
 * joues et les tempes sont vues en raccourci, et leur relief disparait. Les
 * angles lateraux les exposent.
 *
 * Le detecteur est charge a la demande : 11 Mo de WASM n'ont rien a faire dans
 * le bundle principal, et l'ecran doit rester utilisable si le chargement
 * echoue — le guidage est un confort, pas une condition.
 */

export type GuideState =
  | "loading"
  | "searching"
  | "too_far"
  | "too_close"
  | "off_center"
  | "turn_left"
  | "turn_right"
  | "hold"
  | "done";

/** Les angles a couvrir. */
export type Angle = "left" | "center" | "right";
export const ANGLES: Angle[] = ["center", "right", "left"];

/** Seuils de cadrage et d'orientation. */
const T = {
  /** Hauteur du visage rapportee a la hauteur de l'image. */
  minFace: 0.26,
  maxFace: 0.66,
  /** Ecart tolere au centre — large, parce qu'on tourne la tete. */
  offX: 0.2,
  offY: 0.2,
  /** En deca, la tete est consideree de face. */
  center: 0.18,
  /** Au-dela, elle est consideree tournee. */
  turned: 0.28,
};

export interface Detection {
  hRatio: number;
  cx: number;
  cy: number;
  /** Orientation : 0 = face, negatif d'un cote, positif de l'autre. */
  yaw: number;
}

/** L'angle courant, ou null si la tete est entre deux positions. */
export function angleOf(yaw: number): Angle | null {
  if (Math.abs(yaw) < T.center) return "center";
  if (yaw >= T.turned) return "right";
  if (yaw <= -T.turned) return "left";
  return null;
}

/** Le cadrage est-il exploitable, independamment de l'orientation ? */
export function framingOk(d: Detection): boolean {
  return (
    d.hRatio >= T.minFace &&
    d.hRatio <= T.maxFace &&
    Math.abs(d.cx - 0.5) <= T.offX &&
    Math.abs(d.cy - 0.5) <= T.offY
  );
}

/**
 * Etat du guidage.
 *
 * L'ordre compte : on corrige d'abord le cadrage, puis on oriente. Demander de
 * tourner la tete a quelqu'un qui est hors champ ne sert a rien.
 */
export function evaluate(d: Detection | null, covered: Angle[]): GuideState {
  const reste = ANGLES.filter((a) => !covered.includes(a));
  if (reste.length === 0) return "done";
  if (!d) return "searching";

  if (d.hRatio < T.minFace) return "too_far";
  if (d.hRatio > T.maxFace) return "too_close";
  if (Math.abs(d.cx - 0.5) > T.offX || Math.abs(d.cy - 0.5) > T.offY) return "off_center";

  const ici = angleOf(d.yaw);
  // L'angle courant manque encore : on est au bon endroit, il suffit de tenir.
  if (ici && reste.includes(ici)) return "hold";

  // Sinon on oriente vers ce qui manque, en commençant par le plus proche.
  if (reste.includes("center")) return d.yaw > 0 ? "turn_left" : "turn_right";
  if (reste.includes("right")) return "turn_right";
  return "turn_left";
}

export function guideMessage(state: GuideState): string {
  switch (state) {
    case "loading":
      return "Préparation…";
    case "searching":
      return "Aucun visage détecté";
    case "too_far":
      return "Rapprochez-vous";
    case "too_close":
      return "Reculez un peu";
    case "off_center":
      return "Centrez votre visage";
    case "turn_left":
      return "Tournez lentement vers la gauche";
    case "turn_right":
      return "Tournez lentement vers la droite";
    case "hold":
      return "Ne bougez plus";
    case "done":
      return "Analyse en cours";
  }
}

/**
 * Lit une image du flux.
 *
 * Les points cles de BlazeFace donnent oeil droit, oeil gauche, nez : la
 * position du nez entre les deux yeux estime l'orientation.
 */
export function readDetection(res: any, videoW: number, videoH: number): Detection | null {
  const d = res?.detections?.[0];
  if (!d?.boundingBox) return null;
  const bb = d.boundingBox;
  const k = d.keypoints || [];

  let yaw = 0;
  if (k.length >= 3) {
    const eyeMid = (k[0].x + k[1].x) / 2;
    const inter = Math.abs(k[1].x - k[0].x) || 0.001;
    yaw = (k[2].x - eyeMid) / inter;
  }

  return {
    hRatio: bb.height / videoH,
    cx: (bb.originX + bb.width / 2) / videoW,
    cy: (bb.originY + bb.height / 2) / videoH,
    yaw,
  };
}

/**
 * Duree pendant laquelle l'angle doit tenir avant d'etre echantillonne.
 * Assez court pour ne pas peser dans une rotation continue, assez long pour
 * eviter une image floue prise en plein mouvement.
 */
export const HOLD_MS = 420;
