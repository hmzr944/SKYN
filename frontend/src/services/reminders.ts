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

  await Notifications.cancelAllScheduledNotificationsAsync();
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
      content: { ...AM_COPY },
      trigger: daily(prefs.amHour, prefs.amMinute),
    });
  }
  if (prefs.pm) {
    await Notifications.scheduleNotificationAsync({
      content: { ...PM_COPY },
      trigger: daily(prefs.pmHour, prefs.pmMinute),
    });
  }
  return prefs;
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
