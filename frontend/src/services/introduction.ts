/**
 * Le suivi d'introduction.
 *
 * Le moment ou une routine echoue n'est presque jamais le choix du produit :
 * c'est la troisieme semaine, quand la peau va visiblement moins bien et qu'on
 * arrete. Certains actifs accelerent le renouvellement cellulaire et font
 * temporairement remonter des lesions deja formees sous la peau ; d'autres
 * fois, c'est une irritation qu'il faut arreter. De l'exterieur, les deux se
 * ressemblent.
 *
 * Ce module accompagne cette fenetre. Il pose chaque jour quelques questions
 * courtes et rend une LECTURE, jamais un diagnostic.
 *
 * ────────────────────────────────────────────────────────────────────────
 * LIMITE ASSUMEE : distinguer une adaptation d'une reaction ne se fait pas
 * de facon fiable a distance. Ce module ne dit donc jamais "c'est un purge"
 * ni "c'est une allergie". Il dit ce qui est frequent, ce qui l'est moins, et
 * a partir de quand il faut arreter et demander un avis. En cas de doute il
 * penche systematiquement vers l'arret : se tromper en arretant coute quelques
 * semaines, se tromper en continuant peut couter la barriere cutanee.
 * ────────────────────────────────────────────────────────────────────────
 */
import { track } from "@/src/services/analytics";
import { cancelIntroReminder, scheduleIntroReminder } from "@/src/services/reminders";
import { todayKey } from "@/src/services/routineStore";
import { storage } from "@/src/utils/storage";
import type { ProductPick } from "@/src/types/analysis";

const K_TRACKINGS = "skyn_introductions";

/**
 * Familles qui accelerent le renouvellement cellulaire.
 *
 * C'est la distinction qui compte : seule cette categorie peut faire remonter
 * des lesions deja en formation. Une creme hydratante ou de la niacinamide qui
 * declenche des boutons ne "s'adapte" pas — c'est autre chose, et il ne faut
 * pas encourager quelqu'un a persister.
 */
export const ACCELERATING = new Set([
  "retinoid",
  "retinoide",
  "bha",
  "aha",
  "benzoyl_peroxide",
  "peroxyde_benzoyle",
]);

export type Signal =
  | "lesions_up"
  | "lesions_same"
  | "lesions_down"
  | "burning"
  | "peeling"
  | "itching"
  | "swelling"
  | "new_zones";

export const SIGNALS: { key: Signal; label: string; group: "lesions" | "tolerance" }[] = [
  { key: "lesions_down", label: "Moins de boutons", group: "lesions" },
  { key: "lesions_same", label: "Comme avant", group: "lesions" },
  { key: "lesions_up", label: "Plus de boutons", group: "lesions" },
  { key: "new_zones", label: "Sur des zones inhabituelles", group: "tolerance" },
  { key: "peeling", label: "Peau qui pèle", group: "tolerance" },
  { key: "burning", label: "Ça brûle / picote", group: "tolerance" },
  { key: "itching", label: "Ça démange", group: "tolerance" },
  { key: "swelling", label: "Gonflement, cloques", group: "tolerance" },
];

export interface DayLog {
  date: string;
  signals: Signal[];
}

export interface Tracking {
  id: string;
  productId: string;
  name: string;
  brand: string;
  family: string | null;
  startedAt: string;
  logs: DayLog[];
  stoppedAt?: string;
  stopReason?: "user" | "alert" | "completed";
}

export type VerdictLevel = "early" | "expected" | "watch" | "stop" | "settled" | "too_long";

export interface Verdict {
  level: VerdictLevel;
  title: string;
  body: string;
  /** Ce que l'utilisateur peut faire maintenant. */
  action: string;
}

/* ------------------------------------------------------------------ */
/* Persistance                                                         */
/* ------------------------------------------------------------------ */

export async function getTrackings(): Promise<Tracking[]> {
  try {
    const raw = (await storage.getItem(K_TRACKINGS, "[]")) as string;
    return JSON.parse(raw || "[]") as Tracking[];
  } catch {
    return [];
  }
}

async function save(list: Tracking[]): Promise<void> {
  await storage.setItem(K_TRACKINGS, JSON.stringify(list));
}

export async function activeTracking(): Promise<Tracking | null> {
  return (await getTrackings()).find((t) => !t.stoppedAt) ?? null;
}

