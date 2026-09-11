import { CONCERN_LABEL, LESION_LABEL, ZONE_LABEL } from "@/src/types/analysis";
import type { ConcernKey, LesionType, ZoneKey } from "@/src/types/analysis";
import type {
  ActivePeriodView,
  ChangeDirection,
  ChangeKind,
  Confidence,
  MemoryScan,
  Period,
  SkinChangeItem,
} from "@/src/types/skinMemory";

/**
 * Lecture d'un SkinChangeItem pour l'affichage — la seule logique de
 * traduction "direction brute -> tonalite" du produit. Vit ici, pas
 * duplique par ecran, pour qu'un changement de regle (ex. un nouveau
 * concern) ne se corrige qu'a un seul endroit.
 *
 * Regle : jamais de vert ni de rouge nouveaux. Deux tonalites seulement,
 * exactement celles deja definies par le design system —
 *   "calm"  -> terre, rien a signaler (stable ET amelioration)
 *   "watch" -> corail, demande de l'attention
 * La polarite depend du type de metrique : un concern ou un compte de
 * lesions qui MONTE est une aggravation (watch) ; une zone qui monte est
 * une amelioration (le score de zone va vers 100 = peau nette), donc
 * l'inverse.
 */
export type ChangeTone = "calm" | "watch";

export function changeTone(kind: ChangeKind, direction: ChangeDirection): ChangeTone {
  if (direction === "stable") return "calm";
  const risingIsBad = kind === "concern" || kind === "lesion_type";
  const rising = direction === "up";
  return rising === risingIsBad ? "watch" : "calm";
}

/** Le libellé humain d'une métrique, quel que soit son type — jamais la clé brute (ex. "post_acne_marks") affichée telle quelle. */
export function metricLabel(item: Pick<SkinChangeItem, "metric" | "kind">): string {
  if (item.kind === "concern") return CONCERN_LABEL[item.metric as ConcernKey] ?? item.metric;
  if (item.kind === "zone") return ZONE_LABEL[item.metric as ZoneKey] ?? item.metric;
  return LESION_LABEL[item.metric as LesionType] ?? item.metric;
}

const DIRECTION_WORD: Record<ChangeTone, Record<ChangeDirection, string>> = {
  calm: { up: "Amélioration", down: "Amélioration", stable: "Stable" },
  watch: { up: "Variation à surveiller", down: "Variation à surveiller", stable: "Stable" },
};

/** "Amélioration" / "Stable" / "Variation à surveiller" — jamais "hausse"/"baisse", qui ne dit rien sans connaître la polarité de la métrique. */
export function directionLabel(item: Pick<SkinChangeItem, "kind" | "direction">): string {
  const tone = changeTone(item.kind, item.direction);
  return DIRECTION_WORD[tone][item.direction];
}

export function confidenceLabel(c: Confidence): string {
  return { low: "Confiance faible", medium: "Confiance moyenne", high: "Confiance élevée" }[c];
}

/** Nombre de points pleins (sur 3) pour la puce de confiance. */
export function confidenceDots(c: Confidence): number {
  return { low: 1, medium: 2, high: 3 }[c];
}

/**
 * La phrase corrélationnelle du Bulletin — jamais de causalité affirmée.
 * `null` si aucun produit n'est attribuable (voir SkinChangeItem.attribution,
 * qui n'est renseigné par le backend que sous confiance suffisante et
 * sans chevauchement de changement de routine dans la Phase).
 */
export function attributionSentence(item: SkinChangeItem, productLabel: (id: string) => string): string | null {
  if (!item.attribution || item.attribution.length === 0) return null;
  const names = item.attribution.map(productLabel).join(", ");
  return `Depuis l'introduction de ${names}, une évolution a été observée.`;
}

/**
 * Même règle corrélationnelle que `attributionSentence`, mais pour une
 * Phase nommée (voir POST /api/treatments) plutôt qu'un produit introduit
 * dans la routine — deux mécanismes distincts, jamais mélangés : celle-ci
 * lit `period.label`, l'autre `item.attribution`. `null` si la Phase n'a
 * pas de nom (changement de routine anonyme, ou Baseline) ou si la
 * confiance est trop faible pour qu'une phrase interprétative ait un sens.
 */
