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
  type ImageSourcePropType,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Defs, Path, RadialGradient, Rect, Stop } from "react-native-svg";
import * as Haptics from "expo-haptics";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  SharedValue,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";

import { ease } from "@/src/animation/ease";
import { childDelay, spring, stagger } from "@/src/animation/motion";
import { colors, fonts, spacing, radius, shadow, motion } from "@/src/theme";
import { onboardingPalette } from "@/src/theme/onboardingPalette";
import { remindersSupported, requestPermission } from "@/src/services/reminders";
import { storage } from "@/src/utils/storage";
import { useAuth } from "@/src/contexts/AuthContext";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { GoogleLogo } from "@/src/components/icons/GoogleLogo";
import { useProviderAuth } from "@/src/hooks/useProviderAuth";
import { SkynLockup } from "@/src/components/brand/SkynLockup";
import { BentoGrid } from "@/src/components/onboarding/BentoGrid";
import { PhotoCard } from "@/src/components/onboarding/PhotoCard";
import { Progress } from "@/src/components/onboarding/Progress";
import { Autorisation, type Etat } from "@/src/components/onboarding/Autorisation";

/**
 * L'onboarding, en composition editoriale — trois pages, pas plus.
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QUI CHANGE, ET POURQUOI.
 *
 * Cinq pages, c'est un onboarding qu'on subit : une promesse dite quatre
 * fois sous des angles a peine differents avant d'arriver au vif du sujet.
 * Le parcours classique d'une appli mobile tient en trois temps — ce qu'elle
 * fait, ce qu'elle demande et pourquoi, puis on commence — et c'est celui-la
 * qui reste ici.
 *
 * Le texte est FERRE A GAUCHE et le titre occupe la place d'un titre de
 * couverture : trois ou quatre lignes, chasse serree, interlignage court.
 * Chaque page porte SA propre photo (voir PhotoCard.tsx et BentoGrid.tsx
 * pour la premiere) — jamais un rond, jamais une matiere abstraite reprise
 * d'une page a l'autre.
 * ────────────────────────────────────────────────────────────────────────
 */

const CONTENT_MAX_W = 480;
/** Duree du glissement d'une page a l'autre. */
const GLISSE = 380;

/**
 * Les trois photos de la grille bento du premier ecran (voir BentoGrid.tsx).
 * Deposees dans `assets/onboarding/` — voir LISEZ-MOI.md pour le format et
 * les droits.
 */
const HERO_PHOTO = require("@/assets/onboarding/hero.jpg");
const JOY_PHOTO = require("@/assets/onboarding/joy.jpg");
const HAND_PHOTO = require("@/assets/onboarding/hand.jpg");
/** Une photo dediee par page suivante — voir LISEZ-MOI.md. */
const PRIVACY_PHOTO = require("@/assets/onboarding/privacy.jpg");
const START_PHOTO = require("@/assets/onboarding/start.jpg");

type Slide = {
  kicker: string;
  title: string;
  helper: string;
  variante?: number;
  /** La photo dediee de cette page — chaque page delivre son message avec
   * sa propre image, jamais une matiere abstraite reprise partout. */
  photo: ImageSourcePropType;
  /** Les autorisations demandees sur cette page — jamais plus d'une page
   * dediee a "demander la permission de X", trop pour trois ecrans. */
  demandes?: readonly ("camera" | "rappels")[];
};

/**
 * ────────────────────────────────────────────────────────────────────────
 * TROIS PAGES : CE QUE L'APP FAIT, CE QU'ELLE DEMANDE, ON COMMENCE.
 *
 * Il y avait cinq pages : la promesse, la vie privee seule, la camera seule,
 * les rappels seuls, puis le compte. Quatre temps de discours pour un seul
 * message ("faites-nous confiance") repete sous des angles a peine
 * differents. Le parcours classique d'une appli mobile tient en trois temps,
 * et les deux demandes systeme (camera, rappels) n'ont pas besoin chacune de
 * leur page : la vie privee est l'argument qui les rend acceptables, alors
 * elles vivent ensemble sur la deuxieme page, pas seules sur un ecran vide.
 * ────────────────────────────────────────────────────────────────────────
 */
