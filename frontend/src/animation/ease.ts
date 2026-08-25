/**
 * Les courbes de GSAP, portees sur le thread d'animation.
 *
 * POURQUOI PORTER PLUTOT QU'INSTALLER. GSAP anime des noeuds du DOM. Sur iOS
 * et Android il n'y a pas de DOM : la bibliotheque s'installerait sans rien
 * animer, et l'app ne bougerait que dans un navigateur — soit exactement la
 * plateforme qui n'est pas la cible. Ce qui se transporte, en revanche, c'est
 * le VOCABULAIRE : ces courbes sont des formules, et une formule se recopie
 * fidelement.
 *
 * Chaque fonction est un worklet : elle est appelee des dizaines de fois par
 * seconde depuis le thread d'animation, jamais depuis JavaScript.
 *
 * Les valeurs sont celles de GSAP, pas des approximations « qui ressemblent » :
 * power1 est quadratique, power2 cubique, power3 quartique, power4 quintique,
 * et le depassement par defaut de `back` vaut 1,70158 comme chez Penner, dont
 * GSAP herite.
 */

/* ------------------------------------------------------------------ */
/* Familles polynomiales : power1 a power4                            */
/* ------------------------------------------------------------------ */

/** p^n — depart lent, arrivee lancee. */
export function powerIn(n: number) {
  return (p: number) => {
    "worklet";
    return Math.pow(p, n);
  };
}

/** 1 - (1-p)^n — depart lance, arrivee posee. Le plus utile en interface. */
export function powerOut(n: number) {
  return (p: number) => {
    "worklet";
    return 1 - Math.pow(1 - p, n);
  };
}

/** Symetrique : lent aux deux bouts, rapide au milieu. */
export function powerInOut(n: number) {
  return (p: number) => {
    "worklet";
    return p < 0.5
      ? Math.pow(2 * p, n) / 2
      : 1 - Math.pow(2 * (1 - p), n) / 2;
  };
}

/* ------------------------------------------------------------------ */
/* Sinusoidale — la plus douce, presque imperceptible                  */
/* ------------------------------------------------------------------ */

export function sineIn(p: number) {
  "worklet";
  return 1 - Math.cos((p * Math.PI) / 2);
}

export function sineOut(p: number) {
  "worklet";
  return Math.sin((p * Math.PI) / 2);
}

export function sineInOut(p: number) {
  "worklet";
  return -(Math.cos(Math.PI * p) - 1) / 2;
}

/* ------------------------------------------------------------------ */
/* Exponentielle — le contraste le plus fort entre debut et fin        */
/* ------------------------------------------------------------------ */

export function expoIn(p: number) {
  "worklet";
  return p === 0 ? 0 : Math.pow(2, 10 * (p - 1));
}

export function expoOut(p: number) {
  "worklet";
  return p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
}

export function expoInOut(p: number) {
  "worklet";
  if (p === 0) return 0;
  if (p === 1) return 1;
  return p < 0.5
    ? Math.pow(2, 20 * p - 10) / 2
    : (2 - Math.pow(2, -20 * p + 10)) / 2;
}

/* ------------------------------------------------------------------ */
/* Circulaire — accelere puis freine sur un quart de cercle            */
/* ------------------------------------------------------------------ */

export function circIn(p: number) {
  "worklet";
  return 1 - Math.sqrt(1 - p * p);
}

export function circOut(p: number) {
  "worklet";
  return Math.sqrt(1 - (p - 1) * (p - 1));
}

/* ------------------------------------------------------------------ */
/* Back — depassement franc, sans oscillation                          */
/* ------------------------------------------------------------------ */

/** Depassement par defaut de GSAP. */
export const BACK = 1.70158;

/** Recule avant de partir. */
export function backIn(s: number = BACK) {
  return (p: number) => {
    "worklet";
    return p * p * ((s + 1) * p - s);
  };
}

/** Depasse la cible puis revient. C'est le geste d'un objet qui se pose. */
export function backOut(s: number = BACK) {
  return (p: number) => {
    "worklet";
    const q = p - 1;
    return 1 + q * q * ((s + 1) * q + s);
  };
}

/* ------------------------------------------------------------------ */
/* Elastic — depassement qui oscille avant de se stabiliser            */
/* ------------------------------------------------------------------ */

/**
 * `amplitude` >= 1 : hauteur du premier depassement.
 * `period` : duree d'une oscillation, en fraction de la duree totale.
 */
export function elasticOut(amplitude: number = 1, period: number = 0.3) {
  const a = Math.max(1, amplitude);
  const s = (period / (2 * Math.PI)) * Math.asin(1 / a);
  return (p: number) => {
    "worklet";
    if (p === 0) return 0;
    if (p === 1) return 1;
    return a * Math.pow(2, -10 * p) * Math.sin(((p - s) * (2 * Math.PI)) / period) + 1;
  };
}

/* ------------------------------------------------------------------ */
/* Bounce — rebonds successifs, amortis                                */
/* ------------------------------------------------------------------ */

export function bounceOut(p: number) {
  "worklet";
  const n = 7.5625;
  const d = 2.75;
  if (p < 1 / d) return n * p * p;
  if (p < 2 / d) {
    const q = p - 1.5 / d;
    return n * q * q + 0.75;
  }
  if (p < 2.5 / d) {
    const q = p - 2.25 / d;
    return n * q * q + 0.9375;
  }
  const q = p - 2.625 / d;
  return n * q * q + 0.984375;
}

/* ------------------------------------------------------------------ */
/* Le vocabulaire utilise dans l'app                                   */
/* ------------------------------------------------------------------ */

/**
 * Les courbes nommees, telles qu'on les ecrirait chez GSAP.
 *
 * On n'en garde qu'une poignee, volontairement. Un catalogue complet invite a
 * varier la courbe d'un ecran a l'autre, et c'est ce qui fait qu'une app
 * parait assemblee de plusieurs mains. Le mouvement se reconnait a sa
 * constance, pas a sa variete.
 */
export const ease = {
  /** Linéaire. Reserve a ce qui est deja courbe par ailleurs. */
  none: (p: number) => {
    "worklet";
    return p;
  },

  /** Entree standard d'un contenu. L'equivalent de `power2.out`. */
  out: powerOut(3),
  /** Sortie standard. `power2.in`. */
  in: powerIn(3),
  /** Deplacement d'un objet deja visible. `power3.inOut`. */
  inOut: powerInOut(4),

  /** Le plus franc : demarre a pleine vitesse et s'arrete long. `expo.out`. */
  expoOut,
  /** Le plus doux, presque invisible. `sine.inOut`. */
  sineInOut,

  /** Un objet qui se pose en depassant legerement. `back.out(1.7)`. */
  drop: backOut(BACK),
  /** Depassement appuye, pour un evenement rare. `back.out(2.6)`. */
  dropStrong: backOut(2.6),
  /** Oscillation amortie. `elastic.out(1, 0.35)`. */
  elastic: elasticOut(1, 0.35),
} as const;
