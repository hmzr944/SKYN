import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Dimensions,
  ActivityIndicator,
  Image,
  Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Svg, { Circle } from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedProps,
  withTiming,
  Easing,
  withSpring,
  useAnimatedStyle,
  withDelay,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";

import { colors, fonts, spacing, radius, shadow } from "@/src/theme";
import { api, getLocalReport, ProductReco } from "@/src/services/api";
import { storage } from "@/src/utils/storage";
import { FadeIn } from "@/src/components/ui/FadeIn";
import { AnimatedPressable } from "@/src/components/ui/AnimatedPressable";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

// Accompagnement : chaque métrique est expliquée en langage clair
const METRIC_INFO: Record<string, { title: string; what: string; advice: string }> = {
  texture: {
    title: "Texture",
    what: "La régularité du grain de peau : micro-reliefs, rugosités et finesse des pores, mesurés par l'analyse des contrastes de surface de votre photo.",
    advice: "Une exfoliation douce hebdomadaire et une hydratation régulière lissent progressivement le grain de peau.",
  },
  radiance: {
    title: "Éclat",
    what: "L'uniformité et la luminosité de votre teint, évaluées dans l'espace colorimétrique de la photo. Un score bas traduit un teint terne ou irrégulier.",
    advice: "La vitamine C le matin, une bonne hydratation et un sommeil régulier ravivent l'éclat naturel.",
  },
  imperfections: {
    title: "Imperfections",
    what: "Les lésions repérées par notre détecteur entraîné (boutons, points noirs) et le grade clinique estimé de l'acné, de peau nette à sévère.",
    advice: "Niacinamide ou acide salicylique le soir, et surtout : ne percez pas — laissez les actifs travailler.",
  },
};

function scoreInterpretation(score: number): string {
  if (score >= 80) return "Peau équilibrée — continuez ainsi";
  if (score >= 65) return "Bon équilibre, à entretenir";
  if (score >= 50) return "Des besoins ciblés — suivez votre routine";
  return "Votre peau réclame de l'attention";
}
const { width: SCREEN_W } = Dimensions.get("window");
const RING = Math.min(SCREEN_W - spacing.xl * 2, 240);
const STROKE = 6;
const R = (RING - STROKE) / 2;
const CIRC = 2 * Math.PI * R;

function ScoreRing({ value }: { value: number }) {
  const progress = useSharedValue(0);
  const display = useSharedValue(0);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    progress.value = withTiming(value / 100, {
      duration: 1800,
      easing: Easing.out(Easing.cubic),
    });
    display.value = withTiming(value, { duration: 1800 });
    const id = setInterval(() => setShown(Math.round(display.value)), 32);
    setTimeout(() => clearInterval(id), 2000);
    return () => clearInterval(id);
  }, [value, progress, display]);

  const animProps = useAnimatedProps(() => ({
    strokeDashoffset: CIRC * (1 - progress.value),
  }));

  return (
    <View style={{ width: RING, height: RING, alignItems: "center", justifyContent: "center" }}>
      <Svg width={RING} height={RING}>
        <Circle
          cx={RING / 2}
          cy={RING / 2}
          r={R}
          stroke={colors.borderSubtle}
          strokeWidth={STROKE}
          fill="transparent"
        />
        <AnimatedCircle
          cx={RING / 2}
          cy={RING / 2}
          r={R}
          stroke={colors.accent}
          strokeWidth={STROKE}
          fill="transparent"
          strokeDasharray={`${CIRC} ${CIRC}`}
          animatedProps={animProps}
          strokeLinecap="round"
          transform={`rotate(-90, ${RING / 2}, ${RING / 2})`}
        />
      </Svg>
      <View style={styles.ringCenter}>
        <Text style={styles.ringEyebrow}>SCORE GLOBAL</Text>
        <Text style={styles.ringValue} testID="report-global-score">
          {shown}
        </Text>
        <Text style={styles.ringUnit}>sur 100</Text>
      </View>
    </View>
  );
}

