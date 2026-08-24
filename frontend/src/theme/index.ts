/**
 * SKYN — systeme de marque.
 *
 * TROIS TEINTES, rien d'autre. Chaque bordure, chaque texte secondaire, chaque
 * surface creusee est une OPACITE de l'une des trois. Aucun gris n'est jamais
 * introduit, aucune quatrieme couleur.
 *
 *   creme  60 %  le sol
 *   terre  30 %  structure, texte, surfaces inversees
 *   corail 10 %  accent seul — ce qui demande de l'attention
 *
 * Semantique : le corail ne decore pas. Il signale une zone a traiter. Ce qui
 * va bien est en terre, pas en vert — l'app n'a pas de couleur "positive".
 */

export const palette = {
  creme: "#FFF6F0",
  terre: "#2A1D18",
  corail: "#FF4D6D",
} as const;

/** Opacites de terre — la seule facon de creuser une surface. */
const t = (a: number) => `rgba(42, 29, 24, ${a})`;
/** Opacites de corail — reservees aux etats d'accent. */
const c = (a: number) => `rgba(255, 77, 109, ${a})`;
/** Opacites de creme — pour ce qui se pose sur le bloc terre. */
const k = (a: number) => `rgba(255, 246, 240, ${a})`;

export const colors = {
  // ————— sol —————
  bg: palette.creme,
  surface: t(0.04),
  surfaceRaised: t(0.04),
  surfaceSunken: t(0.07),

  // ————— texte —————
  fg: palette.terre,
  fgMuted: t(0.58),
  fgDim: t(0.38),
  fgFaint: t(0.14),

  // ————— bordures —————
  borderSubtle: t(0.07),
  borderMid: t(0.14),
  borderActive: palette.terre,

  // ————— accent : la zone qui demande de l'attention —————
  accent: palette.corail,
  accentDark: palette.corail,
  accentSoft: c(0.14),
  accentSofter: c(0.07),
  accentLine: c(0.45),
  onAccent: palette.creme,

  // ————— bloc terre : surfaces inversees —————
  inverse: palette.terre,
  onInverse: palette.creme,
  onInverseMuted: k(0.6),
  onInverseFaint: k(0.14),

  // ————— etat "rien a signaler" : terre, jamais une teinte positive —————
  ok: palette.terre,
  okSoft: t(0.1),
  okSofter: t(0.05),
  onOk: palette.creme,

  overlay: t(0.45),
  white: palette.creme,
} as const;

export const fonts = {
  logo: "Outfit_700Bold",
  heading: "Outfit_600SemiBold",
  headingMedium: "Outfit_500Medium",
  body: "Outfit_400Regular",
  bodyMedium: "Outfit_500Medium",
  bodyLight: "Outfit_300Light",
} as const;

/** Une seule famille : la hierarchie vient de la graisse et de la chasse. */
export const type = {
  display: { fontFamily: fonts.heading, fontSize: 34, lineHeight: 36, letterSpacing: -1.2 },
  title: { fontFamily: fonts.heading, fontSize: 24, lineHeight: 28, letterSpacing: -0.6 },
  subtitle: { fontFamily: fonts.headingMedium, fontSize: 18, lineHeight: 24, letterSpacing: -0.3 },
  body: { fontFamily: fonts.body, fontSize: 15, lineHeight: 23 },
  bodySmall: { fontFamily: fonts.body, fontSize: 13, lineHeight: 20 },
  label: { fontFamily: fonts.bodyMedium, fontSize: 13, lineHeight: 18 },
  kicker: {
    fontFamily: fonts.heading,
    fontSize: 10,
    lineHeight: 14,
    letterSpacing: 2.2,
    textTransform: "uppercase" as const,
  },
  wordmark: { fontFamily: fonts.logo, fontSize: 16, letterSpacing: 6.4 },
  number: { fontFamily: fonts.logo, fontSize: 46, lineHeight: 46, letterSpacing: -2 },
} as const;

export const spacing = {
  xs: 4,
  s: 8,
  m: 16,
  l: 24,
  xl: 32,
  xxl: 48,
  xxxl: 64,
} as const;

export const radius = {
  pill: 999,
  xl: 28,
  lg: 24,
  md: 16,
  sm: 10,
} as const;

export const shadow = {
  card: {
    shadowColor: palette.terre,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.06,
    shadowRadius: 16,
    elevation: 3,
  },
  raised: {
    shadowColor: palette.terre,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.1,
    shadowRadius: 24,
    elevation: 6,
  },
  button: {
    shadowColor: palette.corail,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.3,
    shadowRadius: 16,
    elevation: 5,
  },
} as const;

/**
 * Motion — un seul rythme pour toute l'app.
 * Regle : la sortie est toujours plus rapide que l'entree (~65 %), et rien
 * n'est lineaire. Une animation qui n'explique rien est une animation a
 * supprimer.
 */
export const motion = {
  instant: 110,
  fast: 180,
  base: 260,
  slow: 420,
  sweep: 1100,

  /** Sortie = 65 % de l'entree. */
  exit: 170,

  /** Decalage entre deux elements d'une meme liste. */
  stagger: 55,

  /** Ressort standard : pose franche, sans rebond parasite. */
  spring: { damping: 18, stiffness: 190, mass: 0.9 },
  /** Ressort d'appui : plus vif, pour le retour au repos d'un bouton. */
  springPress: { damping: 22, stiffness: 320, mass: 0.7 },
  /** Ressort d'arrivee : leger depassement, pour un element qui se pose. */
  springDrop: { damping: 12, stiffness: 180, mass: 0.8 },
} as const;