const SLIDES: readonly Slide[] = [
  {
    kicker: "LA PROMESSE",
    title: "SKYN se souvient\nde votre peau.",
    helper:
      "Un premier scan pose un point de départ. Ensuite, à chaque nouveau scan, SKYN compare et vous montre ce qui a vraiment changé — pas un diagnostic isolé, une mémoire qui se construit.",
    photo: HERO_PHOTO,
    variante: 0,
  },
  {
    kicker: "VOTRE CONFIANCE",
    title: "Vos données\nvous appartiennent.",
    helper:
      "Vos photos partent au moteur le temps du calcul, puis disparaissent. Vos analyses restent sur votre téléphone. Rien n'est revendu, rien n'entraîne quoi que ce soit. Voilà ce qu'il nous faut pour ça :",
    demandes: ["camera", "rappels"],
    photo: PRIVACY_PHOTO,
    variante: 1,
  },
  {
    kicker: "À VOUS DE JOUER",
    // L'onboarding passe AVANT la question du genre : impossible de s'accorder
    // ici. La tournure evite donc l'accord plutot que de choisir au hasard.
    title: "On découvre\nvotre peau ?",
    helper: "Créez votre dossier cutané chiffré pour commencer votre premier bilan.",
    photo: START_PHOTO,
    variante: 0,
  },
] as const;

const PAGE_COUNT = SLIDES.length;

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

/**
 * L'eloignement d'une page pendant le glissement.
 *
 * Le rail translate deja chaque page d'un ecran entier — ca deplace, ca ne
 * donne pas de profondeur. Ici, une page qui s'eloigne du doigt perd un peu
 * de presence (opacite, echelle) : le glissement devient un fondu-enchaine
 * plutot qu'une diapositive qui claque d'un bord a l'autre.
 */
function PageDepth({
  index,
  scrollX,
  screenW,
  reduced,
  style,
  children,
}: {
  index: number;
  scrollX: SharedValue<number>;
  screenW: number;
  reduced: boolean;
  style?: StyleProp<ViewStyle>;
  children: React.ReactNode;
}) {
  const aStyle = useAnimatedStyle(() => {
    if (reduced) return { opacity: 1, transform: [{ scale: 1 }] };
    const p = Math.min(1, Math.abs(scrollX.value / screenW - index));
    return {
      opacity: 1 - p * 0.6,
      transform: [{ scale: 1 - p * 0.08 }],
    };
  });
  return <Animated.View style={[style, aStyle]}>{children}</Animated.View>;
}

/**
 * La photo derive un peu moins vite que le reste de la page pendant le
 * glissement : c'est ce decalage relatif, pas l'opacite, qui se lit comme
 * de la profondeur — le meme principe qu'un fond de parallaxe, applique ici
 * a une seule couche plutot qu'a un decor entier.
 */
