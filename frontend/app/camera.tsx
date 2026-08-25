import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutChangeEvent, Platform, StyleSheet, Text, View } from "react-native";
import Svg, { Defs, Mask, Path, Rect } from "react-native-svg";
import Animated, {
  useAnimatedProps,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
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
import { colors, radius, spacing, type } from "@/src/theme";
import { FACE_EXTENT, facePathAt } from "@/src/theme/mark";
import { storage } from "@/src/utils/storage";

/** Base64 nu, sans entete : c'est ce que le reste de l'app attend. */
const AnimatedPath = Animated.createAnimatedComponent(Path);

const cleanB64 = (b?: string | null) =>
  b ? (b.startsWith("data:") ? b.split(",")[1] ?? "" : b) : "";

/**
 * Ce qui separe la boite du detecteur du contour de la marque.
 *
 * BlazeFace rend une boite serree : elle s'arrete aux sourcils en haut et sous
 * la levre en bas. Le contour, lui, couvre le visage entier, front et menton
 * compris. Sans ce facteur, l'ovale se poserait au milieu du visage au lieu de
 * l'entourer.
 */
const BOX_TO_OVAL = 1.26;

/** Le detecteur centre sa boite sous les yeux : l'ovale doit remonter. */
const BOX_RISE = 0.13;

/** Lissage exponentiel de la detection, avant l'interpolation d'affichage. */
const SMOOTH = 0.45;

/** Sans visage pendant ce delai, le cadre revient au centre. */
const LOST_MS = 700;

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

  // Geometrie du cadre, en pixels d'ecran. Elle vit en valeurs animees : le
  // contour et la couronne suivent le visage image par image, sans repasser
  // par le rendu React — a 9 detections par seconde, un aller-retour par React
  // se verrait immediatement comme une saccade.
  const faceX = useSharedValue(0);
  const faceY = useSharedValue(0);
  const faceK = useSharedValue(0);
  const ringR = useSharedValue(0);
  const ringP = useSharedValue(0);
  /** Derniere position lissee, cote JS : la detection saute, l'affichage non. */
  const smoothRef = useRef<{ x: number; y: number; k: number } | null>(null);
  const lastSeenRef = useRef(0);
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
   * Pose le cadre sur le visage.
   *
   * Le contour et la couronne ne sont plus ancres a l'ecran : ils vont sur le
   * visage, et l'y suivent. Le cadre fixe obligeait a se placer dedans, avec
   * les consignes qui vont avec — "reculez", "centrez-vous". C'est a l'app de
   * trouver le visage, pas a la personne de trouver le cadre.
   *
   * La video est affichee en `cover` : agrandie jusqu'a remplir le champ, puis
   * rognee. Il faut refaire ce calcul pour convertir une detection en pixels
   * d'ecran, sinon le cadre derive des que les proportions de la camera
   * different de celles du champ. Et l'apercu etant en miroir, l'abscisse doit
   * etre retournee : sans ca, le cadre partirait du cote oppose au visage.
   */
  const placeFrame = useCallback(
    (d: { cx: number; cy: number; hRatio: number } | null, videoW: number, videoH: number) => {
      const { w, h } = stageRef.current;
      if (!w || !h) return;

      let target: { x: number; y: number; k: number };

      if (d && videoW && videoH) {
        const cover = Math.max(w / videoW, h / videoH);
        const dw = videoW * cover;
        const dh = videoH * cover;
        const ox = (w - dw) / 2;
        const oy = (h - dh) / 2;

        const faceH = d.hRatio * dh;
        const k = (faceH * BOX_TO_OVAL) / FACE_EXTENT.h;
        target = {
          x: w - (ox + d.cx * dw),
          y: oy + d.cy * dh - faceH * BOX_RISE,
          k,
        };
        lastSeenRef.current = Date.now();
      } else if (Date.now() - lastSeenRef.current < LOST_MS) {
        // Perte breve : on ne bouge pas. Un cadre qui repart au centre a chaque
        // image manquee clignoterait plus qu'il ne suivrait.
        return;
      } else {
        // Repos : au centre, a une taille de visage plausible.
        target = { x: w / 2, y: h / 2, k: Math.min(w * 0.78 / FACE_EXTENT.w, h * 0.7 / FACE_EXTENT.h) };
        smoothRef.current = null;
      }

      // Deux lissages successifs, et ils ne font pas la meme chose : celui-ci
      // absorbe le bruit du detecteur, l'interpolation qui suit comble les
      // ~110 ms entre deux detections.
      const prev = smoothRef.current;
      const sm = prev
        ? {
            x: prev.x + (target.x - prev.x) * SMOOTH,
            y: prev.y + (target.y - prev.y) * SMOOTH,
            k: prev.k + (target.k - prev.k) * SMOOTH,
          }
        : target;
      smoothRef.current = sm;

      const ms = { duration: 150 };
      faceX.value = withTiming(sm.x, ms);
      faceY.value = withTiming(sm.y, ms);
      faceK.value = withTiming(sm.k, ms);

      // La couronne se pose juste au-dela du contour, et son rayon n'est JAMAIS
      // reduit pour tenir dans le champ. La version precedente le faisait, et
      // des que le visage approchait d'un bord les traits retombaient sur la
      // peau — exactement ce qu'ils ne doivent pas faire. Un trait coupe par le
      // bord de l'ecran se lit comme un cadre qui sort ; un trait pose sur une
      // joue se lit comme un bug.
      ringR.value = withTiming((FACE_EXTENT.h / 2) * sm.k * 1.12, ms);
    },
    [faceX, faceY, faceK, ringR],
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
          // ~9 images par seconde. Le guidage seul s'accommodait de 5 : une
          // consigne toutes les 200 ms suffit a corriger une posture. Un cadre
          // qui SUIT le visage, non — a 5 images par seconde il saute
          // visiblement d'une position a l'autre.
          if (v && v.readyState >= 2 && v.videoWidth > 0 && now - last > 110) {
            last = now;
            try {
              const d = readDetection(
                detector.detectForVideo(v, now),
                v.videoWidth,
                v.videoHeight,
              );
              placeFrame(d, v.videoWidth, v.videoHeight);
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
  }, [canUseCamera, sample, ringP, placeFrame]);

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
  const laid = stage.w > 0 && stage.h > 0;

  // Position de repos, le temps qu'un visage apparaisse. Le cadre part de la
  // pour aller au visage : il ne surgit pas de nulle part.
  useEffect(() => {
    if (laid) placeFrame(null, 0, 0);
  }, [laid, stage.w, stage.h, placeFrame]);

  // Le contour se recalcule a chaque image plutot que d'etre transforme : `d`
  // n'est qu'une chaine, et une chaine se met a jour partout de la meme façon.
  const facePathProps = useAnimatedProps(() => ({
    d: facePathAt(faceX.value, faceY.value, faceK.value),
  }));

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
                {/* Le trou du voile : c'est lui qui suit le visage. */}
                <AnimatedPath fill="black" animatedProps={facePathProps} />
              </Mask>
            </Defs>

            <Rect width={stage.w} height={stage.h} fill={colors.bg} mask="url(#skyn-window)" />

            {/* Le trait du contour, sur le bord du trou. */}
            <AnimatedPath
              fill="none"
              stroke={colors.accent}
              strokeWidth={2}
              animatedProps={facePathProps}
            />

            {/* La couronne vit dans le repere de l'ecran, pas dans celui du
                dessin : son epaisseur ne doit pas suivre l'echelle du visage. */}
            <ScanRing cx={faceX} cy={faceY} radius={ringR} progress={ringP} />
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

  guidance: { alignItems: "center", paddingHorizontal: spacing.l, paddingTop: spacing.m },
  // Une seule ligne. Il y en avait deux, qui disaient la meme chose : la
  // consigne du moment, et un rappel permanent de tourner la tete.
  guide: { ...type.subtitle, color: colors.fg, textAlign: "center", minHeight: 26 },
  guideOk: { color: colors.accent },

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