export async function startTracking(p: ProductPick): Promise<Tracking> {
  const list = await getTrackings();
  const t: Tracking = {
    id: `intro_${Date.now()}`,
    productId: p.id,
    name: p.name,
    brand: p.brand,
    family: p.family ?? null,
    startedAt: new Date().toISOString(),
    logs: [],
  };
  // Un seul suivi a la fois : deux actifs introduits en parallele rendraient
  // toute lecture impossible, on ne saurait pas lequel produit quoi.
  const next = list.map((x) => (x.stoppedAt ? x : { ...x, stoppedAt: new Date().toISOString(), stopReason: "user" as const }));
  next.push(t);
  await save(next);

  // Le rappel quotidien est le declencheur de la boucle : il se met en place
  // tout seul, sans reglage a faire. S'il est refuse, le suivi fonctionne
  // quand meme — on ne bloque pas une fonctionnalite sur une autorisation.
  const armed = await scheduleIntroReminder(p.name);
  await track("intro_started", { family: p.family ?? "inconnue", rappel: armed });
  return t;
}

export async function stopTracking(
  id: string,
  reason: Tracking["stopReason"] = "user",
): Promise<void> {
  const list = await getTrackings();
  await save(
    list.map((t) => (t.id === id ? { ...t, stoppedAt: new Date().toISOString(), stopReason: reason } : t)),
  );
  // Un rappel qui survit au suivi qu'il accompagnait devient une nuisance.
  await cancelIntroReminder();
  await track(reason === "completed" ? "intro_completed" : "intro_stopped", {
    reason: reason ?? "user",
  });
}

/** Enregistre le point du jour. Un seul par jour : le dernier remplace. */
export async function logDay(id: string, signals: Signal[]): Promise<Tracking | null> {
  const list = await getTrackings();
  const day = todayKey();
  let updated: Tracking | null = null;

  const next = list.map((t) => {
    if (t.id !== id) return t;
    const logs = t.logs.filter((l) => l.date !== day);
    logs.push({ date: day, signals });
    logs.sort((a, b) => a.date.localeCompare(b.date));
    updated = { ...t, logs };
    return updated;
  });

  await save(next);
  await track("intro_checkin", { jour: dayNumber(updated ?? list[0]), signaux: signals.length });
  return updated;
}

export function todayLogged(t: Tracking): boolean {
  return t.logs.some((l) => l.date === todayKey());
}

/** Numero du jour de suivi, en commençant a 1. */
export function dayNumber(t: Tracking): number {
  const start = new Date(t.startedAt);
  const s = Date.UTC(start.getFullYear(), start.getMonth(), start.getDate());
  const now = new Date();
  const n = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.floor((n - s) / 86400000) + 1;
}

/* ------------------------------------------------------------------ */
/* Lecture                                                             */
/* ------------------------------------------------------------------ */

function countRecent(t: Tracking, signal: Signal, days: number): number {
  return t.logs.slice(-days).filter((l) => l.signals.includes(signal)).length;
}

function hasEver(t: Tracking, signal: Signal): boolean {
  return t.logs.some((l) => l.signals.includes(signal));
}

/**
 * Rend la lecture du moment.
 *
 * Les regles sont ordonnees par gravite : le premier signal d'alerte gagne,
 * quelle que soit la suite. On ne compense jamais un signe inquietant par un
 * signe rassurant.
 */