function PhotoParallax({
  index,
  scrollX,
  screenW,
  reduced,
  children,
}: {
  index: number;
  scrollX: SharedValue<number>;
  screenW: number;
  reduced: boolean;
  children: React.ReactNode;
}) {
  const aStyle = useAnimatedStyle(() => {
    if (reduced) return { transform: [{ translateX: 0 }] };
    const p = scrollX.value / screenW - index;
    return { transform: [{ translateX: p * -34 }] };
  });
  return <Animated.View style={aStyle}>{children}</Animated.View>;
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

  /* ————— les deux autorisations —————
     La camera passe par le crochet d'expo-camera, qui connait deja l'etat au
     montage : si elle a ete accordee ailleurs, la page l'affiche accordee sans
     rien redemander. Les rappels n'ont pas d'equivalent, d'ou l'etat local. */
  const [permCam, demanderCam] = useCameraPermissions();
  const [etatRappels, setEtatRappels] = useState<Etat>(
    remindersSupported ? "attente" : "impossible",
  );

  const etatCamera: Etat = permCam?.granted
    ? "accorde"
    : permCam && !permCam.granted && permCam.status !== "undetermined"
      ? "refuse"
      : "attente";

  const isNarrow = SCREEN_W < 380;
  const isShort = SCREEN_H < 700;
  const horizontalPadding = isNarrow ? spacing.l : spacing.xl;

  // Le titre est le seul element qui a le droit d'etre grand. Il se cale sur la
  // largeur, pas sur un palier : entre 320 et 430 px il y a un facteur 1,34, et
  // deux tailles fixes laissent forcement l'une des deux mal posee.
  const titleSize = Math.round(Math.min(Math.max(SCREEN_W * 0.098, 30), 42));
  const titleLead = Math.round(titleSize * 1.08);
  const photoHeight = isShort ? 190 : isNarrow ? 210 : 240;

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

  const posePage = (p: number) =>
    reduced
      ? withTiming(p * SCREEN_W, { duration: 0 })
      : withSpring(p * SCREEN_W, motion.spring);

  const goToPage = (p: number) => {
    if (p < 0 || p > PAGE_COUNT - 1) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    scrollX.value = posePage(p);
    setPage(p);
  };

  /**
   * ────────────────────────────────────────────────────────────────────
   * LE GLISSEMENT AU DOIGT.
   *
   * Avant, la seule facon de tourner une page etait la fleche : un pager
   * qu'on ne peut PAS glisser au doigt se lit comme une diapositive, pas
   * comme un carrousel. `scrollX` suit maintenant le geste image par image
   * (pas de temps mort entre le doigt et le rail), avec une resistance
   * elastique aux deux bouts — ceder un peu plutot que buter net dit "il
   * n'y a rien de plus" sans avoir besoin d'un mot pour le dire.
   *
   * `activeOffsetX`/`failOffsetY` laissent le defilement vertical des pages
   * courtes gagner sur un glissement essentiellement vertical, et le
   * carrousel gagner sur un glissement essentiellement horizontal — sans ce
   * partage, l'un des deux devient impossible a declencher.
   */
  const dragOrigin = useSharedValue(0);

  const settle = (p: number) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setPage(p);
  };

  const panGesture = Gesture.Pan()
    .activeOffsetX([-14, 14])
    .failOffsetY([-10, 10])
    .onStart(() => {
      dragOrigin.value = scrollX.value;
    })
    .onUpdate((e) => {
      const min = 0;
      const max = (PAGE_COUNT - 1) * SCREEN_W;
      let next = dragOrigin.value - e.translationX;
      if (next < min) next = min + (next - min) * 0.32;
      else if (next > max) next = max + (next - max) * 0.32;
      scrollX.value = next;
    })
    .onEnd((e) => {
      const current = scrollX.value / SCREEN_W;
      // Une pichenette franche fait toujours avancer d'une page entiere,
      // meme a peine deplacee — c'est le geste qui compte, pas la distance.
      const flick = Math.abs(e.velocityX) > 480;
      let target = flick
        ? e.velocityX < 0
          ? Math.ceil(current)
          : Math.floor(current)
        : Math.round(current);
      target = Math.min(Math.max(target, 0), PAGE_COUNT - 1);
      scrollX.value = posePage(target);
      runOnJS(settle)(target);
    });

  // La largeur change avec la fenetre : sans ce recalage, une rotation ou un
  // redimensionnement laisserait le rail entre deux pages.
  useEffect(() => {
    scrollX.value = page * SCREEN_W;
  }, [SCREEN_W, page, scrollX]);

  const finishOnboarding = () => storage.setItem("skyn_onboarding_seen", "1");

  const isLast = page === PAGE_COUNT - 1;
  // Plus aucune page sombre : chaque page porte sa propre photo sur fond
  // clair, y compris l'ancienne page "pleine" (confidentialite). `sombre`
  // reste ici pour le contraste de l'en-tete/pied, au cas ou une page en
  // aurait de nouveau besoin — elle vaut simplement toujours faux aujourd'hui.
  const sombre = false;

  return (
    <View style={styles.container}>
      <FondChaud actif={page === 0} />

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
          <GestureDetector gesture={panGesture}>
          <Animated.View
            style={[styles.rail, { width: SCREEN_W * PAGE_COUNT }, railStyle]}
          >
            {SLIDES.map((slide, i) => {
              const active = i === page;
              return (
                <ScrollView
                  key={i}
                  style={{ width: SCREEN_W }}
                  contentContainerStyle={styles.page}
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
                  <PageDepth
                    index={i}
                    scrollX={scrollX}
                    screenW={SCREEN_W}
                    reduced={reduced}
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
                    {i === 0 ? (
                      // La grille bento remplace le disque unique sur la page
                      // hero : photos reelles, tuiles rectangulaires a coins
                      // arrondis, pleine largeur — voir BentoGrid.tsx. Seule
                      // cette page a plusieurs tuiles ; les suivantes portent
                      // chacune UNE photo dediee (voir PhotoCard.tsx).
                      <>
                        <PhotoParallax index={i} scrollX={scrollX} screenW={SCREEN_W} reduced={reduced}>
                          <View style={styles.bentoLayer}>
                            <BentoGrid hero={HERO_PHOTO} joy={JOY_PHOTO} hand={HAND_PHOTO} delay={90} />
                          </View>
                        </PhotoParallax>

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
                      </>
                    ) : (
                      <>
                        <PhotoParallax index={i} scrollX={scrollX} screenW={SCREEN_W} reduced={reduced}>
                          <PhotoCard source={slide.photo} height={photoHeight} delay={90} />
                        </PhotoParallax>

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

                        {slide.demandes?.map((d, k) => (
                          <Ligne key={d} index={3 + k} actif={active} style={styles.bloc}>
                            {d === "camera" ? (
                              <Autorisation
                                testID="onboarding-perm-camera"
                                etat={etatCamera}
                                libelle="Autoriser l'appareil photo"
                                motAccorde="L'appareil photo est autorisé. Vous pourrez lancer un scan tout de suite."
                                motRefuse="Refusé pour l'instant. On vous le redemandera au moment du scan, et vous pouvez revenir dessus dans les réglages du téléphone."
                                motImpossible="L'appareil photo n'est pas accessible ici."
                                onDemander={async () => {
                                  await demanderCam();
                                }}
                              />
                            ) : (
                              <Autorisation
                                testID="onboarding-perm-rappels"
                                etat={etatRappels}
                                libelle="Activer les rappels"
                                motAccorde="Rappels activés. Vous choisirez les horaires dans les réglages."
                                motRefuse="Sans notification, pas de rappel. Vous pourrez les activer plus tard dans les réglages."
                                motImpossible="Les rappels demandent des notifications programmées, que le navigateur ne sait pas faire. Ils s'activeront dans l'application installée."
                                onDemander={async () => {
                                  const ok = await requestPermission();
                                  setEtatRappels(ok ? "accorde" : "refuse");
                                }}
                              />
                            )}
                          </Ligne>
                        ))}

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
                                style={styles.googleBtn}
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
                  </PageDepth>
                </ScrollView>
              );
            })}
          </Animated.View>
          </GestureDetector>
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
              <NavArrow direction="left" onPress={() => goToPage(page - 1)} />
            ) : (
              <SkynLockup size={20} still onDark={sombre} />
            )}
          </View>

          <View style={[styles.footerSlot, styles.footerSlotEnd]}>
            {!isLast ? (
              <NavArrow direction="right" onPress={() => goToPage(page + 1)} />
            ) : null}
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

/**
 * Le fond chaud de la page hero, qui se leve et se retire.
 *
 * Meme mecanisme que FondPlein, pour la page photo : un lavis dore/sable qui
 * irrigue le haut de l'ecran, cote figure, et s'efface vers le creme aux
 * bords. Sans lui la photo restait un rectangle colore pose sur un fond
 * neutre indifferent ; avec lui, la chaleur de la photo se propage a la
 * page entiere — c'est la page qui change, pas seulement un element dessus.
 */
function FondChaud({ actif }: { actif: boolean }) {
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
      <Svg width="100%" height="100%" viewBox="0 0 100 200" preserveAspectRatio="xMidYMid slice">
        <Defs>
          <RadialGradient id="fond-chaud" cx="72%" cy="20%" r="55%">
            <Stop offset="0" stopColor={onboardingPalette.sable} stopOpacity={0.9} />
            <Stop offset="0.55" stopColor={onboardingPalette.dore} stopOpacity={0.14} />
            <Stop offset="1" stopColor={onboardingPalette.dore} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x={0} y={0} width={100} height={200} fill="url(#fond-chaud)" />
      </Svg>
    </Animated.View>
  );
}

