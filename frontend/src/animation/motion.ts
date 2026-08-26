/**
 * Le vocabulaire de mouvement de l'app.
 *
 * Les valeurs viennent du skill motion/framer-motion : ce sont ses reglages de
 * ressort nommes, repris tels quels plutot que redecouverts a l'oeil. Un
 * ressort se decrit par trois nombres, et deux composants qui en choisissent
 * chacun de leur cote ne bougent jamais tout a fait pareil — c'est ce qui fait
 * qu'une app parait assemblee de plusieurs mains.
 *
 * `type: "spring"` et `type: "timing"` sont les deux formes que Moti attend.
 * On les pre-remplit ici pour qu'aucun ecran n'ait a inventer sa physique.
 */

/** Ressorts du skill : raideur, amortissement, masse. */
export const spring = {
  /** Le defaut. Se pose franchement, sans rebond parasite. */
  gentle: { type: "spring", stiffness: 100, damping: 20, mass: 1 },
  /** Rebond marque. A reserver a ce qui arrive rarement. */
  wobbly: { type: "spring", stiffness: 200, damping: 10, mass: 1 },
  /** Reponse immediate, sans depassement. Pour ce qui suit le doigt. */
  stiff: { type: "spring", stiffness: 400, damping: 30, mass: 1 },
  /** Lent et lourd. Pour une masse qui se deplace. */
  slow: { type: "spring", stiffness: 50, damping: 20, mass: 1 },
} as const;

/** Durees, quand une duree exacte compte plus qu'une physique. */
export const duration = {
  instant: 110,
  fast: 180,
  base: 260,
  slow: 420,
  /** Un trace qui se dessine : assez long pour qu'on suive la pointe. */
  draw: 760,
} as const;

/**
 * Decalage entre enfants d'une meme sequence.
 *
 * Le skill le nomme `staggerChildren` et le donne en secondes ; Moti l'exprime
 * en millisecondes via `delay`. On garde ici des millisecondes, l'unite de
 * tout le reste de l'app.
 */
export const stagger = {
  /** Lettres d'un mot : tres serre, sinon le mot se disloque. */
  letters: 52,
  /** Elements d'une liste. */
  items: 60,
  /** Blocs d'un ecran. */
  blocks: 90,
} as const;

/** Retard d'un enfant selon son rang, avec un retard d'ensemble. */
export function childDelay(index: number, step: number, base = 0) {
  return base + index * step;
}
