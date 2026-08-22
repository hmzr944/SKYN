/**
 * Suivi local de la routine et des series.
 *
 * Tout est stocke sur l'appareil : la routine du jour, les cases cochees et
 * l'historique. Aucune de ces donnees ne transite par le serveur.
 *
 * Le calcul de serie suit la regle habituelle : un jour compte des qu'au moins
 * un moment de la journee a ete complete, et la serie en cours tolere que la
 * journee d'aujourd'hui ne soit pas encore faite (sinon elle afficherait zero
 * chaque matin au reveil, ce qui est decourageant et faux).
 */
import { storage } from "@/src/utils/storage";
import type { FaceAnalysis, ProductPick } from "@/src/types/analysis";

const K_ROUTINE = "skyn_routine_v2";
const K_LOG = "skyn_routine_log";
const K_SCANS = "skyn_scan_history";

export interface StoredRoutine {
  am: ProductPick[];
  pm: ProductPick[];
  weekly: ProductPick[];
  total_price: number;
  savedAt: string;
  diagnosis: string;
  skin_type: string;
}

/** Journal : "2026-08-22" -> { am: [ids], pm: [ids] } */
export type RoutineLog = Record<string, { am: string[]; pm: string[] }>;

export interface ScanEntry {
  date: string;
  global_score: number;
  diagnosis: string;
  severity_level: number;
  lesion_total: number;
  skin_type: string;
}

export function todayKey(d: Date = new Date()): string {
  // Cle locale (pas UTC) : a 23 h a Paris, on est encore aujourd'hui.
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function addDays(key: string, delta: number): string {
  const [y, m, d] = key.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + delta);
  return todayKey(dt);
}

/* ---------------- Routine ---------------- */
export async function saveRoutineFromAnalysis(a: FaceAnalysis): Promise<void> {
  const r: StoredRoutine = {
    am: a.routine.am,
    pm: a.routine.pm,
    weekly: a.routine.weekly,
    total_price: a.routine.total_price,
    savedAt: new Date().toISOString(),
    diagnosis: a.diagnosis,
    skin_type: a.skin_type,
  };
  await storage.setItem(K_ROUTINE, JSON.stringify(r));

  const scans = await getScans();
  const entry: ScanEntry = {
    date: new Date().toISOString(),
    global_score: a.global_score,
    diagnosis: a.diagnosis,
    severity_level: a.severity_level,
    lesion_total: Object.values(a.lesion_counts ?? {}).reduce((x, y) => x + y, 0),
    skin_type: a.skin_type,
  };
  await storage.setItem(K_SCANS, JSON.stringify([...scans, entry]));
}

export async function getRoutine(): Promise<StoredRoutine | null> {
  const raw = (await storage.getItem(K_ROUTINE, "")) as string;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredRoutine;
  } catch {
    return null;
  }
}

export async function getScans(): Promise<ScanEntry[]> {
  const raw = (await storage.getItem(K_SCANS, "[]")) as string;
  try {
    return JSON.parse(raw || "[]") as ScanEntry[];
  } catch {
    return [];
  }
}

/* ---------------- Journal ---------------- */
export async function getLog(): Promise<RoutineLog> {
  const raw = (await storage.getItem(K_LOG, "{}")) as string;
  try {
    return JSON.parse(raw || "{}") as RoutineLog;
  } catch {
    return {};
  }
}

export async function toggleStep(
  moment: "am" | "pm",
  productId: string,
  day: string = todayKey(),
): Promise<RoutineLog> {
  const log = await getLog();
  const entry = log[day] ?? { am: [], pm: [] };
  const list = entry[moment];
  entry[moment] = list.includes(productId)
    ? list.filter((x) => x !== productId)
    : [...list, productId];
  log[day] = entry;
  await storage.setItem(K_LOG, JSON.stringify(log));
  return log;
}

/* ---------------- Series ---------------- */
function dayCounts(log: RoutineLog, day: string): boolean {
  const e = log[day];
  return !!e && (e.am.length > 0 || e.pm.length > 0);
}

export function currentStreak(log: RoutineLog, today: string = todayKey()): number {
  // Si la journee n'est pas encore entamee, on part d'hier : la serie ne doit
  // pas retomber a zero simplement parce qu'il est 8 h du matin.
  let cursor = dayCounts(log, today) ? today : addDays(today, -1);
  let n = 0;
  while (dayCounts(log, cursor)) {
    n += 1;
    cursor = addDays(cursor, -1);
  }
  return n;
}

export function bestStreak(log: RoutineLog): number {
  const days = Object.keys(log).filter((d) => dayCounts(log, d)).sort();
  let best = 0;
  let run = 0;
  let prev: string | null = null;
  for (const d of days) {
    run = prev && addDays(prev, 1) === d ? run + 1 : 1;
    best = Math.max(best, run);
    prev = d;
  }
  return best;
}

/** Nombre de jours completes sur les `window` derniers jours. */
export function completionRate(
  log: RoutineLog,
  windowDays = 30,
  today: string = todayKey(),
): number {
  let done = 0;
  for (let i = 0; i < windowDays; i++) {
    if (dayCounts(log, addDays(today, -i))) done += 1;
  }
  return done / windowDays;
}

/** Derniers `n` jours, du plus ancien au plus recent, pour la frise. */
export function recentDays(
  log: RoutineLog,
  n = 14,
  today: string = todayKey(),
): { day: string; am: boolean; pm: boolean }[] {
  const out: { day: string; am: boolean; pm: boolean }[] = [];
  for (let i = n - 1; i >= 0; i--) {
    const day = addDays(today, -i);
    const e = log[day];
    out.push({ day, am: !!e?.am.length, pm: !!e?.pm.length });
  }
  return out;
}