/**
 * La fleche de navigation — plus de "Suivant"/"Retour" en toutes lettres.
 *
 * Une fleche seule dit la meme chose plus vite, et laisse la page respirer.
 * Elle nudge doucement vers son sens en continu — une invitation discrete a
 * appuyer, pas juste un bouton statique qui attend — et repond a l'appui par
 * le meme ressort que le reste de l'app (AnimatedPressable).
 */
function NavArrow({
  direction,
  onPress,
}: {
  direction: "left" | "right";
  onPress: () => void;
}) {
  const reduced = useReducedMotion();
  const nudge = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    nudge.value = withRepeat(
      withSequence(
        withDelay(400, withTiming(1, { duration: 700, easing: ease.sineInOut })),
        withTiming(0, { duration: 700, easing: ease.sineInOut }),
      ),
      -1,
      true,
    );
  }, [reduced, nudge]);

  const sign = direction === "right" ? 1 : -1;
  const nudgeStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: sign * nudge.value * 4 }],
  }));

  const d = direction === "right" ? "M9,5 L16,12 L9,19" : "M15,5 L8,12 L15,19";

  return (
    <AnimatedPressable
      testID={direction === "right" ? "onboarding-next-btn" : "onboarding-back-btn"}
      onPress={onPress}
      scaleTo={0.86}
      haptic="light"
      style={styles.navArrow}
      accessibilityLabel={direction === "right" ? "Étape suivante" : "Étape précédente"}
    >
      <Animated.View style={nudgeStyle}>
        <Svg width={22} height={22} viewBox="0 0 24 24">
          <Path
            d={d}
            fill="none"
            stroke={colors.fg}
            strokeWidth={2.4}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </Svg>
      </Animated.View>
    </AnimatedPressable>
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
  bentoLayer: { alignSelf: "stretch", marginBottom: spacing.l },
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
  googleBtn: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: spacing.m,
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
  guestBtn: { alignSelf: "flex-start", paddingVertical: spacing.s, minHeight: 44, justifyContent: "center" },
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
  navArrow: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSunken,
  },
});
