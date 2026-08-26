import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Platform,
  useWindowDimensions,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import Animated, {
  type SharedValue,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { useRouter } from "expo-router";

import { ease } from "@/src/animation/ease";
import { childDelay, spring, stagger } from "@/src/animation/motion";
import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { storage } from "@/src/utils/storage";
import { useAuth } from "@/src/contexts/AuthContext";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { GoogleLogo } from "@/src/components/icons/GoogleLogo";
import { useProviderAuth } from "@/src/hooks/useProviderAuth";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { Figure, MatiereEntiere } from "@/src/components/onboarding/Figure";
import { Progress } from "@/src/components/onboarding/Progress";

/**
 * L'onboarding, en composition editoriale.
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QUI CHANGE, ET POURQUOI.
 *
 * L'ancienne version centrait tout : surtitre centre, illustration centree,
 * titre centre, texte centre. Cinq ecrans batis sur le meme axe, avec pour
 * seule variation le dessin du milieu. C'est une mise en page de diaporama,
 * pas de magazine — l'oeil n'a nulle part ou entrer.
 *
 * Ici le texte est FERRE A GAUCHE et le titre occupe la place d'un titre de
 * couverture : trois ou quatre lignes, chasse serree, interlignage court. La
 * figure ronde deborde a droite, traversee d'un filet en orbite. La
 * progression remonte en haut, en segments, la ou on la lit avant de lire le
 * reste.
 *
 * Une page sur cinq rompt la regle : fond terre, matiere pleine page, titre en
 * creme empile mot par mot. Une seule — c'est ce qui en fait un evenement. Si
 * les cinq le faisaient, ce ne serait plus qu'un autre gabarit repete.
 * ────────────────────────────────────────────────────────────────────────
 */

const PAGE_COUNT = 5;
const CONTENT_MAX_W = 480;
/** Duree du glissement d'une page a l'autre. */
const GLISSE = 380;

/**
 * Une photo dans le disque de la premiere page.
 *
 * Depose un fichier dans `assets/onboarding/` et remplace `null` par son
 * `require(...)`. Sans photo, le disque contient la matiere dessinee : l'app
 * est complete dans les deux cas, jamais en attente d'un fichier manquant.
 */
const PORTRAIT = null; // require("@/assets/onboarding/portrait.jpg")

type Slide = {
  kicker: string;
  title: string;
  helper: string;
  /** Page pleine : fond terre, matiere entiere, titre empile en creme. */
  pleine?: boolean;
  /** Le titre s'empile mot par mot, chaque ligne ponctuee. */
  lignes?: readonly string[];
  variante?: number;
  photo?: boolean;
};

const SLIDES: readonly Slide[] = [
  {
    kicker: "01 · LE CONSTAT",
    title: "Votre peau,\ndécryptée.",
    helper:
      "SKYN analyse votre peau en quelques secondes et vous révèle ce qu'elle a vraiment à dire.",
    photo: true,
    variante: 0,
  },
  {
    kicker: "02 · SUR MESURE",
    title: "Un diagnostic\nqui vous\nressemble.",
    helper:
      "Calibré sur votre âge, votre environnement et vos priorités pour des recommandations vraiment personnalisées.",
    variante: 1,
  },
  {
    kicker: "03 · LA TECHNOLOGIE",
    pleine: true,
    lignes: ["Cartographiée.", "Zone", "par zone."],
    title: "Une technologie de pointe",
    helper:
      "Notre moteur cartographie votre peau zone par zone et détecte les micro-patterns invisibles à l'œil nu.",
  },
  {
    kicker: "04 · CONFIDENTIEL",
    title: "Vos données\nvous\nappartiennent.",
    helper:
      "Vos photos sont analysées puis immédiatement supprimées. Rien n'est partagé, rien n'est conservé.",
    variante: 2,
  },
  {
    kicker: "05 · À VOUS DE JOUER",
    // L'onboarding passe AVANT la question du genre : impossible de s'accorder
    // ici. La tournure evite donc l'accord plutot que de choisir au hasard.
    title: "On découvre\nvotre peau ?",
    helper: "Créez votre dossier cutané chiffré pour commencer votre premier bilan.",
    variante: 3,
  },
] as const;

/**
 * Une couche de la page, decalee a sa propre vitesse.
 *
 * `rate` dit a quelle profondeur elle se trouve : positif, elle suit le
 * defilement et parait loin ; negatif, elle le devance et parait proche.
 */
function Parallax({
  scrollX,
  index,
  width,
  rate,
  style,
  children,
}: {
  scrollX: SharedValue<number>;
  index: number;
  width: number;
  rate: number;
  style?: StyleProp<ViewStyle>;
  children: React.ReactNode;
}) {
  const aStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: (scrollX.value - index * width) * rate }],
  }));
  return (
    <Animated.View style={[style, aStyle]} pointerEvents="box-none">
      {children}
    </Animated.View>
  );
}

