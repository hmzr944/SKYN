/**
 * Journal d'evenements local.
 *
 * L'app n'avait aucune instrumentation. Celle-ci reste volontairement pauvre :
 * un journal horodate sur l'appareil, plafonne, sans identifiant ni envoi
 * reseau. Il sert a repondre a une seule question — les gens reviennent-ils —
 * et non a profiler qui que ce soit.
 *
 * Rien ne part de l'appareil. Le jour ou un envoi sera necessaire, il devra
 * etre choisi explicitement par l'utilisateur ; en attendant, ces donnees se
 * lisent en debug et servent a decider si la fonctionnalite merite d'exister.
 */
import { storage } from "@/src/utils/storage";

const K_EVENTS = "skyn_events";
const K_FIRST = "skyn_first_seen";

/** Au-dela, les plus anciens evenements sont oublies. */
const MAX_EVENTS = 400;

export type EventName =
  // Exposition et activation de la fonctionnalite
  | "intro_feature_seen"
  | "intro_started"
  | "intro_checkin"
  | "intro_checkin_skipped"
  | "intro_alert_shown"
  | "intro_stopped"
  | "intro_completed"
  // Ouvertures, pour mesurer le retour
  | "app_opened"
  | "scan_started"
  | "scan_completed";

export interface Event {
  name: EventName;
  at: string;
  /** Details libres, volontairement courts. */
  meta?: Record<string, string | number | boolean>;
}

export async function track(name: EventName, meta?: Event["meta"]): Promise<void> {
  try {
    const raw = (await storage.getItem(K_EVENTS, "[]")) as string;
    const list = JSON.parse(raw || "[]") as Event[];
    list.push({ name, at: new Date().toISOString(), meta });
    await storage.setItem(K_EVENTS, JSON.stringify(list.slice(-MAX_EVENTS)));

    const first = (await storage.getItem(K_FIRST, "")) as string;
    if (!first) await storage.setItem(K_FIRST, new Date().toISOString());
  } catch {
    // L'instrumentation ne doit jamais casser un parcours.
  }
}

export async function allEvents(): Promise<Event[]> {
  try {
    const raw = (await storage.getItem(K_EVENTS, "[]")) as string;
    return JSON.parse(raw || "[]") as Event[];
  } catch {
    return [];
  }
}

function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

export interface Funnel {
  /** A vu la fonctionnalite au moins une fois. */
  exposed: boolean;
  /** A demarre un suivi. */
  activated: boolean;
  /** Nombre de points quotidiens renseignes. */
  checkins: number;
  /** Jours distincts avec au moins un point. */
  activeDays: number;
  /** Points renseignes / jours ecoules depuis l'activation. */
  frequency: number | null;
  /** Est revenu apres son premier point. */
  returnedAfterFirst: boolean;
  /** Revenu le lendemain / a une semaine / a un mois de l'activation. */
  d1: boolean;
  d7: boolean;
  d30: boolean;
  /** A abandonne : active, mais rien depuis plus de trois jours. */
  abandoned: boolean;
}

/**
 * Entonnoir de retention.
 *
 * `d7` et `d30` restent faux tant que le delai n'est pas ecoule : on ne peut
 * pas conclure a un abandon a J+30 le jour meme de l'installation. C'est la
 * distinction entre "pas encore revenu" et "pas revenu".
 */
export async function funnel(): Promise<Funnel> {
  const events = await allEvents();
  const exposed = events.some((e) => e.name === "intro_feature_seen");
  const starts = events.filter((e) => e.name === "intro_started");
  const checkins = events.filter((e) => e.name === "intro_checkin");

  if (!starts.length) {
    return {
      exposed,
      activated: false,
      checkins: checkins.length,
      activeDays: 0,
      frequency: null,
      returnedAfterFirst: false,
      d1: false,
      d7: false,
      d30: false,
      abandoned: false,
    };
  }

  const start = new Date(starts[0].at).getTime();
  const days = (n: number) => start + n * 86400000;
  const now = Date.now();
  const seenOn = (from: number, to: number) =>
    checkins.some((e) => {
      const t = new Date(e.at).getTime();
      return t >= from && t < to;
    });

  const activeDays = new Set(checkins.map((e) => dayKey(e.at))).size;
  const elapsed = Math.max(1, Math.floor((now - start) / 86400000) + 1);
  const last = checkins.length ? new Date(checkins[checkins.length - 1].at).getTime() : start;

  return {
    exposed,
    activated: true,
    checkins: checkins.length,
    activeDays,
    frequency: Number((checkins.length / elapsed).toFixed(2)),
    // Un retour, c'est un point renseigne un autre jour que le premier.
    returnedAfterFirst:
      checkins.length > 1 &&
      new Set(checkins.map((e) => dayKey(e.at))).size > 1,
    d1: seenOn(days(1), days(2)),
    d7: seenOn(days(7), days(8)),
    d30: seenOn(days(30), days(31)),
    abandoned: now - last > 3 * 86400000,
  };
}
