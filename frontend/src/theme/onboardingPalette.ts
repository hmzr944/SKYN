/**
 * Palette etendue, reservee a l'onboarding.
 *
 * Le reste de l'app s'en tient strictement a creme/terre/corail (voir
 * theme/index.ts) : c'est la grammaire clinique, ou chaque couleur porte un
 * sens mesure (le corail signale ce qui demande de l'attention, jamais un
 * decor). L'onboarding est un moment de marque, pas un releve de donnees —
 * il peut se permettre plus de richesse.
 *
 * Retour du premier passage : pas de brun, pas de teinte sombre — la grille
 * bento reste sur des tons CLAIRS, derives des photos (jamais choisis a
 * l'oeil), avec le corail de la marque comme seul accent vif.
 */
export const onboardingPalette = {
  /** Ton clair, chaud — la lumiere sur la peau de la photo hero. */
  dore: "#E8B98C",
  /** Neutre chaud tres clair, eclairci depuis le fond des photos. */
  sable: "#F4EDE1",
  /** Rose poudre, tire du fond de la photo "main" — la tuile de couleur qui
   * n'est pas une photo, pour que la grille ne soit pas que des rectangles
   * d'images. */
  blush: "#FBE2DE",
} as const;
