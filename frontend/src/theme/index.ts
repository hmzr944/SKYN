export const colors = {
  // Base surfaces — warm neutrals only, never black or cold gray
  bg: "#FFF8F2",
  surface: "#F2E4DA",
  surfaceRaised: "#FFFFFF",
  surfaceSunken: "#F2E4DA",

  // Text — warm dark brown, never pure black
  fg: "#2D1F1A",
  fgMuted: "rgba(45, 31, 26, 0.6)",
  fgDim: "rgba(45, 31, 26, 0.4)",
  fgFaint: "rgba(45, 31, 26, 0.08)",

  // Borders
  borderSubtle: "rgba(45, 31, 26, 0.08)",
  borderMid: "rgba(45, 31, 26, 0.15)",
  borderActive: "#2D1F1A",

  // Primary — Coral Pop, used for buttons, accents, strong CTAs
  accent: "#FF4D6D",
  accentDark: "#E23A59",
  accentSoft: "rgba(255, 77, 109, 0.2)",
  accentSofter: "rgba(255, 77, 109, 0.08)",
  onAccent: "#FFF8F2",

  // Secondary — Acid Lime, highlights / tags / active indicators
  lime: "#C8F04A",
  limeSoft: "rgba(200, 240, 74, 0.3)",
  limeSofter: "rgba(200, 240, 74, 0.15)",
  onLime: "#2D1F1A",

  overlay: "rgba(45, 31, 26, 0.45)",
  white: "#FFF8F2",
};

export const fonts = {
  // Logo — Velvetyne fallback: Clash Display SemiBold with very large tracking
  logo: "ClashDisplay_600SemiBold",
  // Titles & UI — Clash Display, never light/thin
  heading: "ClashDisplay_600SemiBold",
  headingMedium: "ClashDisplay_500Medium",
  // Body & labels — General Sans
  body: "GeneralSans_400Regular",
  bodyMedium: "GeneralSans_500Medium",
};

export const spacing = {
  xs: 4,
  s: 8,
  m: 16,
  l: 24,
  xl: 32,
  xxl: 48,
  xxxl: 64,
};

export const radius = {
  pill: 999,
  lg: 24,
  md: 16,
  sm: 10,
};

export const shadow = {
  card: {
    shadowColor: "#2D1F1A",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.06,
    shadowRadius: 16,
    elevation: 3,
  },
  raised: {
    shadowColor: "#2D1F1A",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.1,
    shadowRadius: 24,
    elevation: 6,
  },
  button: {
    shadowColor: "#FF4D6D",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.3,
    shadowRadius: 16,
    elevation: 5,
  },
} as const;

export const motion = {
  fast: 150,
  base: 250,
  slow: 400,
};