function MetricCell({
  label,
  value,
  variant,
  delay,
  onInfo,
}: {
  label: string;
  value: number;
  variant: "tall" | "small";
  delay: number;
  onInfo?: () => void;
}) {
  const sv = useSharedValue(0);
  useEffect(() => {
    sv.value = withDelay(delay, withSpring(1, { damping: 16, stiffness: 90 }));
  }, [sv, delay]);
  const aStyle = useAnimatedStyle(() => ({
    opacity: sv.value,
    transform: [{ translateY: (1 - sv.value) * 12 }],
  }));
  return (
    <Animated.View style={[styles.metricCell, styles[variant], aStyle]}>
      <TouchableOpacity
        style={{ flex: 1, justifyContent: "space-between" }}
        onPress={onInfo}
        activeOpacity={0.7}
        testID={`metric-${label}`}
      >
        <View
          style={[
            styles.metricDot,
            { backgroundColor: value > 70 ? colors.lime : colors.accent },
          ]}
        />
        <Text style={styles.metricLabel}>{label}</Text>
        <View>
          <Text style={styles.metricValue}>{value}</Text>
          <Text style={styles.metricHint}>Comprendre ⓘ</Text>
        </View>
      </TouchableOpacity>
    </Animated.View>
  );
}

function MetricInfoSheet({
  metricKey,
  onClose,
}: {
  metricKey: string | null;
  onClose: () => void;
}) {
  if (!metricKey) return null;
  const info = METRIC_INFO[metricKey];
  if (!info) return null;
  return (
    <TouchableOpacity
      style={styles.infoOverlay}
      activeOpacity={1}
      onPress={onClose}
      testID="metric-info-sheet"
    >
      <View style={styles.infoCard}>
        <Text style={styles.infoTitle}>{info.title}</Text>
        <Text style={styles.infoSectionLabel}>CE QUE ÇA MESURE</Text>
        <Text style={styles.infoText}>{info.what}</Text>
        <Text style={styles.infoSectionLabel}>NOTRE CONSEIL</Text>
        <Text style={styles.infoText}>{info.advice}</Text>
        <Text style={styles.infoClose}>Toucher pour fermer</Text>
      </View>
    </TouchableOpacity>
  );
}

function confidenceColor(score: number): string {
  if (score >= 85) return colors.lime;
  if (score >= 65) return colors.accent;
  if (score >= 45) return colors.accentSoft;
  return colors.fgDim;
}

function ProductCard({ product, index }: { product: ProductReco; index: number }) {
  const [imgFailed, setImgFailed] = useState(false);
  const [showReasons, setShowReasons] = useState(false);

  const openLink = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    Linking.openURL(product.url).catch(() => {});
  };

  return (
    <FadeIn delay={index * 80} distance={10}>
      <AnimatedPressable
        style={styles.productCard}
        onPress={openLink}
        scaleTo={0.98}
        testID={`product-card-${index}`}
      >
        <View style={styles.productImageWrap}>
          {imgFailed ? (
            <Text style={styles.productImageFallback}>
              {product.brand.charAt(0)}
            </Text>
          ) : (
            <Image
              source={{ uri: product.image_url }}
              style={styles.productImage}
              resizeMode="contain"
              onError={() => setImgFailed(true)}
            />
          )}
        </View>
        <View style={styles.productBody}>
          <View style={styles.productMetaRow}>
            <Text style={styles.productStep}>{product.step_label}</Text>
            <View
              style={[
                styles.momentBadge,
                product.moment === "soir" && styles.momentBadgeNight,
              ]}
            >
              <Text style={styles.momentText}>
                {product.moment === "matin" ? "☀ " : product.moment === "soir" ? "☾ " : "☀☾ "}
                {product.moment_label || "Matin & soir"}
              </Text>
            </View>
          </View>
          <Text style={styles.productName} numberOfLines={2}>
            {product.brand} — {product.name}
          </Text>
          <Text style={styles.productWhy} numberOfLines={3}>
            {product.why}
          </Text>

          {typeof product.match_confidence === "number" ? (
            <TouchableOpacity
              onPress={() => setShowReasons((s) => !s)}
              activeOpacity={0.7}
              testID={`product-confidence-${index}`}
            >
              <View style={styles.confidenceRow}>
                <View
                  style={[
                    styles.confidenceDot,
                    { backgroundColor: confidenceColor(product.match_confidence) },
                  ]}
                />
                <Text style={styles.confidenceText}>
                  {product.match_confidence}% adapté à votre peau — {product.confidence_label}
                </Text>
              </View>
              {showReasons && product.match_reasons?.length ? (
                <View style={styles.reasonsBox}>
                  {product.match_reasons.map((r, i) => (
                    <Text key={i} style={styles.reasonItem}>• {r}</Text>
                  ))}
                </View>
              ) : null}
            </TouchableOpacity>
          ) : null}

          <View style={styles.productFooter}>
            <Text style={styles.productPrice}>≈ {product.price_eur.toFixed(0)} €</Text>
            <Text style={styles.productLink}>Voir le produit →</Text>
          </View>
        </View>
      </AnimatedPressable>
    </FadeIn>
  );
}

