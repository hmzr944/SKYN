import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutChangeEvent, Platform, StyleSheet, Text, View } from "react-native";
import Svg, { Defs, G, Mask, Path, Rect } from "react-native-svg";
import { useSharedValue, withSpring, withTiming } from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";

import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";
import { ScanRing } from "@/src/components/analysis/ScanRing";
import { Reveal } from "@/src/components/ui/Reveal";
import { track } from "@/src/services/analytics";
import {
  ANGLES,
  angleOf,
  evaluate,
  framingOk,
  guideMessage,
  HOLD_MS,
  readDetection,
  type Angle,
  type GuideState,
} from "@/src/services/faceGuide";
import { colors, motion, radius, spacing, type } from "@/src/theme";
import { FACE_CLOSED } from "@/src/theme/mark";
import { storage } from "@/src/utils/storage";

/** Base64 nu, sans entete : c'est ce que le reste de l'app attend. */
const cleanB64 = (b?: string | null) =>
  b ? (b.startsWith("data:") ? b.split(",")[1] ?? "" : b) : "";

/**
 * Encombrement du visage dans le repere du symbole.
 *
 * Il n'occupe pas tout le carre de 64 : il s'inscrit dans 36,8 x 44,5, centre
 * a peu pres au milieu. Dimensionner la boite plutot que le dessin donnerait
 * une forme trop petite entouree de vide.
 */
const CONTENT_W = 36.8;
const CONTENT_H = 44.5;
const CENTER = { x: 32, y: 32.3 };

/**
 * Le scan, en une seule session continue.
 *
 * On ne prend pas de photos : on tourne lentement la tete et l'app
 * echantillonne toute seule les angles qui lui manquent, comme l'enregistrement
 * de Face ID. Le contour se remplit au fur et a mesure de la couverture ; quand
 * il est complet, l'analyse part.
 *
 * MIROIR — le mecanisme est celui de Snapchat et de l'appareil photo natif :
 * l'APERCU est en miroir, la PHOTO ne l'est pas.
 *
 * On se voit toute la journee dans un miroir : une vue non inversee de son
 * propre visage parait fausse, et c'est desagreable au moment ou l'on se
 * cadre. L'apercu garde donc l'inversion appliquee par expo-camera.
 *
 * La photo, elle, doit etre a l'endroit : c'est elle qui est analysee, et le
 * moteur decoupe le visage en zones gauche/droite. unmirror() corrige donc le
 * canvas que la bibliotheque inverse de son cote (isImageMirror). Ce sont deux
 * chemins distincts, et ils ne doivent PAS etre traites pareil.
 */
