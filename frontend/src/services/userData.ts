import AsyncStorage from "@react-native-async-storage/async-storage";

/**
 * Les donnees de l'utilisateur, et ce qu'on peut en faire.
 *
 * Une app qui lit un visage et tient un journal de peau doit pouvoir rendre
 * ces donnees et les effacer pour de bon. Ce n'est pas une case a cocher de
 * conformite : quelqu'un qui note ses poussees pendant trois mois doit pouvoir
 * partir avec, ou tout supprimer sans nous croire sur parole.
 *
 * Tout vit sur l'appareil. Il n'y a donc rien a demander a un serveur — ce qui
 * rend la suppression immediate et verifiable.
 */

/** Toutes nos cles portent ce prefixe : c'est ce qui rend l'effacement sur. */
const PREFIX = "skyn_";

export interface DataSummary {
  scans: number;
  joursDeJournal: number;
  suivis: number;
  /** Taille approximative occupee, en kilo-octets. */
  poidsKo: number;
}

async function ourKeys(): Promise<string[]> {
  try {
    const all = await AsyncStorage.getAllKeys();
    return all.filter((k) => k.startsWith(PREFIX));
  } catch {
    return [];
  }
}

function count(raw: string | null, kind: "array" | "object"): number {
  if (!raw) return 0;
  try {
    // Le stockage encode deux fois : une chaine JSON dans une chaine JSON.
    const once = JSON.parse(raw);
    const val = typeof once === "string" ? JSON.parse(once) : once;
    if (kind === "array") return Array.isArray(val) ? val.length : 0;
    return val && typeof val === "object" ? Object.keys(val).length : 0;
  } catch {
    return 0;
  }
}

export async function summarize(): Promise<DataSummary> {
  const keys = await ourKeys();
  let poids = 0;
  let scans = 0;
  let jours = 0;
  let suivis = 0;

  try {
    const pairs = await AsyncStorage.multiGet(keys);
    for (const [k, v] of pairs) {
      poids += (v?.length ?? 0) + k.length;
      if (k === `${PREFIX}scans_index`) scans = count(v, "array");
      else if (k === `${PREFIX}journal`) jours = count(v, "object");
      else if (k === `${PREFIX}introductions`) suivis = count(v, "array");
    }
  } catch {
    /* on rend ce qu'on a pu lire */
  }

  return {
    scans,
    joursDeJournal: jours,
    suivis,
    poidsKo: Math.round(poids / 1024),
  };
}

/**
 * Rassemble les donnees dans un objet lisible.
 *
 * On retire les photos : elles pesent lourd, ne sont conservees que le temps
 * d'une analyse, et n'ont pas leur place dans un export destine a etre lu ou
 * transmis a un professionnel.
 */
export async function exportAll(): Promise<string> {
  const keys = (await ourKeys()).filter(
    (k) => !k.includes("capture") && !k.startsWith(`${PREFIX}scan_full_`),
  );
  const out: Record<string, unknown> = {};

  try {
    const pairs = await AsyncStorage.multiGet(keys);
    for (const [k, v] of pairs) {
      if (v == null) continue;
      try {
        const once = JSON.parse(v);
        out[k] = typeof once === "string" ? JSON.parse(once) : once;
      } catch {
        out[k] = v;
      }
    }
  } catch {
    /* export partiel plutot que rien */
  }

  return JSON.stringify(
    { app: "SKYN", exporte_le: new Date().toISOString(), donnees: out },
    null,
    2,
  );
}

/**
 * Efface tout ce que l'app a stocke.
 *
 * On enumere les cles au lieu d'appeler `clear()` : le stockage est partage
 * avec la session d'authentification et d'autres bibliotheques, et un effacement
 * global deconnecterait sans prevenir.
 */
export async function eraseAll(): Promise<number> {
  const keys = await ourKeys();
  if (!keys.length) return 0;
  try {
    await AsyncStorage.multiRemove(keys);
    return keys.length;
  } catch {
    return 0;
  }
}