/**
 * Une ligne de titre qui monte a sa place.
 *
 * Le titre ne s'affiche pas, il se compose. Chaque ligne arrive apres la
 * precedente, et le regard suit la construction au lieu de recevoir un pave
 * deja fait. Le decalage reste court : au dela, on attend devant un ecran qui
 * se remplit encore.
 */
function Ligne({
  children,
  index,
  actif,
  style,
}: {
  children: React.ReactNode;
  index: number;
  actif: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!actif) {
      t.value = 0;
      return;
    }
    if (reduced) {
      t.value = 1;
      return;
    }
    t.value = withDelay(childDelay(index, stagger.blocks, 90), withSpring(1, spring.gentle));
  }, [actif, index, reduced, t]);

  const aStyle = useAnimatedStyle(() => ({
    opacity: t.value,
    transform: [{ translateY: (1 - t.value) * 22 }],
  }));

  return <Animated.View style={[style, aStyle]}>{children}</Animated.View>;
}

export default function OnboardingScreen() {
  const { width: SCREEN_W, height: SCREEN_H } = useWindowDimensions();
  const [page, setPage] = useState(0);
  const reduced = useReducedMotion();
  const { busy, error, handleGoogle } = useProviderAuth();
  const { continueAsGuest } = useAuth();
  const router = useRouter();

  const handleGuest = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    finishOnboarding();
    await continueAsGuest();
    router.replace("/profile-setup");
  };

  const isNarrow = SCREEN_W < 380;
  const isShort = SCREEN_H < 700;
  const horizontalPadding = isNarrow ? spacing.l : spacing.xl;

  // Le titre est le seul element qui a le droit d'etre grand. Il se cale sur la
  // largeur, pas sur un palier : entre 320 et 430 px il y a un facteur 1,34, et
  // deux tailles fixes laissent forcement l'une des deux mal posee.
  const titleSize = Math.round(Math.min(Math.max(SCREEN_W * 0.098, 30), 42));
  const titleLead = Math.round(titleSize * 1.08);
  const figureSize = isShort ? 156 : isNarrow ? 172 : 196;

  /**
   * Position du pager, en points, suivie image par image.
   *
   * ────────────────────────────────────────────────────────────────────
   * POURQUOI CE N'EST PAS UN DEFILEMENT.
   *
   * Les pages vivaient dans un ScrollView horizontal a `scrollEnabled={false}`
   * qu'on deplacait par `scrollTo()`. Sur Chrome ca marchait ; sur Safari et
   * dans les webviews d'iOS, non — `overflow: hidden` y interdit le defilement
   * programme, et `scroll-snap` ramene au point d'ou l'on vient. L'echec etait
   * muet, la pagination avancait sur un contenu fige, et l'onboarding etant la
   * porte d'entree, on n'entrait jamais dans l'app.
   *
   * Une translation ne depend d'aucun de ces deux mecanismes. Elle sert aussi
   * de source aux couches en parallaxe.
   * ────────────────────────────────────────────────────────────────────
   */
  const scrollX = useSharedValue(0);

  const railStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: -scrollX.value }],
  }));

  const goToPage = (p: number) => {
    if (p < 0 || p > PAGE_COUNT - 1) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    scrollX.value = withTiming(p * SCREEN_W, {
      duration: reduced ? 0 : GLISSE,
      easing: ease.out,
    });
    setPage(p);
  };

  // La largeur change avec la fenetre : sans ce recalage, une rotation ou un
  // redimensionnement laisserait le rail entre deux pages.
  useEffect(() => {
    scrollX.value = page * SCREEN_W;
  }, [SCREEN_W, page, scrollX]);

  const finishOnboarding = () => storage.setItem("skyn_onboarding_seen", "1");

  const isLast = page === PAGE_COUNT - 1;
  const sombre = SLIDES[page].pleine === true;

  return (
    <View style={styles.container}>
      {/* La matiere pleine page vit SOUS les pages, pas dedans : elle doit
          pouvoir deborder derriere l'en-tete et le pied, la ou une page
          s'arrete. Elle s'efface quand on quitte l'ecran qui la porte. */}
      <FondPlein actif={sombre} />

      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        {/* En-tete : la progression d'abord, la marque ensuite. C'est ce qu'on
            regarde en premier quand on se demande ou l'on en est. */}
        <View style={[styles.header, { paddingHorizontal: horizontalPadding }]}>
          <Progress count={PAGE_COUNT} page={page} onDark={sombre} />
          {!isLast ? (
            <TouchableOpacity
              testID="onboarding-skip-btn"
              onPress={() => {
                finishOnboarding();
                goToPage(PAGE_COUNT - 1);
              }}
              hitSlop={12}
              style={styles.skipBtn}
              accessibilityRole="button"
              accessibilityLabel="Passer l'introduction"
            >
              <Text style={[styles.skip, sombre && styles.onDarkMuted]}>Passer</Text>
            </TouchableOpacity>
          ) : (
            <View style={styles.skipBtn} />
          )}
        </View>

        {/* Pages */}
        <View style={styles.viewport}>
          <Animated.View
            style={[styles.rail, { width: SCREEN_W * PAGE_COUNT }, railStyle]}
          >
            {SLIDES.map((slide, i) => {
              const active = i === page;
              return (
                <ScrollView
                  key={i}
                  style={{ width: SCREEN_W }}
                  contentContainerStyle={[styles.page, slide.pleine && styles.pageBasse]}
                  showsVerticalScrollIndicator={false}
                  // Les quatre autres pages restent montees, hors champ. Sans
                  // ces lignes, leurs boutons restent atteignables au clavier
                  // et annonces par le lecteur d'ecran : on peut atterrir sur
                  // un « Continuer avec Google » invisible depuis la page 1.
                  // Il en faut trois, chacune ne couvrant qu'une plateforme.
                  pointerEvents={active ? "auto" : "none"}
                  accessibilityElementsHidden={!active}
                  importantForAccessibility={active ? "auto" : "no-hide-descendants"}
                  aria-hidden={!active}
                >
                  <View
                    style={[
                      styles.pageContent,
                      {
                        maxWidth: CONTENT_MAX_W,
                        paddingHorizontal: horizontalPadding,
                        paddingBottom:
                          i === PAGE_COUNT - 1 ? spacing.xxl : isShort ? spacing.m : spacing.xl,
                      },
                    ]}
                  >
                    {slide.pleine ? (
                      /* ─── La page pleine ─── */
                      <View style={styles.pleineBloc}>
                        <Ligne index={0} actif={active}>
                          <Text style={[styles.kicker, styles.onDarkKicker]}>
                            {slide.kicker}
                          </Text>
                        </Ligne>
                        <View style={styles.pleineTitre}>
                          {slide.lignes?.map((mot, k) => (
                            <Ligne key={mot} index={k + 1} actif={active}>
                              <Text
                                style={[
                                  styles.title,
                                  styles.onDarkTitle,
                                  { fontSize: titleSize, lineHeight: titleLead },
                                ]}
                              >
                                {mot}
                              </Text>
                            </Ligne>
                          ))}
                        </View>
                        <Ligne index={(slide.lignes?.length ?? 0) + 1} actif={active}>
                          <Text style={[styles.helper, styles.onDarkHelper]}>
                            {slide.helper}
                          </Text>
                        </Ligne>
                      </View>
                    ) : (
                      /* ─── Les pages editoriales ─── */
                      <>
                        {/* La figure deborde a droite, et se decale plus vite
                            que le texte : c'est ce decalage qui donne la
                            profondeur au moment du changement de page. */}
                        <Parallax
                          scrollX={scrollX}
                          index={i}
                          width={SCREEN_W}
                          rate={-0.18}
                          // Un debord franc mais mesure : la boite fait deja
                          // 1,26 fois le disque pour loger l'orbite, et un
                          // tiers du disque en plus la poussait de 67 px hors
                          // de l'ecran — l'ellipse et la scintille etaient
                          // tranchees net par le bord droit.
                          style={[styles.figureLayer, { marginRight: -spacing.m }]}
                        >
                          <Figure
                            size={figureSize}
                            source={i === 0 ? PORTRAIT : null}
                            variante={slide.variante ?? 0}
                            delay={90}
                          />
                        </Parallax>

                        <Ligne index={0} actif={active} style={styles.bloc}>
                          <Text style={styles.kicker}>{slide.kicker}</Text>
                        </Ligne>

                        <Ligne index={1} actif={active} style={styles.bloc}>
                          <Text
                            style={[
                              styles.title,
                              { fontSize: titleSize, lineHeight: titleLead },
                            ]}
                          >
                            {slide.title}
                          </Text>
                        </Ligne>

                        <Ligne index={2} actif={active} style={styles.bloc}>
                          <View style={styles.filet} />
                          <Text style={styles.helper}>{slide.helper}</Text>
                        </Ligne>

                        {i === PAGE_COUNT - 1 ? (
                          <Ligne index={3} actif={active} style={styles.bloc}>
                            <View style={styles.authBlock}>
                              {error ? (
                                <View style={styles.errorBadge}>
                                  <Text style={styles.error} testID="onboarding-auth-error">
                                    {error}
                                  </Text>
                                </View>
                              ) : null}

                              <AnimatedPressable
                                testID="onboarding-google-button"
                                style={[styles.googleBtn, busy !== null && styles.btnDisabled]}
                                onPress={() => {
                                  finishOnboarding();
                                  handleGoogle();
                                }}
                                disabled={busy !== null}
                              >
                                <View style={styles.googleBtnInner}>
                                  {busy === "google" ? (
                                    <ActivityIndicator color={colors.fg} size="small" />
                                  ) : (
                                    <>
                                      <GoogleLogo size={20} />
                                      <Text style={styles.googleBtnText}>
                                        Continuer avec Google
                                      </Text>
                                    </>
                                  )}
                                </View>
                              </AnimatedPressable>

                              <TouchableOpacity
                                testID="onboarding-guest-button"
                                onPress={handleGuest}
                                style={styles.guestBtn}
                                hitSlop={8}
                                accessibilityRole="button"
                              >
                                <Text style={styles.guestText}>Tester sans compte →</Text>
                              </TouchableOpacity>

                              <Text style={styles.gdpr} testID="onboarding-gdpr">
                                En continuant, vous créez votre dossier cutané chiffré. Vos
                                photos sont analysées puis immédiatement supprimées.
                              </Text>
                            </View>
                          </Ligne>
                        ) : null}
                      </>
                    )}
                  </View>
                </ScrollView>
              );
            })}
          </Animated.View>
        </View>

        {/* Pied : deux liens, pas un bouton plein.
            La pastille corail etait l'element le moins editorial de l'ecran, et
            la seule chose qui criait sur une page qui, par ailleurs, chuchote.
            Les deux liens gardent leurs 44 px de hauteur tactile. */}
        <View
          style={[
            styles.footer,
            {
              paddingHorizontal: horizontalPadding,
              paddingBottom: Platform.OS === "ios" ? spacing.s : spacing.m,
            },
          ]}
        >
          <View style={styles.footerSlot}>
            {page > 0 ? (
              <TouchableOpacity
                testID="onboarding-back-btn"
                onPress={() => goToPage(page - 1)}
                style={styles.navBtn}
                activeOpacity={0.6}
                hitSlop={10}
                accessibilityRole="button"
                accessibilityLabel="Étape précédente"
              >
                <Text style={[styles.navText, sombre && styles.onDarkMuted]} numberOfLines={1}>
                  ← Retour
                </Text>
              </TouchableOpacity>
            ) : (
              <SkynLockup size={20} still onDark={sombre} />
            )}
          </View>

          <View style={[styles.footerSlot, styles.footerSlotEnd]}>
            {!isLast ? (
              <TouchableOpacity
                testID="onboarding-next-btn"
                onPress={() => goToPage(page + 1)}
                style={styles.navBtn}
                activeOpacity={0.6}
                hitSlop={10}
                accessibilityRole="button"
                accessibilityLabel="Étape suivante"
              >
                <Text style={[styles.navNext, sombre && styles.onDarkNext]} numberOfLines={1}>
                  Suivant →
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

/** Le fond terre de la page pleine, qui se leve et se retire. */
function FondPlein({ actif }: { actif: boolean }) {
  const t = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    t.value = withTiming(actif ? 1 : 0, {
      duration: reduced ? 0 : GLISSE,
      easing: ease.out,
    });
  }, [actif, reduced, t]);

  const aStyle = useAnimatedStyle(() => ({ opacity: t.value }));

  return (
    <Animated.View style={[StyleSheet.absoluteFill, aStyle]} pointerEvents="none">
      <MatiereEntiere />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, overflow: "hidden" },
  safe: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.m,
    paddingTop: spacing.m,
    paddingBottom: spacing.s,
  },
  skipBtn: { minHeight: 44, minWidth: 56, justifyContent: "center", alignItems: "flex-end" },
  skip: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.fgDim,
  },
  // La fenetre montre une page a la fois ; le rail porte les cinq et coulisse
  // derriere elle.
  viewport: { flex: 1, overflow: "hidden" },
  rail: { flex: 1, flexDirection: "row" },
  page: { flexGrow: 1, justifyContent: "center" },
  // La page pleine pose son titre en bas, la ou le voile est le plus
  // opaque et ou la reference place le sien.
  pageBasse: { justifyContent: "flex-end" },
  pageContent: {
    width: "100%",
    alignSelf: "center",
  },
  // La figure sort du cadre a droite. Un rond entier centre est un logo ; un
  // rond qui deborde est une image dans une page.
  figureLayer: { alignSelf: "flex-end", marginBottom: spacing.l },
  bloc: { width: "100%" },
  kicker: {
    fontFamily: fonts.bodyMedium,
    fontSize: 11,
    letterSpacing: 3,
    color: colors.accent,
    marginBottom: spacing.m,
  },
  title: {
    fontFamily: fonts.display,
    color: colors.fg,
    letterSpacing: -0.8,
    textAlign: "left",
  },
  // Un filet court avant le texte courant : il separe le titre du corps sans
  // ajouter d'espace vide, et il donne au bloc un point de depart visible.
  filet: {
    width: 40,
    height: 2,
    borderRadius: 1,
    backgroundColor: colors.accent,
    marginTop: spacing.l,
    marginBottom: spacing.m,
  },
  helper: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 15,
    lineHeight: 23,
    textAlign: "left",
    maxWidth: 330,
  },

  // ————— page pleine —————
  pleineBloc: { width: "100%" },
  pleineTitre: { marginBottom: spacing.l },
  onDarkTitle: { color: colors.onInverse },
  onDarkKicker: { color: colors.accent },
  onDarkHelper: { color: colors.onInverseMuted },
  onDarkMuted: { color: colors.onInverseMuted },
  onDarkNext: { color: colors.onInverse },

  // ————— dernier ecran —————
  authBlock: { marginTop: spacing.xl, width: "100%", gap: spacing.m },
  errorBadge: {
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.sm,
    paddingVertical: spacing.s,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.surface,
  },
  error: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 0.5,
    textAlign: "center",
  },
  btnDisabled: { opacity: 0.6 },
  googleBtn: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: 16,
    alignItems: "center",
    borderRadius: radius.pill,
    ...shadow.card,
  },
  googleBtnInner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.s,
    minHeight: 22,
  },
  googleBtnText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 14,
    letterSpacing: 0.3,
  },
  guestBtn: { alignSelf: "flex-start", paddingVertical: 12, minHeight: 44, justifyContent: "center" },
  guestText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 13,
    letterSpacing: 0.5,
    textDecorationLine: "underline",
  },
  gdpr: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "left",
  },

  // ————— pied —————
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingTop: spacing.s,
    gap: spacing.s,
  },
  footerSlot: { flex: 1, justifyContent: "center" },
  footerSlotEnd: { alignItems: "flex-end" },
  navBtn: { minHeight: 44, justifyContent: "center", paddingVertical: 10 },
  navText: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 14,
    letterSpacing: 0.3,
  },
  navNext: {
    fontFamily: fonts.headingMedium,
    color: colors.fg,
    fontSize: 14,
    letterSpacing: 0.3,
  },
});
