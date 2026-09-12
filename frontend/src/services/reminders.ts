/**
 * Les rappels de routine.
 *
 * Une routine ne marche que si elle est faite. Un actif se juge sur huit a
 * douze semaines : ce qui fait echouer une routine, ce n'est presque jamais le
 * mauvais produit, c'est les soirs ou on oublie.
 *
 * Deux rappels quotidiens, matin et soir, programmes localement — aucun serveur
 * de notifications, donc rien qui parte de l'appareil. Chacun peut etre coupe
 * separement : quelqu'un qui n'oublie jamais son matin n'a pas besoin qu'on
 * l'y reprenne.
 */
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { storage } from "@/src/utils/storage";

const K_PREFS = "skyn_reminders";

/**
 * Identifiants stables.
 *
 * Sans eux, reprogrammer les rappels de routine effacerait aussi celui du
 * suivi d'introduction : `cancelAllScheduledNotificationsAsync` ne fait pas
 * le tri. Chaque rappel s'annule donc individuellement.
 */
const ID_AM = "skyn-routine-am";
const ID_PM = "skyn-routine-pm";
const ID_INTRO = "skyn-introduction";
const ID_PHASE_J7 = "skyn-phase-j7";
const ID_PHASE_J14 = "skyn-phase-j14";
const ID_PHASE_J30 = "skyn-phase-j30";
const PHASE_CHECKPOINT_IDS = [ID_PHASE_J7, ID_PHASE_J14, ID_PHASE_J30];

export interface ReminderPrefs {
  am: boolean;
  pm: boolean;
  /** Heures locales, 0-23. */
  amHour: number;
  amMinute: number;
  pmHour: number;
  pmMinute: number;
}

export const DEFAULT_PREFS: ReminderPrefs = {
  am: false,
  pm: false,
  amHour: 8,
  amMinute: 0,
  pmHour: 21,
  pmMinute: 30,
};

/** Le web n'a pas de notification programmee utilisable ici. */
const SUPPORTED = Platform.OS === "ios" || Platform.OS === "android";

// Pose du gestionnaire a l'import, mais seulement la ou les notifications
// existent : sur le web, ce module est charge par le bundle et ne doit rien
// casser au demarrage.
if (SUPPORTED) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

export async function getPrefs(): Promise<ReminderPrefs> {
  const raw = (await storage.getItem(K_PREFS, "")) as string;
  if (!raw) return DEFAULT_PREFS;
  try {
    return { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<ReminderPrefs>) };
  } catch {
    return DEFAULT_PREFS;
  }
}

async function ensureAndroidChannel() {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync("routine", {
    name: "Routine",
    importance: Notifications.AndroidImportance.DEFAULT,
    sound: null,
    vibrationPattern: [0, 180],
  });
}

/** Demande l'autorisation. Renvoie false si l'utilisateur refuse. */
export async function requestPermission(): Promise<boolean> {
  if (!SUPPORTED) return false;
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  // On ne redemande pas si le systeme a ferme la porte : il faut passer par
  // les reglages, et une deuxieme demande ne montrerait rien du tout.
  if (!current.canAskAgain) return false;
  const asked = await Notifications.requestPermissionsAsync();
  return asked.granted;
}

const AM_COPY = {
  title: "Routine du matin",
  body: "Nettoyant, soin, protection solaire. Trois minutes.",
};
const PM_COPY = {
  title: "Routine du soir",
  body: "C'est le moment qui compte le plus : la peau repare la nuit.",
};

/**
 * Réapplique les préférences : annule tout, puis reprogramme ce qui est actif.
 *
 * On repart systematiquement d'une table rase — reprogrammer par-dessus
 * l'existant est le moyen le plus sur d'empiler deux rappels du soir.
 */
export async function applyPrefs(prefs: ReminderPrefs): Promise<ReminderPrefs> {
  await storage.setItem(K_PREFS, JSON.stringify(prefs));
  if (!SUPPORTED) return prefs;

  // On n'annule que les deux rappels de routine : celui du suivi vit sa
  // propre vie et ne doit pas disparaitre quand on touche a ces reglages.
  await cancel(ID_AM);
  await cancel(ID_PM);
  if (!prefs.am && !prefs.pm) return prefs;

  const granted = await requestPermission();
  if (!granted) {
    const off = { ...prefs, am: false, pm: false };
    await storage.setItem(K_PREFS, JSON.stringify(off));
    return off;
  }

  await ensureAndroidChannel();

  const daily = (hour: number, minute: number) =>
    ({
      type: Notifications.SchedulableTriggerInputTypes.DAILY,
      hour,
      minute,
      channelId: "routine",
    }) as Notifications.DailyTriggerInput;

  if (prefs.am) {
    await Notifications.scheduleNotificationAsync({
      identifier: ID_AM,
      content: { ...AM_COPY },
      trigger: daily(prefs.amHour, prefs.amMinute),
    });
  }
  if (prefs.pm) {
    await Notifications.scheduleNotificationAsync({
      identifier: ID_PM,
      content: { ...PM_COPY },
      trigger: daily(prefs.pmHour, prefs.pmMinute),
    });
  }
  return prefs;
}

async function cancel(id: string): Promise<void> {
  try {
    await Notifications.cancelScheduledNotificationAsync(id);
  } catch {
    // Rien de programme sous cet identifiant : c'est le cas normal au premier
    // passage, pas une erreur.
  }
}