export default function CameraScreen() {
  const router = useRouter();
  const { retake } = useLocalSearchParams<{ retake?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  const [guide, setGuide] = useState<GuideState>("loading");
  const [covered, setCovered] = useState<Angle[]>([]);
  const coveredRef = useRef<Angle[]>([]);
  const capturesRef = useRef<string[]>([]);
  const holdSinceRef = useRef<number | null>(null);
  // Amplitude de rotation reellement balayee, pour la couronne : on retient
  // l'ecart entre le yaw le plus a gauche et le plus a droite vus nettement.
  const spanRef = useRef<{ min: number; max: number } | null>(null);

  // Geometrie de la couronne, en pixels d'ecran. Elle vit en valeurs animees :
  // la couronne suit le visage image par image sans repasser par le rendu.
  const ringX = useSharedValue(0);
  const ringY = useSharedValue(0);
  const ringR = useSharedValue(0);
  const ringP = useSharedValue(0);
  // Le repere de l'ecran change avec la mise en page : on le lit dans une ref
  // pour que la boucle de detection ne travaille jamais sur une valeur perimee.
  const stageRef = useRef({ w: 0, h: 0 });
  const busyRef = useRef(false);
  const doneRef = useRef(false);

  const [stage, setStage] = useState({ w: 0, h: 0 });
  const onStageLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    stageRef.current = { w: width, h: height };
    setStage((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
  };

  const canUseCamera = !!permission?.granted;

  useEffect(() => {
    track("scan_started");
  }, []);

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  /* ————— fin de session ————— */
  const finish = useCallback(
    async (captures: string[]) => {
      if (doneRef.current) return;
      doneRef.current = true;
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      await storage.setItem("skyn_last_capture_b64", captures[0] || "");
      await storage.setItem("skyn_last_captures", JSON.stringify(captures));
      router.replace("/analysis");
    },
    [router],
  );

  const unmirror = (b64: string): Promise<string> =>
    new Promise((resolve) => {
      if (Platform.OS !== "web") {
        resolve(b64);
        return;
      }
      const img = new window.Image();
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = img.width;
          c.height = img.height;
          const g = c.getContext("2d");
          if (!g) return resolve(b64);
          g.translate(img.width, 0);
          g.scale(-1, 1);
          g.drawImage(img, 0, 0);
          resolve(c.toDataURL("image/jpeg", 0.85).split(",")[1] ?? b64);
        } catch {
          resolve(b64);
        }
      };
      img.onerror = () => resolve(b64);
      img.src = b64.startsWith("data:") ? b64 : `data:image/jpeg;base64,${b64}`;
    });

  /**
   * Place la couronne sur le visage detecte.
   *
   * La video est affichee en `cover` : elle est agrandie jusqu'a remplir le
   * cadre, puis rognee. Il faut donc refaire ce calcul pour convertir les
   * coordonnees de detection en pixels d'ecran — sinon la couronne derive des
   * que les proportions de la camera different de celles du cadre.
   *
   * Et l'apercu etant en miroir, l'abscisse doit etre retournee : sans ca, la
   * couronne partirait du cote oppose au visage.
   */
  /**
   * Place la couronne juste a l'exterieur de la fenetre de visee.
   *
   * Elle etait auparavant dimensionnee sur le visage DETECTE alors que la
   * fenetre l'est sur l'ECRAN : deux logiques independantes, et les traits
   * finissaient par tomber sur l'image des que le visage etait un peu grand.
   *
   * La couronne appartient au cadre, pas au sujet. Comme a l'enregistrement de
   * Face ID, ou le cercle ne bouge pas : c'est le visage qui vient s'y placer.
   * Ce qui suit le visage, c'est l'allumage des traits — pas leur position.
   */
  const placeRing = useCallback(
    (w: number, h: number, k: number, centerY: number) => {
      if (!w || !h || !k) return;

      // La forme mesure CONTENT_H de haut : son point le plus eloigne du centre
      // est donc a la moitie de cette hauteur. On se pose juste au-dela.
      const outside = (CONTENT_H / 2) * k * 1.06;

      // Les traits allumes s'allongent encore au-dela du rayon : on compte
      // cette marge, sinon la couronne sort du cadre.
      const reach = (r: number) => r + 1.6 * Math.max(6, r * 0.07) + 4;
      const room = Math.min(w / 2, h / 2) - 6;
      let r = outside;
      if (reach(r) > room) r = Math.max(40, (room - 13.6) / 1.112);

      ringX.value = withSpring(w / 2, motion.spring);
      ringY.value = withSpring(centerY, motion.spring);
      ringR.value = withSpring(r, motion.spring);
    },
    [ringX, ringY, ringR],
  );

  /** Echantillonne l'angle courant, sans ceremonie : ni flash ni compte a rebours. */
  const sample = useCallback(
    async (angle: Angle) => {
      if (busyRef.current || doneRef.current) return;
      busyRef.current = true;
      try {
        const photo = await cameraRef.current?.takePictureAsync({
          base64: true,
          quality: 0.55,
          skipProcessing: true,
        });
        const clean = cleanB64(photo?.base64 ?? null);
        if (clean) {
          capturesRef.current.push(await unmirror(clean));
          const next = [...coveredRef.current, angle];
          coveredRef.current = next;
          setCovered(next);
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          if (next.length >= ANGLES.length) await finish(capturesRef.current);
        }
      } catch {
        /* on retentera a l'image suivante */
      } finally {
        busyRef.current = false;
        holdSinceRef.current = null;
      }
    },
    [finish],
  );

  /* ————— guidage live ————— */
  useEffect(() => {
    if (Platform.OS !== "web" || !canUseCamera) {
      setGuide("searching");
      return;
    }
    let stopped = false;
    let raf = 0;
    let last = 0;
    let detector: any = null;

    (async () => {
      try {
        const vision: any = await new Function("u", "return import(u)")(
          "/mediapipe/vision_bundle.mjs",
        );
        const fileset = await vision.FilesetResolver.forVisionTasks("/mediapipe");
        detector = await vision.FaceDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: "/mediapipe/blaze_face_short_range.tflite" },
          runningMode: "VIDEO",
        });
        if (stopped) return;

        const loop = () => {
          if (stopped) return;
          const v = document.querySelector("video");
          const now = performance.now();
          // ~5 images par seconde : au-dela on chauffe le telephone sans rien
          // gagner, l'oeil ne suit pas des corrections plus rapides.
          if (v && v.readyState >= 2 && v.videoWidth > 0 && now - last > 180) {
            last = now;
            try {
              const d = readDetection(
                detector.detectForVideo(v, now),
                v.videoWidth,
                v.videoHeight,
              );
              const state = evaluate(d, coveredRef.current);
              setGuide(state);

              // L'angle doit tenir un court instant avant d'etre echantillonne :
              // une image prise en plein mouvement serait floue.
              if (d) {
                if (framingOk(d)) {
                  const sp = spanRef.current;
                  const next = sp
                    ? { min: Math.min(sp.min, d.yaw), max: Math.max(sp.max, d.yaw) }
                    : { min: d.yaw, max: d.yaw };
                  spanRef.current = next;
                  // Une amplitude d'environ 1,2 couvre confortablement un
                  // profil a l'autre : au-dela on demanderait un effort inutile.
                  ringP.value = withTiming(
                    Math.max(0, Math.min(1, (next.max - next.min) / 1.2)),
                    { duration: 220 },
                  );
                }
              }

              const angle = d && framingOk(d) ? angleOf(d.yaw) : null;
              const wanted = angle && !coveredRef.current.includes(angle) ? angle : null;
              if (wanted) {
                if (holdSinceRef.current === null) holdSinceRef.current = now;
                else if (now - holdSinceRef.current >= HOLD_MS) sample(wanted);
              } else {
                holdSinceRef.current = null;
              }
            } catch {
              /* image suivante */
            }
          }
          raf = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        // Detecteur indisponible : on rend la main au declencheur manuel.
        if (!stopped) setGuide("searching");
      }
    })();

    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      try {
        detector?.close?.();
      } catch {
        /* noop */
      }
    };
  }, [canUseCamera, sample, ringP]);

  /* ————— repli manuel ————— */
  const manualCapture = async () => {
    const photo = await cameraRef.current?.takePictureAsync({
      base64: true,
      quality: 0.55,
      skipProcessing: true,
    });
    const clean = cleanB64(photo?.base64 ?? null);
    await finish(clean ? [await unmirror(clean)] : []);
  };

  const pickFromGallery = async () => {
    try {
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        base64: true,
        quality: 0.55,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const clean = cleanB64(res.assets[0].base64);
      await finish(clean ? [clean] : []);
    } catch {
      await finish(capturesRef.current);
    }
  };

  /* ————— geometrie ————— */
  // La fenetre doit laisser de la place a la couronne, sinon les traits
  // retombent sur l'image. On prend donc la plus petite des deux tailles :
  // celle qui cadre bien le visage, et celle qui laisse la marge necessaire.
  //
  // La marge requise vient de la geometrie de la couronne : rayon a 1,06 fois
  // la demi-hauteur de la forme, plus l'allongement des traits allumes. Le
  // facteur 26,3 est ce cumul rapporte a l'echelle.
  const kCadrage = Math.min((stage.w * 0.78) / CONTENT_W, (stage.h * 0.74) / CONTENT_H);
  const kMarge = (Math.min(stage.w, stage.h) / 2 - 20) / 26.3;
  const k = Math.max(1, Math.min(kCadrage, kMarge));
  const tx = stage.w / 2 - CENTER.x * k;
  const ty = stage.h / 2 - CENTER.y * k;
  const laid = stage.w > 0 && stage.h > 0;

  // La couronne depend de la mise en page, pas de la detection : on la place
  // quand le cadre change, une fois pour toutes.
  useEffect(() => {
    if (laid) placeRing(stage.w, stage.h, k, ty + CENTER.y * k);
  }, [laid, stage.w, stage.h, k, ty, placeRing]);

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
        <Text style={styles.headerTitle}>
          {covered.length} / {ANGLES.length} angles
        </Text>
        <View style={{ width: 36 }} />
      </View>

      {retake === "no_face" ? (
        <Reveal distance={6} style={styles.noticeWrap}>
          <View style={styles.notice} testID="camera-retake-notice">
            <Text style={styles.noticeText}>
              {"Aucun visage détecté sur la dernière prise. Suivez le guidage ci-dessous."}
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

        {laid ? (
          <Svg width={stage.w} height={stage.h} style={StyleSheet.absoluteFill} pointerEvents="none">
            <Defs>
              <Mask id="skyn-window">
                <Rect width={stage.w} height={stage.h} fill="white" />
                <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
                  <Path d={FACE_CLOSED} fill="black" />
                </G>
              </Mask>
            </Defs>

            <Rect width={stage.w} height={stage.h} fill={colors.bg} mask="url(#skyn-window)" />

            <G transform={`translate(${tx}, ${ty}) scale(${k})`}>
              {!canUseCamera ? <Path d={FACE_CLOSED} fill={colors.fg} opacity={0.05} /> : null}
            </G>

            {/* La couronne vit dans le repere de l'ecran, pas dans celui du
                dessin : son epaisseur ne doit pas suivre l'echelle du visage. */}
            <ScanRing cx={ringX} cy={ringY} radius={ringR} progress={ringP} />
          </Svg>
        ) : null}

        {!canUseCamera ? (
          <View style={styles.placeholder} pointerEvents="box-none">
            <Text style={styles.placeholderText}>
              {permission?.canAskAgain === false
                ? "Autorisez la caméra dans les réglages, puis rechargez."
                : "Autorisez la caméra pour lancer un scan."}
            </Text>
            {!permission?.granted ? (
              <AnimatedPressable style={styles.permBtn} haptic="medium" onPress={requestPermission}>
                <Text style={styles.permBtnText}>Autoriser</Text>
              </AnimatedPressable>
            ) : null}
          </View>
        ) : null}
      </View>

      <View style={styles.guidance}>
        <Reveal key={guide} distance={6}>
          <Text
            style={[styles.guide, guide === "hold" && styles.guideOk]}
            testID="camera-guide"
          >
            {guideMessage(guide)}
          </Text>
        </Reveal>
        <Text style={styles.hint}>
          Tournez lentement la tête — les prises se font toutes seules.
        </Text>
      </View>

      <View style={styles.controls}>
        <AnimatedPressable
          testID="camera-gallery-btn"
          onPress={pickFromGallery}
          style={styles.secondaryBtn}
        >
          <Text style={styles.secondaryText}>Galerie</Text>
        </AnimatedPressable>

        {/* Repli : si le guidage n'a pas pu se charger, rien ne doit empecher
            de lancer une analyse simple. */}
        <AnimatedPressable
          testID="camera-capture-btn"
          onPress={manualCapture}
          style={styles.secondaryBtn}
          disabled={canUseCamera ? !ready : true}
          haptic="medium"
        >
          <Text style={styles.secondaryText}>Prendre maintenant</Text>
        </AnimatedPressable>
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
  headerTitle: { ...type.kicker, color: colors.fgDim, fontVariant: ["tabular-nums"] },

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

  stage: { flex: 1, overflow: "hidden" },
  placeholder: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.m,
  },
  placeholderText: { ...type.bodySmall, color: colors.fgDim, textAlign: "center", maxWidth: 240 },
  permBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: 26,
    paddingVertical: 11,
    borderRadius: radius.pill,
  },
  permBtnText: { ...type.kicker, color: colors.accent },

  guidance: { alignItems: "center", paddingHorizontal: spacing.l, paddingTop: spacing.m, gap: 6 },
  guide: { ...type.subtitle, color: colors.fg, textAlign: "center", minHeight: 26 },
  guideOk: { color: colors.accent },
  hint: { ...type.bodySmall, color: colors.fgDim, textAlign: "center" },

  controls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.m,
    paddingHorizontal: spacing.l,
    paddingTop: spacing.l,
    paddingBottom: spacing.m,
  },
  secondaryBtn: {
    paddingVertical: 13,
    paddingHorizontal: spacing.l,
    borderWidth: 1,
    borderColor: colors.borderMid,
    borderRadius: radius.pill,
    minHeight: 44,
    justifyContent: "center",
  },
  secondaryText: { ...type.kicker, color: colors.fgMuted },
});
