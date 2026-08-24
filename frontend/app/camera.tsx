import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  LayoutChangeEvent,
  Platform,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import Svg, { Defs, G, Mask, Path, Rect } from "react-native-svg";
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { Reveal } from "@/src/components/ui/Reveal";
import { colors, radius, spacing, type } from "@/src/theme";
import { FACE_CLOSED, FACE_LENGTH, FACE_PATH } from "@/src/theme/mark";
import { storage } from "@/src/utils/storage";

const AnimatedPath = Animated.createAnimatedComponent(Path);

/**
 * L'ecran de prise de vue.
 *
 * Pas de theme sombre : le fond reste la creme de l'app, et c'est un voile
 * creme perce a la forme du symbole qui isole le visage. On voit donc son
 * reflet exactement dans le contour de la marque — le meme trace que le logo
 * et que l'ecran d'analyse.
 *
 * La mise en page est en flux, pas en absolu : l'ancienne version empilait
 * tout en position absolue avec un ovale dimensionne en pourcentage de la
 * hauteur d'ecran, si bien que sur un telephone haut l'ovale passait sous le
 * texte. Ici l'aire de visee mesure sa propre place et la forme s'y adapte.
 */
export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const { width: winW } = useWindowDimensions();

  // L'aire de visee mesure sa propre taille : c'est ce qui rend l'ecran
  // correct sur un petit telephone comme sur une tablette.
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const onStageLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setStage((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
  };

  // Le contour respire : une seule ligne dont l'opacite varie, plutot que deux
  // ellipses superposees qui donnaient un double trait.
  const breath = useSharedValue(0);
  useEffect(() => {
    breath.value = withRepeat(
      withTiming(1, { duration: 2200, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
  }, [breath]);
  const contourProps = useAnimatedProps(() => ({
    strokeOpacity: 0.55 + breath.value * 0.45,
  }));

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  const finalize = async (base64: string | null) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    await storage.setItem("skyn_last_capture_b64", base64 || "");
    // On passe par l'ecran d'analyse : c'est lui qui lance le moteur et qui
    // montre ce qui se passe pendant les quelques secondes de calcul.
    router.replace("/analysis");
  };

  const capture = async () => {
    if (!cameraRef.current) {
      finalize(null);
      return;
    }
    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.55,
        skipProcessing: true,
      });
      finalize(photo?.base64 || null);
    } catch {
      finalize(null);
    }
  };

  const pickFromGallery = async () => {
    try {
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        base64: true,
        quality: 0.55,
      });
      if (res.canceled || !res.assets?.[0]) return;
      finalize(res.assets[0].base64 || null);
    } catch {
      finalize(null);
    }
  };

  const canUseCamera = permission?.granted && Platform.OS !== "web";

  // Le visage n'occupe pas tout le carre de 64 : il s'inscrit dans 36,8 x 44,5.
  // Dimensionner la boite plutot que le dessin donnait une forme bien trop
  // petite, avec du vide tout autour.
  const CONTENT_W = 36.8;
  const CONTENT_H = 44.5;
  const CENTER = { x: 32, y: 32.3 };

  const k = Math.min((stage.w * 0.78) / CONTENT_W, (stage.h * 0.74) / CONTENT_H);
  const tx = stage.w / 2 - CENTER.x * k;
  const ty = stage.h / 2 - CENTER.y * k;
  // Le trait est exprime en unites du repere : sans compensation, il epaissit
  // avec la forme. On vise une epaisseur constante a l'ecran.
  const stroke = k > 0 ? 2.4 / k : 0;
  const ready2 = stage.w > 0 && stage.h > 0;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <AnimatedPressable
          testID="camera-close-btn"
          onPress={() => router.back()}
          style={styles.closeBtn}
          scaleTo={0.9}
        >
          <Text style={styles.closeText}>✕</Text>
        </AnimatedPressable>
        <Text style={styles.headerTitle}>Nouveau scan</Text>
        <View style={{ width: 36 }} />
      </View>

      {retake === "no_face" ? (
        <Reveal distance={6} style={styles.noticeWrap}>
          <View style={styles.notice} testID="camera-retake-notice">
            <Text style={styles.noticeText}>
              {"Aucun visage détecté. Cadrez votre visage dans le contour, " +
                "sans lunettes ni cheveux sur le front."}
            </Text>
          </View>
        </Reveal>
      ) : null}

      <View style={styles.stage} onLayout={onStageLayout}>
        {canUseCamera ? (
          <CameraView
            ref={cameraRef}
            style={StyleSheet.absoluteFill}
            facing="front"
            onCameraReady={() => setReady(true)}
          />
        ) : null}

        {ready2 ? (
          <Svg
            width={stage.w}
            height={stage.h}
            style={StyleSheet.absoluteFill}
            pointerEvents="none"
          >
            <Defs>
              <Mask id="skyn-window">
                {/* Blanc = opaque, noir = perce. */}
                <Rect width={stage.w} height={stage.h} fill="white" />
                <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
                  <Path d={FACE_CLOSED} fill="black" />
                </G>
              </Mask>
            </Defs>

            {/* Le voile est creme, pas noir : la fenetre decoupe le fond de
                l'app, elle ne l'assombrit pas. */}
            <Rect
              width={stage.w}
              height={stage.h}
              fill={colors.bg}
              mask="url(#skyn-window)"
            />

            <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
              {/* Sans camera, la fenetre reste creusee dans une teinte tres
                  legere pour qu'on lise quand meme la forme. */}
              {!canUseCamera ? (
                <Path d={FACE_CLOSED} fill={colors.fg} opacity={0.05} />
              ) : null}
              <AnimatedPath
                d={FACE_PATH}
                fill="none"
                stroke={colors.accent}
                strokeWidth={stroke}
                strokeLinecap="round"
                strokeDasharray={FACE_LENGTH}
                animatedProps={contourProps}
              />
            </G>
          </Svg>
        ) : null}

        {!canUseCamera ? (
          <View style={styles.placeholder} pointerEvents="box-none">
            <Text style={styles.placeholderText}>
              {Platform.OS === "web"
                ? "Aperçu caméra indisponible sur le web."
                : "Autorisez la caméra pour lancer un scan."}
            </Text>
            {!permission?.granted && Platform.OS !== "web" ? (
              <AnimatedPressable
                style={styles.permBtn}
                haptic="medium"
                onPress={requestPermission}
              >
                <Text style={styles.permBtnText}>Autoriser</Text>
              </AnimatedPressable>
            ) : null}
          </View>
        ) : null}
      </View>

      <View style={styles.guidance}>
        <Text style={styles.guide}>Cadrez votre visage dans le contour</Text>
        <Text style={styles.conditions}>Lumière du jour · à 30 cm · sans lunettes</Text>
      </View>

      <View style={[styles.controls, winW < 340 && styles.controlsTight]}>
        <AnimatedPressable
          testID="camera-gallery-btn"
          onPress={pickFromGallery}
          style={styles.galleryBtn}
        >
          <Text style={styles.galleryText}>Galerie</Text>
        </AnimatedPressable>

        <AnimatedPressable
          testID="camera-capture-btn"
          onPress={capture}
          style={styles.captureOuter}
          disabled={canUseCamera ? !ready : false}
          haptic="medium"
          scaleTo={0.92}
        >
          <View style={styles.captureInner} />
        </AnimatedPressable>

        {/* Contrepoids de la galerie : garde le declencheur au centre exact. */}
        <View style={styles.controlsSpacer} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.s,
    paddingBottom: spacing.s,
  },
  closeBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSunken,
  },
  closeText: { color: colors.fg, fontSize: 15 },
  headerTitle: { ...type.kicker, color: colors.fgMuted },

  noticeWrap: { paddingHorizontal: spacing.l, paddingBottom: spacing.s },
  notice: {
    borderWidth: 1,
    borderColor: colors.accentLine,
    backgroundColor: colors.accentSofter,
    paddingVertical: 11,
    paddingHorizontal: spacing.m,
    borderRadius: radius.md,
  },
  noticeText: { ...type.bodySmall, color: colors.fg, textAlign: "center" },

  // L'aire de visee prend la place restante — c'est elle qui absorbe les
  // differences de hauteur entre telephones.
  stage: { flex: 1, overflow: "hidden" },
  placeholder: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.m,
  },
  placeholderText: {
    ...type.bodySmall,
    color: colors.fgDim,
    textAlign: "center",
    maxWidth: 240,
  },
  permBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: 26,
    paddingVertical: 11,
    borderRadius: radius.pill,
  },
  permBtnText: { ...type.kicker, color: colors.accent },

  guidance: {
    alignItems: "center",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.m,
    gap: spacing.xs,
  },
  guide: { ...type.subtitle, color: colors.fg, textAlign: "center" },
  conditions: { ...type.bodySmall, color: colors.fgMuted, textAlign: "center" },

  controls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.l,
    paddingTop: spacing.l,
    paddingBottom: spacing.m,
  },
  controlsTight: { paddingHorizontal: spacing.m, paddingTop: spacing.m },
  galleryBtn: {
    width: 84,
    paddingVertical: 11,
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  galleryText: { ...type.kicker, color: colors.fgMuted },
  controlsSpacer: { width: 84 },
  captureOuter: {
    width: 76,
    height: 76,
    borderRadius: 38,
    borderWidth: 2,
    borderColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  captureInner: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: colors.accent,
  },
});