/**
 * Le rappel du suivi d'introduction.
 *
 * C'est le declencheur de la boucle : sans lui, revenir chaque jour repose
 * uniquement sur la bonne volonte. Il se programme a l'ouverture d'un suivi et
 * s'annule a sa fermeture — l'utilisateur n'a rien a regler, parce qu'un
 * reglage de plus serait un abandon de plus.
 *
 * Il tombe en soiree : c'est au demaquillage qu'on regarde vraiment sa peau,
 * et c'est le moment ou le point du jour est le plus fiable.
 */
export async function scheduleIntroReminder(productName: string): Promise<boolean> {
  if (!SUPPORTED) return false;
  await cancel(ID_INTRO);

  const granted = await requestPermission();
  if (!granted) return false;

  await ensureAndroidChannel();
  await Notifications.scheduleNotificationAsync({
    identifier: ID_INTRO,
    content: {
      title: "Votre point du jour",
      // Nommer le produit ancre le rappel dans quelque chose de concret :
      // "comment va ta peau" est trop vague pour declencher une action.
      body: `Comment votre peau réagit-elle à ${productName} aujourd'hui ?`,
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DAILY,
      hour: 21,
      minute: 0,
      channelId: "routine",
    } as Notifications.DailyTriggerInput,
  });
  return true;
}

export async function cancelIntroReminder(): Promise<void> {
  if (!SUPPORTED) return;
  await cancel(ID_INTRO);
}

/**
 * Les trois rendez-vous d'une Phase de traitement — J+7, J+14, J+30.
 *
 * A la différence du rappel d'introduction (quotidien, un point subjectif
 * du jour), ceux-ci sont ponctuels et disent explicitement CE QUE la
 * comparaison peut montrer maintenant, pas juste "n'oubliez pas de
 * scanner". Le nom du traitement n'ancre que le premier — les deux
 * suivants parlent de la Phase elle-même, une fois le contexte déjà posé.
 *
 * Programmés en soirée comme le reste des rappels de peau (voir
 * `scheduleIntroReminder`), à une heure distincte pour ne pas s'empiler
 * avec eux si tous sont actifs en même temps.
 *
 * Limite connue, assumée : si la Phase se termine autrement qu'en
 * commençant un nouveau traitement (un changement de routine ordinaire,
 * par exemple), ces trois rappels ne sont pas annulés pour autant — ils
 * sont peu nombreux et espacés de plusieurs jours, et le pire cas est un
 * rappel qui arrive pour une Phase déjà close, pas un rappel qui
 * n'arrive jamais. Démarrer un NOUVEAU traitement, en revanche, annule et
 * remplace toujours les trois précédents (mêmes identifiants stables).
 */
const CHECKPOINT_HOUR = 20;

/** Les trois échéances d'une Phase de traitement — partagé avec l'affichage
 * du prochain rendez-vous (phase-summary.tsx, dashboard.tsx), pour ne
 * jamais faire dériver la date montrée à l'écran de celle du rappel
 * effectivement programmé. */
export const PHASE_CHECKPOINT_DAYS = [7, 14, 30] as const;

export function checkpointDate(start: Date, daysAfter: number): Date {
  const d = new Date(start);
  d.setDate(d.getDate() + daysAfter);
  d.setHours(CHECKPOINT_HOUR, 0, 0, 0);
  return d;
}

export async function scheduleTreatmentCheckpoints(
  treatmentName: string,
  startedAt: Date = new Date()
): Promise<boolean> {
  if (!SUPPORTED) return false;
  for (const id of PHASE_CHECKPOINT_IDS) await cancel(id);

  const granted = await requestPermission();
  if (!granted) return false;
  await ensureAndroidChannel();

  const checkpoints = [
    {
      id: ID_PHASE_J7,
      at: checkpointDate(startedAt, 7),
      title: "7 jours dans cette Phase",
      body: `${treatmentName} : votre peau a maintenant un premier point de comparaison. Faites le scan.`,
    },
    {
      id: ID_PHASE_J14,
      at: checkpointDate(startedAt, 14),
      title: "Deux semaines déjà",
      body: "Comparez votre peau aujourd'hui avec le début de cette Phase.",
    },
    {
      id: ID_PHASE_J30,
      at: checkpointDate(startedAt, 30),
      title: "30 jours dans cette Phase",
      body: "Voici ce que SKYN peut maintenant comparer. Faites le scan pour votre bilan.",
    },
  ];

  const now = Date.now();
  for (const c of checkpoints) {
    // Ne programme jamais dans le passe — defensif seulement : avec
    // `startedAt` par defaut a maintenant, les trois echeances tombent
    // toujours dans le futur.
    if (c.at.getTime() <= now) continue;
    await Notifications.scheduleNotificationAsync({
      identifier: c.id,
      content: {
        title: c.title,
        body: c.body,
        // Lu par le listener pose dans app/_layout.tsx : taper la
        // notification doit ouvrir directement le scan guide, pas juste
        // ramener sur l'app a l'endroit ou elle en etait.
        data: { kind: "phase-checkpoint" },
      },
      trigger: {
        type: Notifications.SchedulableTriggerInputTypes.DATE,
        date: c.at,
        channelId: "routine",
      } as Notifications.DateTriggerInput,
    });
  }
  return true;
}

export async function cancelTreatmentCheckpoints(): Promise<void> {
  if (!SUPPORTED) return;
  for (const id of PHASE_CHECKPOINT_IDS) await cancel(id);
}

export function formatTime(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

/** Avance l'heure d'un rappel par pas de trente minutes, en bouclant sur 24 h. */
export function bumpTime(hour: number, minute: number) {
  const total = (hour * 60 + minute + 30) % (24 * 60);
  return { hour: Math.floor(total / 60), minute: total % 60 };
}

export const remindersSupported = SUPPORTED;
