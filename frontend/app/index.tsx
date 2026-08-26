import { AnimatePresence, MotiText, MotiView } from "moti";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { StyleSheet, useWindowDimensions, View } from "react-native";
import { useReducedMotion } from "react-native-reanimated";

import { childDelay, duration, spring, stagger } from "@/src/animation/motion";
import { ease } from "@/src/animation/ease";
import { MarkAssembly } from "@/src/components/brand/MarkAssembly";
import { track } from "@/src/services/analytics";
import { useAuth } from "@/src/contexts/AuthContext";
import { colors, type } from "@/src/theme";

/**
 * L'ouverture, puis l'entree dans l'app.
 *
 * ────────────────────────────────────────────────────────────────────────
 * UN SEUL MOUVEMENT, PAS DEUX ECRANS.
 *
 * Avant, l'app jouait son ouverture, la faisait disparaitre, puis l'ecran
 * suivant rejouait la MEME marque depuis zero. Deux fois la meme construction,
 * separees par un demi-quart de seconde de fond vide. On ne voyait pas une
 * app qui s'ouvre, on voyait un chargement suivi d'un ecran.
 *
 * Ici la marque s'assemble une fois, puis elle PART SE POSER a l'endroit exact
 * ou elle vit dans l'ecran d'arrivee — en haut du bloc d'accueil, ou dans le
 * coin de l'en-tete du tableau de bord. Le mot, lui, a fini son travail : il
 * se retire par le bas. La navigation se declenche PENDANT le vol, pour que
 * l'ecran d'arrivee se remplisse derriere la marque encore en route.
 *
 * Les points d'arrivee ne sont pas devines : ils ont ete mesures sur les
 * ecrans rendus (voir CIBLES).
 * ────────────────────────────────────────────────────────────────────────
 */

const LETTRES = ["S", "K", "Y", "N"];

/** Taille de la marque pendant l'ouverture. */
const TAILLE = 96;
/** Ecart vertical entre le centre de l'ecran et le centre de la marque. */
const MARQUE_DY = -27;
/** Ecart vertical entre le centre de l'ecran et le centre du mot. */
const MOT_DY = 61;

/** Quand la marque est posee et le mot compose. */
const ASSEMBLE = 900;
/** Quand la marque s'elance. */
const DEPART = ASSEMBLE + 300;
/** Duree du vol vers l'ecran d'arrivee. */
const VOL = 560;
/**
 * Avance de la navigation sur la fin du vol.
 *
 * Le changement de route DETRUIT cet ecran : la marque disparait a cet
 * instant precis, ou qu'elle en soit. Il faut donc qu'elle soit deja arrivee.
 * Avec une decelaration en puissance trois, 90 % du temps vaut 99,9 % du
 * chemin — l'echange se fait sur une marque immobile, sur son jumeau immobile
 * de l'ecran d'arrivee. Rien ne saute, et il n'y a aucun fond vide entre les
 * deux puisque le second ecran se peint dans la meme image.
 */
const AVANCE = 60;

/**
 * Ou la marque se pose, par ecran d'arrivee.
 *
 * Mesure au rendu sur 390x844 : accueil (195, 154) taille 84, tableau de bord
 * (44, 28) taille 24. Le premier est centre donc exprime en fraction ; le
 * second est ancre au coin donc exprime en points fixes.
 */
type Cible = { x: number; y: number; taille: number };
const CIBLES: Record<string, (w: number, h: number) => Cible> = {
  "/auth": (w, h) => ({ x: w / 2, y: h * 0.1825, taille: 84 }),
  "/dashboard": () => ({ x: 44, y: 28, taille: 24 }),
};