export function readTracking(t: Tracking, day = dayNumber(t)): Verdict {
  const accelerating = t.family ? ACCELERATING.has(t.family) : false;

  // 1. Gonflement, cloques : ces signes evoquent une reaction de contact et
  //    n'appartiennent a aucun profil d'adaptation. Arret, sans nuance.
  if (hasEver(t, "swelling")) {
    return {
      level: "stop",
      title: "Arrêtez ce produit",
      body:
        "Un gonflement ou des cloques ne font partie d'aucun profil d'adaptation. " +
        "Ce sont des signes qui demandent un avis médical, pas de la patience.",
      action: "Arrêter et consulter un médecin ou un pharmacien",
    };
  }

  // 2. Demangeaison persistante : ce n'est pas le profil d'une adaptation.
  if (countRecent(t, "itching", 7) >= 3) {
    return {
      level: "stop",
      title: "Ce n'est pas un profil d'adaptation",
      body:
        "Des démangeaisons plusieurs jours de suite orientent vers une intolérance " +
        "plutôt que vers une phase de transition. Continuer risque d'abîmer la barrière cutanée.",
      action: "Arrêter le produit et demander un avis",
    };
  }

  // 3. Le produit n'accelere pas le renouvellement : il ne peut pas faire
  //    remonter des lesions deja formees. Encourager a persister serait faux.
  if (!accelerating && countRecent(t, "lesions_up", 7) >= 3) {
    return {
      level: "watch",
      title: "Ce produit ne devrait pas provoquer ça",
      body:
        "Seuls les actifs qui accélèrent le renouvellement cellulaire peuvent faire " +
        "temporairement remonter des lésions. Ce n'est pas le cas de celui-ci : " +
        "l'augmentation observée vient probablement d'autre chose.",
      action: "Suspendre quelques jours pour voir si ça change",
    };
  }

  // 4. Brulure repetee : signe d'une frequence trop elevee pour cette peau.
  if (countRecent(t, "burning", 7) >= 3) {
    return {
      level: "watch",
      title: "Espacez les applications",
      body:
        "Une sensation de brûlure plusieurs jours de suite indique une fréquence trop " +
        "élevée pour votre peau, pas une étape à franchir.",
      action: "Passer à un soir sur trois pendant deux semaines",
    };
  }

  if (t.logs.length === 0) {
    return {
      level: "early",
      title: "Suivi démarré",
      body: "Notez ce que vous observez chaque jour. C'est la régularité qui rend la lecture possible.",
      action: "Renseigner le premier point",
    };
  }

  // 5. Nouvelles zones : une remontee de lesions se produit la ou il y en
  //    avait deja. Ailleurs, l'explication est plus probablement autre.
  if (hasEver(t, "new_zones") && countRecent(t, "lesions_up", 7) >= 2) {
    return {
      level: "watch",
      title: "Des zones qui ne réagissaient pas",
      body:
        "Une remontée liée au renouvellement cellulaire touche les zones qui marquaient " +
        "déjà. Sur des zones nouvelles, l'explication est plus probablement ailleurs : " +
        "un autre produit, une friction, autre chose.",
      action: "Vérifier ce qui a changé d'autre cette semaine",
    };
  }

  if (day <= 7) {
    return {
      level: "early",
      title: `Jour ${day} : trop tôt pour conclure`,
      body:
        "Les premiers jours ne veulent rien dire, dans un sens comme dans l'autre. " +
        "Continuez à noter : c'est la troisième semaine qui est informative.",
      action: "Noter ce que vous observez aujourd'hui",
    };
  }

  const up = countRecent(t, "lesions_up", 7);
  const better = countRecent(t, "lesions_down", 7) + countRecent(t, "lesions_same", 7);

  // 6. Au-dela de huit semaines, une aggravation persistante n'est plus une
  //    transition, quelle que soit la molecule.
  if (day > 56 && up >= 3) {
    return {
      level: "too_long",
      title: "Trop long pour une phase de transition",
      body:
        "Au-delà de huit semaines, une aggravation qui dure n'est plus attribuable à " +
        "une mise en route. Ce produit ne semble pas vous convenir.",
      action: "Arrêter et en parler à un professionnel",
    };
  }

  // 7. Le profil frequemment decrit : aggravation transitoire sous un actif
  //    accelerant, sur les zones habituelles, sans signe d'intolerance.
  if (accelerating && up >= 2 && day <= 42) {
    return {
      level: "expected",
      title: "Fréquent à ce stade",
      body:
        `Une augmentation des lésions dans les premières semaines d'un actif de ce type ` +
        `est fréquemment rapportée et se résorbe le plus souvent avant huit semaines. ` +
        `Vous êtes au jour ${day}. Ce n'est pas une certitude, c'est ce qui est le plus courant.`,
      action: "Tenir encore, sans augmenter la fréquence",
    };
  }

  if (better >= 3 && up === 0) {
    return {
      level: "settled",
      title: "Ça se stabilise",
      body:
        "Aucune aggravation sur vos derniers points. La phase de mise en route semble " +
        "passée : c'est maintenant que le produit commence à se juger.",
      action: "Continuer, et refaire un scan pour mesurer",
    };
  }

  return {
    level: "early",
    title: `Jour ${day}`,
    body: "Rien de marquant dans vos derniers points. Continuez à noter.",
    action: "Noter ce que vous observez aujourd'hui",
  };
}

/** Les niveaux qui doivent interrompre l'utilisateur plutot que l'informer. */
export function isAlert(v: Verdict): boolean {
  return v.level === "stop" || v.level === "too_long";
}

/**
 * Produits eligibles a un suivi : ceux qui portent un actif dont la mise en
 * route se surveille. Un nettoyant ou une creme solaire n'ont rien a suivre.
 */
export function candidates(products: ProductPick[]): ProductPick[] {
  // Dedoublonnage : un serum est souvent prescrit matin ET soir, et la liste
  // arrive concatenee. Sans ca, le meme produit s'affichait deux fois dans le
  // choix, ce qui donne l'impression d'un bug plus que d'un choix.
  const seen = new Set<string>();
  return products.filter((p) => {
    if (p.step === "nettoyant" || p.step === "protection") return false;
    if (!p.family && p.irritation <= 0.2) return false;
    if (seen.has(p.id)) return false;
    seen.add(p.id);
    return true;
  });
}