export default function ReportScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [lowLight, setLowLight] = useState(false);
  const [metricInfo, setMetricInfo] = useState<string | null>(null);
  const [delta, setDelta] = useState<number | null>(null);

  const sheetY = useSharedValue(1);

  useEffect(() => {
    (async () => {
      try {
        // Rapport local (créé quand la sauvegarde cloud a échoué juste après
        // le scan) : jamais d'appel réseau, on l'affiche tel quel.
        if (id?.startsWith("local-")) {
          const local = await getLocalReport(id);
          setReport(local);
          return;
        }

        const list = await api.listReports();
        let current: any = null;
        if (id) {
          current = list.find((r: any) => r.id === id) || (await api.getReport(id));
        } else {
          current = list[0] || null;
        }
        setReport(current);
        // Delta vs bilan précédent (accompagnement : voir sa progression)
        if (current) {
          const idx = list.findIndex((r: any) => r.id === current.id);
          const prev = idx >= 0 ? list[idx + 1] : list[1];
          if (prev) setDelta(current.global_score - prev.global_score);
        }
      } finally {
        setLoading(false);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      }
    })();

    (async () => {
      const flag = (await storage.getItem("skyn_last_low_light", "")) as string;
      if (flag === "1") {
        setLowLight(true);
        await storage.setItem("skyn_last_low_light", "");
      }
    })();
  }, [id]);

  const toggleSheet = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    sheetY.value = withTiming(sheetOpen ? 1 : 0, {
      duration: 420,
      easing: Easing.out(Easing.cubic),
    });
    setSheetOpen((s) => !s);
  };

  const sheetStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: sheetY.value * 480 }],
  }));

  const handleFinish = () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    router.replace("/dashboard");
  };

  if (loading) {
    return (
      <SafeAreaView style={[styles.container, styles.center]} edges={["top", "bottom"]}>
        <ActivityIndicator color={colors.fgMuted} />
      </SafeAreaView>
    );
  }

  if (!report) {
    return (
      <SafeAreaView style={[styles.container, styles.center]} edges={["top", "bottom"]}>
        <Text style={styles.empty}>Aucun rapport disponible.</Text>
        <TouchableOpacity onPress={() => router.replace("/dashboard")} style={styles.linkBackBtn}>
          <Text style={styles.linkBack}>← Retour au tableau de bord</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      {/* Top bar */}
      <View style={styles.topBar}>
        <TouchableOpacity onPress={handleFinish} style={styles.topBackBtn}>
          <Text style={styles.topBackText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>Bilan Clinique</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <FadeIn>
          <Text style={styles.dateTop}>
            {new Date(report.created_at).toLocaleDateString("fr-FR", {
              day: "2-digit",
              month: "long",
              year: "numeric",
            })}
          </Text>
        </FadeIn>

        {lowLight ? (
          <FadeIn distance={6}>
            <View style={styles.lowLightBanner} testID="report-low-light-notice">
              <Text style={styles.lowLightText}>
                Luminosité faible détectée lors de la prise de vue — pour un bilan plus précis, refaites le test dans un environnement bien éclairé.
              </Text>
            </View>
          </FadeIn>
        ) : null}

        {report.diagnosis ? (
          <FadeIn delay={60}>
            <Text style={styles.diagnosis} testID="report-diagnosis">
              {report.diagnosis}
            </Text>
          </FadeIn>
        ) : null}

        {report.skin_type_detected || report.acne_severity_label ? (
          <FadeIn delay={90} distance={6}>
            <View style={styles.aiChipsRow}>
              {report.skin_type_detected ? (
                <View style={styles.aiChip} testID="report-skin-type">
                  <Text style={styles.aiChipText}>
                    Peau {report.skin_type_detected.toLowerCase()} détectée
                  </Text>
                </View>
              ) : null}
              {report.acne_severity_label ? (
                <View style={styles.aiChip} testID="report-acne-severity">
                  <Text style={styles.aiChipText}>{report.acne_severity_label}</Text>
                </View>
              ) : null}
            </View>
          </FadeIn>
        ) : null}

        <FadeIn delay={100} distance={20}>
          <View style={styles.ringWrap}>
            <ScoreRing value={report.global_score} />
            <Text style={styles.interpretation} testID="report-interpretation">
              {scoreInterpretation(report.global_score)}
            </Text>
            {delta !== null && delta !== 0 ? (
              <View style={[styles.deltaChip, delta > 0 ? styles.deltaUp : styles.deltaDown]}>
                <Text style={styles.deltaText} testID="report-delta">
                  {delta > 0 ? "▲" : "▼"} {delta > 0 ? "+" : ""}{delta} depuis votre dernier bilan
                </Text>
              </View>
            ) : null}
          </View>
        </FadeIn>

        {/* Asymmetric metric grid */}
        <View style={styles.gridWrap}>
          <View style={styles.row1}>
            <MetricCell
              label="Texture"
              value={report.texture}
              variant="tall"
              delay={150}
              onInfo={() => setMetricInfo("texture")}
            />
            <View style={styles.column}>
              <MetricCell
                label="Éclat"
                value={report.radiance}
                variant="small"
                delay={300}
                onInfo={() => setMetricInfo("radiance")}
              />
              <MetricCell
                label="Imperfections"
                value={report.imperfections}
                variant="small"
                delay={450}
                onInfo={() => setMetricInfo("imperfections")}
              />
            </View>
          </View>
        </View>

        {/* Personalised product routine */}
        {report.products?.length ? (
          <View style={styles.productsSection}>
            <FadeIn delay={200} distance={8}>
              <Text style={styles.productsEyebrow}>VOTRE ROUTINE</Text>
              <Text style={styles.productsTitle}>Produits recommandés</Text>
            </FadeIn>
            {report.products.map((p: ProductReco, i: number) => (
              <ProductCard key={p.id} product={p} index={i} />
            ))}
          </View>
        ) : null}

        {/* Recommendations trigger */}
        <AnimatedPressable
          testID="report-recos-toggle"
          style={styles.recoTrigger}
          onPress={toggleSheet}
          scaleTo={0.98}
        >
          <Text style={styles.recoTriggerText}>
            {sheetOpen ? "Masquer les recommandations" : "Voir les recommandations"}
          </Text>
          <Text style={styles.recoArrow}>{sheetOpen ? "↓" : "↑"}</Text>
        </AnimatedPressable>

        <View style={{ height: 120 }} />
      </ScrollView>

      {/* Finish button */}
      <AnimatedPressable
        testID="report-finish-btn"
        style={styles.finishBtn}
        onPress={handleFinish}
      >
        <Text style={styles.finishText}>Terminer et Sauvegarder</Text>
      </AnimatedPressable>

      {/* Metric explanation overlay */}
      <MetricInfoSheet metricKey={metricInfo} onClose={() => setMetricInfo(null)} />

      {/* Recommendations sheet */}
      <Animated.View
        style={[styles.sheet, sheetStyle]}
        pointerEvents={sheetOpen ? "auto" : "none"}
      >
        <View style={styles.sheetHandleWrap}>
          <View style={styles.handleBar} />
        </View>
        <Text style={styles.sheetTitle}>Recommandations</Text>
        <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
          {(report.recommendations || []).map((r: string, i: number) => (
            <FadeIn key={i} delay={i * 60} distance={8}>
              <View style={styles.recoItem} testID={`reco-item-${i}`}>
                <Text style={styles.recoIdx}>0{i + 1}</Text>
                <Text style={styles.recoText}>{r}</Text>
              </View>
            </FadeIn>
          ))}
        </ScrollView>
        <AnimatedPressable
          onPress={toggleSheet}
          style={styles.sheetClose}
          testID="report-sheet-close"
          scaleTo={0.96}
        >
          <Text style={styles.sheetCloseText}>Fermer</Text>
        </AnimatedPressable>
      </Animated.View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  empty: {
    color: colors.fgMuted,
    fontFamily: fonts.body,
    fontSize: 15,
    marginBottom: spacing.m,
  },
  linkBackBtn: { marginTop: spacing.s },
  linkBack: {
    color: colors.fgMuted,
    fontFamily: fonts.body,
    fontSize: 13,
    letterSpacing: 0.5,
  },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.s,
    paddingBottom: spacing.m,
  },
  topBackBtn: { width: 40, paddingVertical: 4 },
  topBackText: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 20,
  },
  topTitle: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    letterSpacing: 3,
    fontSize: 11,
    textTransform: "uppercase",
  },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxl },
  dateTop: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 2,
    textAlign: "center",
    textTransform: "uppercase",
    marginTop: spacing.s,
  },
  diagnosis: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 18,
    textAlign: "center",
    marginTop: spacing.m,
    paddingHorizontal: spacing.l,
    letterSpacing: 0.5,
    lineHeight: 26,
  },
  lowLightBanner: {
    marginTop: spacing.m,
    marginHorizontal: spacing.l,
    borderWidth: 1,
    borderColor: colors.borderMid,
    paddingVertical: 12,
    paddingHorizontal: spacing.m,
    backgroundColor: colors.accentSofter,
    borderRadius: radius.sm,
  },
  lowLightText: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 12,
    lineHeight: 18,
    letterSpacing: 0.3,
    textAlign: "center",
  },
  ringWrap: {
    alignItems: "center",
    marginTop: spacing.l,
    marginBottom: spacing.xl,
  },
  ringCenter: { position: "absolute", alignItems: "center" },
  ringEyebrow: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 9,
    letterSpacing: 3,
    textTransform: "uppercase",
  },
  ringValue: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 80,
    letterSpacing: -3,
    lineHeight: 86,
  },
  ringUnit: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  gridWrap: { marginTop: spacing.m },
  row1: { flexDirection: "row", gap: spacing.s },
  column: { flex: 1, gap: spacing.s },
  metricCell: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.md,
    padding: spacing.m,
    justifyContent: "space-between",
    ...shadow.card,
  },
  metricDot: {
    position: "absolute",
    top: spacing.m,
    right: spacing.m,
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  tall: { flex: 1, minHeight: 200 },
  small: { flex: 1, minHeight: 96 },
  metricLabel: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 9,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  metricValue: {
    fontFamily: fonts.heading,
    color: colors.accent,
    fontSize: 48,
    letterSpacing: -1,
  },
  metricHint: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 10,
    letterSpacing: 0.5,
    marginTop: 2,
  },
  interpretation: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 13,
    letterSpacing: 0.3,
    marginTop: spacing.m,
    textAlign: "center",
  },
  deltaChip: {
    marginTop: spacing.s,
    borderRadius: radius.pill,
    paddingVertical: 5,
    paddingHorizontal: 14,
  },
  deltaUp: { backgroundColor: colors.limeSoft },
  deltaDown: { backgroundColor: colors.accentSofter },
  deltaText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  infoOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(45,31,26,0.45)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    zIndex: 20,
  },
  infoCard: {
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.lg,
    padding: spacing.l,
    width: "100%",
    maxWidth: 420,
    ...shadow.raised,
  },
  infoTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 26,
    letterSpacing: -0.5,
    marginBottom: spacing.s,
  },
  infoSectionLabel: {
    fontFamily: fonts.bodyMedium,
    color: colors.accent,
    fontSize: 10,
    letterSpacing: 2,
    marginTop: spacing.m,
    marginBottom: 4,
  },
  infoText: {
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 14,
    lineHeight: 21,
  },
  infoClose: {
    fontFamily: fonts.body,
    color: colors.fgDim,
    fontSize: 11,
    letterSpacing: 1,
    textAlign: "center",
    marginTop: spacing.l,
    textTransform: "uppercase",
  },
  productMetaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  momentBadge: {
    backgroundColor: colors.limeSoft,
    borderRadius: radius.pill,
    paddingVertical: 2,
    paddingHorizontal: 8,
  },
  momentBadgeNight: {
    backgroundColor: colors.accentSofter,
  },
  momentText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 9,
    letterSpacing: 0.5,
  },
  aiChipsRow: {
    flexDirection: "row",
    justifyContent: "center",
    gap: spacing.s,
    marginTop: spacing.m,
    flexWrap: "wrap",
  },
  aiChip: {
    borderWidth: 1,
    borderColor: colors.borderMid,
    backgroundColor: colors.accentSofter,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: 14,
  },
  aiChipText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  productsSection: { marginTop: spacing.xl },
  productsEyebrow: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 9,
    letterSpacing: 3,
    textTransform: "uppercase",
  },
  productsTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 22,
    letterSpacing: -0.5,
    marginTop: 4,
    marginBottom: spacing.m,
  },
  productCard: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.md,
    padding: spacing.m,
    marginBottom: spacing.s,
    gap: spacing.m,
    ...shadow.card,
  },
  productImageWrap: {
    width: 72,
    height: 72,
    borderRadius: radius.sm,
    backgroundColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  productImage: { width: 64, height: 64 },
  productImageFallback: {
    fontFamily: fonts.heading,
    color: colors.accent,
    fontSize: 28,
    opacity: 0.4,
  },
  productBody: { flex: 1 },
  productStep: {
    fontFamily: fonts.bodyMedium,
    color: colors.accent,
    fontSize: 9,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  productName: {
    fontFamily: fonts.headingMedium,
    color: colors.fg,
    fontSize: 14,
    marginTop: 2,
    lineHeight: 19,
  },
  productWhy: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 12,
    lineHeight: 17,
    marginTop: 4,
  },
  confidenceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 6,
  },
  confidenceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  confidenceText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 10.5,
    letterSpacing: 0.2,
  },
  reasonsBox: {
    marginTop: 6,
    paddingLeft: 12,
    gap: 2,
  },
  reasonItem: {
    fontFamily: fonts.body,
    color: colors.fgMuted,
    fontSize: 11,
    lineHeight: 16,
  },
  productFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.s,
  },
  productPrice: {
    fontFamily: fonts.bodyMedium,
    color: colors.fgDim,
    fontSize: 12,
  },
  productLink: {
    fontFamily: fonts.bodyMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  recoTrigger: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.s,
    paddingVertical: spacing.l,
    marginTop: spacing.m,
  },
  recoTriggerText: {
    fontFamily: fonts.bodyMedium,
    color: colors.fg,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  recoArrow: {
    color: colors.fgMuted,
    fontSize: 16,
  },
  finishBtn: {
    position: "absolute",
    bottom: 28,
    left: spacing.xl,
    right: spacing.xl,
    backgroundColor: colors.bg,
    paddingVertical: 18,
    alignItems: "center",
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.accent,
  },
  finishText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 13,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  sheet: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    height: 480,
    backgroundColor: colors.surfaceRaised,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
    paddingBottom: spacing.l,
    ...shadow.raised,
  },
  sheetHandleWrap: { alignItems: "center", marginBottom: spacing.m },
  handleBar: {
    width: 36,
    height: 4,
    backgroundColor: colors.borderMid,
    borderRadius: 2,
  },
  sheetTitle: {
    fontFamily: fonts.heading,
    color: colors.fg,
    fontSize: 26,
    letterSpacing: -0.5,
    marginBottom: spacing.m,
  },
  recoItem: {
    flexDirection: "row",
    paddingVertical: spacing.m,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
    gap: spacing.m,
  },
  recoIdx: {
    fontFamily: fonts.heading,
    color: colors.accent,
    opacity: 0.2,
    fontSize: 32,
    width: 40,
    lineHeight: 36,
  },
  recoText: {
    flex: 1,
    fontFamily: fonts.body,
    color: colors.fg,
    fontSize: 14,
    lineHeight: 22,
  },
  sheetClose: {
    marginTop: spacing.m,
    alignSelf: "center",
    paddingVertical: 12,
    paddingHorizontal: 32,
    borderWidth: 1.5,
    borderColor: colors.accent,
    borderRadius: radius.pill,
  },
  sheetCloseText: {
    fontFamily: fonts.headingMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
});