export default function Index() {
  const router = useRouter();
  const { loading, user, profile } = useAuth();
  const { width, height } = useWindowDimensions();
  const reduced = useReducedMotion();

  /** Passe a faux quand la marque doit partir. */
  const [present, setPresent] = useState(true);

  /** Ou l'on va. Connu des que la session est lue, donc avant le depart. */
  const route = useMemo(() => {
    if (loading) return null;
    if (!user) return "/auth";
    if (!profile?.onboarded) return "/profile-setup";
    return "/dashboard";
  }, [loading, user, profile]);

  useEffect(() => {
    track("app_opened");
  }, []);

  useEffect(() => {
    if (!route) return;
    let annule = false;

    const t1 = setTimeout(() => !annule && setPresent(false), reduced ? 0 : DEPART);
    const t2 = setTimeout(
      () => !annule && router.replace(route as never),
      reduced ? 60 : DEPART + VOL - AVANCE,
    );

    return () => {
      annule = true;
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [route, router, reduced]);

  // Le vol, en points d'ecran. Le deplacement est porte par une vue, l'echelle
  // par une autre : sinon les deux se multiplient et la marque n'atterrit pas
  // ou on l'envoie.
  const cible = route ? CIBLES[route] : undefined;
  const vise = cible?.(width, height);
  const vol = vise
    ? {
        x: vise.x - width / 2,
        y: vise.y - (height / 2 + MARQUE_DY),
        k: vise.taille / TAILLE,
        // Elle se pose : elle reste visible jusqu'au bout, et c'est son jumeau
        // immobile de l'ecran d'arrivee qui prend le relais.
        opacite: 1,
      }
    : // Sans cible — la creation de profil ne porte pas la marque — il n'y a
      // rien a rejoindre : elle s'efface en montant.
      { x: 0, y: -46, k: 0.9, opacite: 0 };

  // Une deceleration, pas une vitesse constante : un objet qui se pose ralentit
  // en approchant. C'est aussi ce qui rend l'echange invisible, puisque le
  // chemin est parcouru bien avant que le temps ne le soit.
  const sortie = reduced
    ? ({ type: "timing", duration: 0 } as const)
    : ({ type: "timing", duration: VOL, easing: ease.out } as const);

  return (
    <View style={styles.container} testID="splash-screen">
      <AnimatePresence>
        {present ? (
          <MotiView
            key="marque"
            style={[styles.couche, { paddingBottom: -MARQUE_DY * 2 }]}
            pointerEvents="none"
            // Les valeurs de repos sont ECRITES : sans elles la sortie n'a pas
            // de point de depart et Moti saute directement a la cible.
            from={{ translateX: 0, translateY: 0, opacity: 1 }}
            animate={{ translateX: 0, translateY: 0, opacity: 1 }}
            exit={{ translateX: vol.x, translateY: vol.y, opacity: vol.opacite }}
            exitTransition={sortie}
          >
            <MotiView
              from={{ scale: 1 }}
              animate={{ scale: 1 }}
              exit={{ scale: vol.k }}
              exitTransition={sortie}
            >
              <MarkAssembly size={TAILLE} />
            </MotiView>
          </MotiView>
        ) : null}

        {present ? (
          <MotiView
            key="mot"
            style={[styles.couche, { paddingTop: MOT_DY * 2 }]}
            pointerEvents="none"
            from={{ opacity: 1, translateY: 0 }}
            animate={{ opacity: 1, translateY: 0 }}
            // Le mot a fini son travail : il se retire vers le bas, vite, pour
            // laisser la marque partir seule. Une sortie dure moins qu'une
            // entree, sinon elle traine.
            exit={{ opacity: 0, translateY: 18 }}
            exitTransition={
              reduced ? { type: "timing", duration: 0 } : { type: "timing", duration: duration.base }
            }
          >
            <View style={styles.mot}>
              {LETTRES.map((l, i) => (
                <MotiText
                  key={l}
                  from={{ opacity: 0, translateY: 16 }}
                  animate={{ opacity: 1, translateY: 0 }}
                  transition={
                    reduced
                      ? { type: "timing", duration: 0 }
                      : {
                          ...spring.gentle,
                          // Le mot se COMPOSE : chaque lettre arrive apres la
                          // precedente. D'un bloc, il n'aurait aucune presence.
                          delay: childDelay(i, stagger.letters, ASSEMBLE - 220),
                        }
                  }
                  style={styles.lettre}
                >
                  {l}
                </MotiText>
              ))}
            </View>
          </MotiView>
        ) : null}
      </AnimatePresence>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  // Deux couches superposees et centrees : chacune decale son contenu par une
  // marge, ce qui rend la position de repos calculable au point pres.
  couche: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  // La chasse est portee par l'ecart de la rangee, pas par la lettre : il n'y
  // a donc pas de gouttiere apres le N, et le mot est centre sans compensation.
  mot: { flexDirection: "row", gap: 9 },
  lettre: {
    fontFamily: type.wordmark.fontFamily,
    fontSize: 22,
    color: colors.fg,
  },
});
