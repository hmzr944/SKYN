/**
 * Le journal de peau.
 *
 * Un scanner dit ce qu'il voit. Un assistant dit ce qui a change autour.
 * Les facteurs retenus sont ceux pour lesquels il existe une litterature
 * dermatologique reelle sur l'acne : sommeil, stress, friction mecanique,
 * charge glycemique et laitages, cycle hormonal.
 *
 * PRUDENCE — ce module ne prouve rien. Il decrit une coincidence entre des
 * journees declarees et un score mesure, sur un echantillon d'une personne.
 * C'est pourquoi les observations sont verrouillees sous un seuil de donnees
 * et formulees comme des constats, jamais comme des causes. Une correlation
 * sur douze jours n'est pas un mecanisme.
 */
import { listScans } from "@/src/services/scanStore";
import { todayKey } from "@/src/services/routineStore";
import { storage } from "@/src/utils/storage";

const K_JOURNAL = "skyn_journal";

export type FactorKey = "sommeil" | "stress" | "friction" | "sucre" | "laitages" | "cycle";

/** Valeur d'un facteur : 0 = absent/bon, 1 = present/mauvais. */
export type DayEntry = Partial<Record<FactorKey, 0 | 1>>;

/** "2026-08-24" -> facteurs du jour */
export type Journal = Record<string, DayEntry>;

export interface FactorDef {
  key: FactorKey;
  label: string;
  /** Formulation de l'etat "coche" — c'est toujours l'etat defavorable. */
  onLabel: string;
  /** Ce que dit la litterature, en une phrase honnete. */
  note: string;
  /** Niveau de preuve, meme echelle que le catalogue produits. */
  evidence: "A" | "B" | "C";
}

// Ces libelles et ces notes sont AFFICHES. Les commentaires du code sont sans
// accents, par commodite d'edition ; le texte lu par quelqu'un ne peut pas
// l'etre — "Journee stressante" sur un ecran, c'est une faute.
export const FACTORS: FactorDef[] = [
  {
    key: "sommeil",
    label: "Nuit courte",
    onLabel: "Moins de 6 h",
    note: "Le manque de sommeil élève le cortisol, qui stimule la production de sébum.",
    evidence: "B",
  },
  {
    key: "stress",
    label: "Journée stressante",
    onLabel: "Stress marqué",
    note: "Le stress est associé à une aggravation des poussées, sans qu'on sache le quantifier.",
    evidence: "B",
  },
  {
    key: "friction",
    label: "Frottement",
    onLabel: "Casque, masque, sport",
    note: "La friction répétée provoque une acné mécanique, surtout menton et mâchoire.",
    evidence: "A",
  },
  {
    key: "sucre",
    label: "Charge sucrée",
    onLabel: "Repas très sucré",
    note: "Une charge glycémique élevée est liée à plus de lésions dans plusieurs essais.",
    evidence: "B",
  },
  {
    key: "laitages",
    label: "Laitages",
    onLabel: "Consommation notable",
    note: "Le lait écrémé ressort surtout, l'effet reste modeste et discuté.",
    evidence: "C",
  },
  {
    key: "cycle",
    label: "Cycle",
    onLabel: "Période prémenstruelle",
    note: "Les poussées mandibulaires suivent souvent la deuxième partie du cycle.",
    evidence: "A",
  },
];

export async function getJournal(): Promise<Journal> {
  const raw = (await storage.getItem(K_JOURNAL, "{}")) as string;
  try {
    return JSON.parse(raw || "{}") as Journal;
  } catch {
    return {};
  }
}

export async function getDay(day: string = todayKey()): Promise<DayEntry> {
  return (await getJournal())[day] ?? {};
}

export async function toggleFactor(
  key: FactorKey,
  day: string = todayKey(),
): Promise<DayEntry> {
  const journal = await getJournal();
  const entry = { ...(journal[day] ?? {}) };
  entry[key] = entry[key] ? 0 : 1;
  journal[day] = entry;
  await storage.setItem(K_JOURNAL, JSON.stringify(journal));
  return entry;
}

/** Nombre de jours ou au moins un facteur a ete renseigne. */
export async function loggedDays(): Promise<number> {
  const journal = await getJournal();
  return Object.values(journal).filter((e) => Object.keys(e).length > 0).length;
}

/* ------------------------------------------------------------------ */
/* Observations                                                        */
/* ------------------------------------------------------------------ */

/** En deca, on n'affiche rien : le bruit depasserait le signal. */
export const MIN_SCANS = 3;
export const MIN_DAYS = 12;

export interface Observation {
  factor: FactorKey;
  label: string;
  note: string;
  /** Ecart de score moyen entre scans precedes du facteur et les autres. */
  gap: number;
  /** Nombre de scans pris en compte. */
  sample: number;
}

function daysBefore(day: string, n: number): string[] {
  const [y, m, d] = day.split("-").map(Number);
  const out: string[] = [];
  for (let i = 1; i <= n; i += 1) {
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() - i);
    out.push(todayKey(dt));
  }
  return out;
}

/**
 * Compare le score des scans precedes d'un facteur a celui des autres.
 *
 * Fenetre de sept jours avant chaque scan : une lesion inflammatoire met
 * plusieurs jours a sortir, regarder le jour meme n'aurait aucun sens.
 *
 * Renvoie une liste vide tant qu'il n'y a pas assez de matiere, et ne garde
 * qu'un ecart franc — en dessous, on regarderait du bruit.
 */
export async function observations(): Promise<Observation[]> {
  const [journal, scans] = await Promise.all([getJournal(), listScans()]);
  const days = Object.values(journal).filter((e) => Object.keys(e).length > 0).length;
  if (scans.length < MIN_SCANS || days < MIN_DAYS) return [];

  const out: Observation[] = [];

  for (const f of FACTORS) {
    const withF: number[] = [];
    const without: number[] = [];

    for (const scan of scans) {
      const window = daysBefore(todayKey(new Date(scan.date)), 7);
      // On exige que la fenetre ait ete renseignee, sinon "pas de facteur"
      // serait confondu avec "pas de journal".
      const filled = window.filter((d) => journal[d] && Object.keys(journal[d]).length > 0);
      if (filled.length < 3) continue;
      const hits = filled.filter((d) => journal[d][f.key] === 1).length;
      (hits >= 2 ? withF : without).push(scan.global_score);
    }

    if (withF.length < 2 || without.length < 2) continue;
    const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
    const gap = Math.round(mean(without) - mean(withF));
    if (gap < 4) continue;

    out.push({
      factor: f.key,
      label: f.label,
      note: f.note,
      gap,
      sample: withF.length + without.length,
    });
  }

  return out.sort((a, b) => b.gap - a.gap).slice(0, 2);
}