export function phaseAttributionSentence(item: SkinChangeItem, period: Period): string | null {
  if (!period.label || item.confidence === "low") return null;
  return `Cette évolution est associée à la période suivant l'introduction de ${period.label}, sans permettre d'en conclure qu'il en est la cause.`;
}

/**
 * Confiance par zone, pour FaceZoneMap#zoneConfidence — la Carte qui se
 * Complète (Personal Skin Map). Vide tant que la Phase n'a qu'un seul
 * scan : à ce stade il n'y a rien à comparer, la carte doit se lire comme
 * un relevé normal du jour, pas comme une carte "en construction".
 */
export function zoneConfidenceMap(changes: SkinChangeItem[]): Partial<Record<ZoneKey, Confidence>> {
  const out: Partial<Record<ZoneKey, Confidence>> = {};
  for (const c of changes) {
    if (c.kind === "zone") out[c.metric as ZoneKey] = c.confidence;
  }
  return out;
}

/** Le score du dernier scan de la Phase, ou `null` — un scan guidé n'en produit pas (voir skyn_engine.v2.multiview). */
export function latestScore(scans: MemoryScan[]): number | null {
  return scans.length ? scans[scans.length - 1].global_score : null;
}

/**
 * Les zones qui se sont le plus dégagées sur la Phase — pour le Bilan de
 * traitement ("Zones les plus améliorées : front, menton"). Seulement les
 * zones en tonalité "calm" avec un vrai mouvement (jamais "stable"), triées
 * par amplitude, jamais par zone alphabétique — l'ordre porte l'information.
 */
export function topImprovedZones(changes: SkinChangeItem[], limit = 3): SkinChangeItem[] {
  return changes
    .filter((c) => c.kind === "zone" && c.direction !== "stable" && changeTone(c.kind, c.direction) === "calm")
    .sort((a, b) => Math.abs(b.latest_value - b.baseline_value) - Math.abs(a.latest_value - a.baseline_value))
    .slice(0, limit);
}

export type PhaseVerdict = "improving" | "watch" | "mixed" | "insufficient";

/**
 * Le verdict global d'une Phase ("Évolution globale : amélioration") — se
 * lit UNIQUEMENT sur les changements assez confiants pour compter comme
 * une vraie tendance (jamais "low", voir `_confidence_for_series` côté
 * serveur). Sans un seul changement medium/high, il n'y a rien à conclure :
 * `"insufficient"`, jamais un verdict optimiste par défaut — c'est la même
 * règle que `phaseAttributionSentence` et `InsufficientPill`, appliquée ici
 * à l'ensemble de la Phase plutôt qu'à une seule métrique.
 */
export function phaseVerdict(changes: SkinChangeItem[]): PhaseVerdict {
  const trustworthy = changes.filter((c) => c.confidence !== "low" && c.direction !== "stable");
  if (trustworthy.length === 0) return "insufficient";
  let calm = 0;
  let watch = 0;
  for (const c of trustworthy) {
    if (changeTone(c.kind, c.direction) === "calm") calm++;
    else watch++;
  }
  if (calm > watch) return "improving";
  if (watch > calm) return "watch";
  return "mixed";
}

export const PHASE_VERDICT_LABEL: Record<PhaseVerdict, string> = {
  improving: "Amélioration globale sur cette période",
  watch: "Surtout des variations à surveiller sur cette période",
  mixed: "Évolution mixte sur cette période",
  insufficient: "Pas assez de données pour conclure",
};

/**
 * Vrai si la Phase active est un traitement nommé, en cours depuis au
 * moins 7 jours, sans le moindre nouveau scan depuis son début — le cas où
 * un rappel J+7/14/30 (programmé une seule fois, en local, voir
 * `scheduleTreatmentCheckpoints`) a été ignoré. Ne distingue pas LEQUEL des
 * trois checkpoints est en cause : passé le premier, ce n'est plus
 * actionnable de plus que "vous êtes en retard, faites le point" — voir la
 * relance sur le tableau de bord.
 */
export function isTreatmentCheckpointOverdue(view: ActivePeriodView): boolean {
  if (!view.period.label || view.period.ends_at) return false;
  const daysSince = (Date.now() - new Date(view.period.starts_at).getTime()) / 86400000;
  return daysSince >= 7 && view.scans.length === 0;
}
