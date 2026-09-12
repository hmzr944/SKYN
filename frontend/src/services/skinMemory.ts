import { api } from "@/src/services/api";
import { track } from "@/src/services/analytics";
import { checkpointDate, PHASE_CHECKPOINT_DAYS } from "@/src/services/reminders";
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

/**
 * Doctrine produit SKYN, pas une simple décision d'interface : SKYN
 * observe, SKYN compare, SKYN n'interprète jamais une évolution cutanée
 * comme un diagnostic médical. "Amélioration"/"Détérioration" affirment un
 * jugement de valeur que la mesure ne permet pas — "Évolution observée"
 * et "À surveiller" décrivent ce qui a été mesuré, jamais s'il fallait
 * s'en réjouir ou s'en inquiéter.
 */
const DIRECTION_WORD: Record<ChangeTone, Record<ChangeDirection, string>> = {
  calm: { up: "Évolution observée", down: "Évolution observée", stable: "Stable" },
  watch: { up: "À surveiller", down: "À surveiller", stable: "Stable" },
};

/** "Évolution observée" / "Stable" / "À surveiller" — jamais "amélioration"/"détérioration", qui affirment un jugement que la mesure ne permet pas ; jamais "hausse"/"baisse", qui ne disent rien sans connaître la polarité de la métrique. */
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
 * Les zones où le changement observé est le plus net sur la Phase — pour
 * le Bilan de traitement. Seulement les zones en tonalité "calm" avec un
 * vrai mouvement (jamais "stable"), triées par amplitude, jamais par zone
 * alphabétique — l'ordre porte l'information. "calm" ne veut pas dire
 * "améliorées" : voir la doctrine sur DIRECTION_WORD.
 */
export function topImprovedZones(changes: SkinChangeItem[], limit = 3): SkinChangeItem[] {
  return changes
    .filter((c) => c.kind === "zone" && c.direction !== "stable" && changeTone(c.kind, c.direction) === "calm")
    .sort((a, b) => Math.abs(b.latest_value - b.baseline_value) - Math.abs(a.latest_value - a.baseline_value))
    .slice(0, limit);
}

export type PhaseVerdict = "improving" | "watch" | "mixed" | "insufficient";

/**
 * Le verdict global d'une Phase — se lit UNIQUEMENT sur les changements
 * assez confiants pour compter comme une vraie tendance (jamais "low",
 * voir `_confidence_for_series` côté serveur). Sans un seul changement
 * medium/high, il n'y a rien à conclure : `"insufficient"`, jamais un
 * verdict optimiste par défaut — c'est la même règle que
 * `phaseAttributionSentence` et `InsufficientPill`, appliquée ici à
 * l'ensemble de la Phase plutôt qu'à une seule métrique.
 *
 * "improving" ne veut pas dire "va mieux" : il veut dire "la majorité des
 * changements confiants sont en tonalité calme" — voir PHASE_VERDICT_LABEL,
 * qui ne dit jamais "amélioration" ni "détérioration" (doctrine SKYN :
 * observer et comparer, jamais diagnostiquer).
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
  improving: "Évolution stable sur cette période",
  watch: "Des changements à surveiller sur cette période",
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

export interface UpcomingCheckpoint {
  day: 7 | 14 | 30;
  date: Date;
}

/**
 * Le prochain rendez-vous J+7/14/30 d'un traitement en cours — le pendant
 * "positif" de `isTreatmentCheckpointOverdue` : montrer ce qui arrive,
 * pas seulement relancer quand c'est déjà en retard. `null` pour une Phase
 * sans nom (changement de routine anonyme, ou baseline), déjà close, ou
 * dont les trois échéances sont déjà passées — la boucle passe alors la
 * main au Bilan, pas à un quatrième rendez-vous inventé.
 */
export function upcomingCheckpoint(period: Period): UpcomingCheckpoint | null {
  if (!period.label || period.ends_at) return null;
  const start = new Date(period.starts_at);
  const now = Date.now();
  for (const day of PHASE_CHECKPOINT_DAYS) {
    const date = checkpointDate(start, day);
    if (date.getTime() > now) return { day, date };
  }
  return null;
}

export type CheckpointStatus = "done" | "next" | "upcoming" | "missed";

export interface CheckpointMarker {
  day: 0 | 7 | 14 | 30;
  date: Date;
  status: CheckpointStatus;
}

/** Un scan tombe "sur" un rendez-vous s'il arrive dans cette fenêtre autour
 * de la date recommandée — personne ne scanne à l'heure pile, et ce n'est
 * pas ce qu'on mesure. */
const CHECKPOINT_TOLERANCE_DAYS = 3;

/**
 * La timeline J0 → J7 → J14 → J30 d'une Phase — où l'utilisateur en est
 * dans la boucle de suivi, jamais un jugement sur le résultat. "missed" ne
 * veut pas dire "raté" au sens négatif : juste "cette échéance est passée
 * sans scan à proximité" — voir la doctrine sur DIRECTION_WORD, la même
 * règle s'applique ici. `null` pour une Phase sans nom : ces échéances
 * n'ont jamais été programmées pour elle (voir scheduleTreatmentCheckpoints).
 */
export function phaseTimeline(period: Period, scans: MemoryScan[]): CheckpointMarker[] | null {
  if (!period.label) return null;
  const start = new Date(period.starts_at);
  const closed = !!period.ends_at;
  const now = Date.now();
  const scanTimes = scans.map((s) => new Date(s.created_at).getTime());
  const toleranceMs = CHECKPOINT_TOLERANCE_DAYS * 86400000;

  const markers: CheckpointMarker[] = [{ day: 0, date: start, status: "done" }];
  let nextAssigned = false;
  for (const day of PHASE_CHECKPOINT_DAYS) {
    const date = checkpointDate(start, day);
    const hasScanNear = scanTimes.some((t) => Math.abs(t - date.getTime()) <= toleranceMs);
    let status: CheckpointStatus;
    if (hasScanNear) {
      status = "done";
    } else if (!closed && date.getTime() > now) {
      status = nextAssigned ? "upcoming" : "next";
      nextAssigned = true;
    } else {
      status = "missed";
    }
    markers.push({ day: day as 7 | 14 | 30, date, status });
  }
  return markers;
}

/**
 * Démarre un traitement nommé et journalise la fermeture de la Phase
 * précédente (si elle existe) — un seul point d'entrée pour
 * start-treatment.tsx et IntroductionCard.tsx, pour que le calcul de durée
 * ne puisse jamais diverger de l'appel réel à POST /api/treatments.
 * Prépare les KPI "Phases complétées" (voir analytics.ts::phaseFunnel) —
 * aucune donnée n'est envoyée au serveur au-delà de l'appel déjà existant.
 */
export async function startTreatmentTracked(name: string, goal?: string): Promise<void> {
  let previous: ActivePeriodView | null = null;
  try {
    previous = await api.getActivePeriod();
  } catch {
    /* best effort — l'instrumentation ne doit jamais bloquer le vrai appel */
  }
  await api.startTreatment(name, goal);
  if (previous) {
    const days = Math.round((Date.now() - new Date(previous.period.starts_at).getTime()) / 86400000);
    await track("phase_closed", {
      period_id: previous.period.id,
      duration_days: days,
      scan_count: previous.scans.length,
    });
  }
  await track("phase_started", { has_label: true });
}
