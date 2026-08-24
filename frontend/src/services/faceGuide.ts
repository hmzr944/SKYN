/**
 * Le guidage live.
 *
 * Un detecteur de visage tourne sur le flux video et dit, image par image, ce
 * qu'il faut corriger : trop loin, trop pres, decentre, tete pas assez
 * tournee. C'est la difference entre "prenez une photo et croisez les doigts"
 * et un scan qui se declenche seul quand le cadrage est reellement bon.
 *
 * Le detecteur est charge a la demande depuis /mediapipe : 11 Mo de WASM
 * n'ont rien a faire dans le bundle principal, et l'ecran doit rester
 * utilisable si le chargement echoue — le guidage est un confort, pas une
 * condition.
 */

export type GuideState =
  | "loading"
  | "searching"
  | "too_far"
  | "too_close"
  | "off_center"
  | "tilted"
  | "turn_more"
  | "turn_other"
  | "perfect";

/** 0 = face, 1 = profil droit, 2 = profil gauche. */
export type ScanStep = 0 | 1 | 2;

export const STEPS: {
  label: string;
  title: string;
  hint: string;
}[] = [
  {
    label: "Face",
    title: "Regardez droit devant vous",
    hint: "Visage au centre du contour, cheveux dégagés",
  },
  {
    label: "Profil droit",
    title: "Tournez lentement la tête à droite",
    hint: "Jusqu'à voir votre joue droite entière",
  },
  {
    label: "Profil gauche",
    title: "Maintenant à gauche",
    hint: "Le moteur compare les deux côtés",
  },
];

/** Ce qui s'affiche pour chaque etat, par etape. */
export function guideMessage(state: GuideState, step: ScanStep): string {
  switch (state) {
    case "loading":
      return "Préparation du guidage…";
    case "searching":
      return "Aucun visage détecté";
    case "too_far":
      return "Rapprochez-vous";
    case "too_close":
      return "Reculez un peu";
    case "off_center":
      return "Centrez votre visage";
    case "tilted":
      return "Redressez la tête";
    case "turn_more":
      return step === 1 ? "Tournez davantage à droite" : "Tournez davantage à gauche";
    case "turn_other":
      return "De l'autre côté";
    case "perfect":
      return step === 0 ? "Parfait, ne bougez plus" : "Parfait, tenez la pose";
  }
}

/** Seuils de cadrage. Regroupes ici pour etre lisibles et ajustables. */
const T = {
  /** Hauteur du visage rapportee a la hauteur de l'image. */
  farFace: 0.3,
  closeFace: 0.62,
  farProfile: 0.24,
  /** Ecart tolere au centre. */
  offX: 0.14,
  offY: 0.16,
  /** Au-dela, la tete est consideree tournee. */
  straightYaw: 0.22,
  turnedYaw: 0.25,
};

export interface Detection {
  /** Hauteur du visage / hauteur de l'image. */
  hRatio: number;
  /** Centre du visage, normalise. */
  cx: number;
  cy: number;
  /** Orientation : 0 = face, |yaw| grand = profil. Signe = cote. */
  yaw: number;
}

/**
 * Verdict de cadrage.
 *
 * `sideSign` est le signe du yaw enregistre au profil droit : au profil
 * gauche, on exige le signe oppose, sinon quelqu'un qui retourne du meme cote
 * validerait deux fois la meme joue.
 */
export function evaluate(d: Detection | null, step: ScanStep, sideSign: number): GuideState {
  if (!d) return "searching";

  if (step === 0) {
    if (d.hRatio < T.farFace) return "too_far";
    if (d.hRatio > T.closeFace) return "too_close";
    if (Math.abs(d.cx - 0.5) > T.offX || Math.abs(d.cy - 0.5) > T.offY) return "off_center";
    if (Math.abs(d.yaw) > T.straightYaw) return "tilted";
    return "perfect";
  }

  if (d.hRatio < T.farProfile) return "too_far";
  if (Math.abs(d.yaw) < T.turnedYaw) return "turn_more";
  if (step === 2 && sideSign !== 0 && Math.sign(d.yaw) === sideSign) return "turn_other";
  return "perfect";
}

/**
 * Lit une image du flux et en tire une detection.
 * Les points cles de BlazeFace donnent oeil droit, oeil gauche, nez : la
 * position du nez entre les deux yeux sert d'estimation d'orientation.
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

/** Duree de maintien du bon cadrage avant declenchement automatique. */
export const AUTO_CAPTURE_MS = 900;
