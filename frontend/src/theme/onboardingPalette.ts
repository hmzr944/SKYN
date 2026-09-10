/**
 * Palette etendue, reservee a l'onboarding.
 *
 * Le reste de l'app s'en tient strictement a creme/terre/corail (voir
 * theme/index.ts) : c'est la grammaire clinique, ou chaque couleur porte un
 * sens mesure (le corail signale ce qui demande de l'attention, jamais un
 * decor). L'onboarding est un moment de marque, pas un releve de donnees —
 * il peut se permettre plus de richesse.
 *
 * Mais pas n'importe laquelle : ces trois tons sont extraits directement de
 * la photo du hero (assets/onboarding/portrait.jpg — clustering des couleurs
 * dominantes), pas choisis a l'oeil. Un onboarding qui emprunte ses couleurs
 * a sa propre photo se lit comme un tout ; un onboarding qui les invente a
 * cote se lit comme deux designs recolles.
 */
export const onboardingPalette = {
  /** Ton clair de la photo — la lumiere sur la peau. */
  dore: "#D39565",
  /** Ton profond de la photo — l'ombre, le cote chaud. */
  ambre: "#AC4A31",
  /** Neutre chaud clair, eclairci depuis le mur du fond de la photo. */
  sable: "#E8DECE",
} as const;
