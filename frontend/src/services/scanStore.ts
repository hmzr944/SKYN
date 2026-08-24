/**
 * Le magasin des analyses.
 *
 * Jusqu'ici un scan produisait un ecran, puis disparaissait : seule la routine
 * survivait. L'accueil et l'historique lisaient de leur cote les rapports du
 * moteur v1, que le parcours camera ne cree jamais — d'ou une app qui affichait
 * "pas encore d'analyse" apres chaque analyse.
 *
 * Ce module est desormais la source unique : il garde l'analyse COMPLETE, si
 * bien qu'un scan peut etre rouvert tel quel des semaines plus tard.
 *
 * Tout est local. On plafonne volontairement le nombre d'analyses completes
 * conservees : une analyse porte la liste de ses lesions, et AsyncStorage n'est
 * pas une base de donnees. Les resumes, eux, sont minuscules et sont gardes
 * sans limite — c'est eux qui tracent la courbe de progression.
 */
import { getLegacyScans } from "@/src/services/routineStore";
import { storage } from "@/src/utils/storage";
import type { ConcernKey, FaceAnalysis, SkinType } from "@/src/types/analysis";

const K_INDEX = "skyn_scans_index";
const K_FULL = "skyn_scan_full_";

/** Au-dela, les plus anciennes analyses completes sont elaguees. */
const FULL_KEPT = 12;

export interface ScanSummary {
  id: string;
  date: string;
  global_score: number;
  diagnosis: string;
  summary: string;
  skin_type: SkinType;
  severity_level: number;
  severity_label: string;
  lesion_total: number;
  top_concerns: ConcernKey[];
  /** Faux des que l'analyse complete a ete elaguee : seul le resume reste. */
  detailed: boolean;
}

function newId(): string {
  return `scan_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

export async function listScans(): Promise<ScanSummary[]> {
  const raw = (await storage.getItem(K_INDEX, "")) as string;
  if (!raw) return migrateLegacy();
  try {
    const list = JSON.parse(raw) as ScanSummary[];
    // Le plus recent d'abord — c'est l'ordre dont tous les ecrans ont besoin.
    return list.sort((a, b) => +new Date(b.date) - +new Date(a.date));
  } catch {
    return [];
  }
}

/**
 * Reprise de l'ancien historique.
 *
 * Les scans d'avant ce module n'existaient qu'en resume : on les remonte tels
 * quels, marques comme non detailles, pour ne pas trouer la courbe de
 * progression de quelqu'un qui utilisait deja l'app.
 */
async function migrateLegacy(): Promise<ScanSummary[]> {
  const old = await getLegacyScans();
  if (!old.length) return [];
  const list: ScanSummary[] = old.map((e, i) => ({
    id: `legacy_${i}_${new Date(e.date).getTime()}`,
    date: e.date,
    global_score: e.global_score,
    diagnosis: e.diagnosis,
    summary: e.diagnosis,
    skin_type: (e.skin_type as SkinType) ?? "indetermine",
    severity_level: e.severity_level,
    severity_label: "",
    lesion_total: e.lesion_total,
    top_concerns: [],
    detailed: false,
  }));
  const sorted = list.sort((a, b) => +new Date(b.date) - +new Date(a.date));
  await storage.setItem(K_INDEX, JSON.stringify(sorted));
  return sorted;
}

export async function getScan(id: string): Promise<FaceAnalysis | null> {
  const raw = (await storage.getItem(K_FULL + id, "")) as string;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as FaceAnalysis;
  } catch {
    return null;
  }
}

export async function latestScan(): Promise<ScanSummary | null> {
  return (await listScans())[0] ?? null;
}

/** Enregistre une analyse et renvoie son identifiant. */
export async function saveScan(a: FaceAnalysis): Promise<string> {
  const id = newId();
  const lesionTotal = Object.values(a.lesion_counts ?? {}).reduce(
    (x, y) => x + (y ?? 0),
    0,
  );

  const summary: ScanSummary = {
    id,
    date: new Date().toISOString(),
    global_score: a.global_score,
    diagnosis: a.diagnosis,
    summary: a.summary,
    skin_type: a.skin_type,
    severity_level: a.severity_level,
    severity_label: a.severity_label,
    lesion_total: lesionTotal,
    top_concerns: a.top_concerns ?? [],
    detailed: true,
  };

  await storage.setItem(K_FULL + id, JSON.stringify(a));

  const index = await listScans();
  const next = [summary, ...index];

  // Elagage : on retire le detail des analyses les plus anciennes, mais on
  // garde leur resume pour ne pas trouer la courbe de progression.
  const detailed = next.filter((s) => s.detailed);
  for (const old of detailed.slice(FULL_KEPT)) {
    await storage.removeItem(K_FULL + old.id);
    old.detailed = false;
  }

  await storage.setItem(K_INDEX, JSON.stringify(next));
  return id;
}

/**
 * Sous-scores façon rapport, derives des charges de preoccupation.
 *
 * Les `concerns` v2 sont des charges entre 0 et 1 (plus haut = plus atteint),
 * alors que les scores affiches vont de 0 a 100 dans l'autre sens.
 */
export function subScores(a: FaceAnalysis) {
  const inv = (v: number | undefined) =>
    Math.max(0, Math.min(100, Math.round(100 * (1 - (v ?? 0)))));
  return {
    texture: inv(a.concerns?.texture),
    radiance: inv(a.concerns?.dullness),
    imperfections: inv(a.concerns?.acne_active),
  };
}

/** Ecart de score avec l'analyse precedente, ou null s'il n'y en a pas. */
export async function scoreDelta(): Promise<number | null> {
  const scans = await listScans();
  if (scans.length < 2) return null;
  return scans[0].global_score - scans[1].global_score;
}
