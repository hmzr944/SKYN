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

/**
 * Deux familles, et un partage net entre les deux.
 *
 * Outfit porte l'interface : etiquettes, boutons, corps de texte, tout ce
 * qu'on lit vite et souvent. Fraunces porte ce qu'on REGARDE : le titre d'un
 * ecran, un score, un chiffre. C'est une serif a fort contraste, donc elle ne
 * supporte pas le petit corps ni les capitales espacees — elle n'y va jamais.
 *
 * Une seule famille rendait chaque ecran uniforme : tout se ressemblait, et
 * rien n'attirait l'oeil en premier. Deux familles donnent un point d'entree a
 * chaque ecran, et c'est ce qui fait qu'une page de texte cesse d'etre un mur.
 */
export const fonts = {
  logo: "Outfit_700Bold",
  heading: "Outfit_600SemiBold",
  headingMedium: "Outfit_500Medium",
  body: "Outfit_400Regular",
  bodyMedium: "Outfit_500Medium",
  bodyLight: "Outfit_300Light",
  /** Serif d'affichage. Jamais sous 18 px, jamais en capitales espacees. */
  display: "Fraunces_600SemiBold",
  displayRegular: "Fraunces_400Regular",
} as const;

export const type = {
  display: { fontFamily: fonts.display, fontSize: 34, lineHeight: 38, letterSpacing: -0.6 },
  title: { fontFamily: fonts.display, fontSize: 24, lineHeight: 30, letterSpacing: -0.3 },
  /** Titre de section, plus discret : la serif y serait trop presente. */
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
  number: { fontFamily: fonts.display, fontSize: 46, lineHeight: 50, letterSpacing: -1 },
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
