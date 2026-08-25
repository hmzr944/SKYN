import { useEffect, useState } from "react";

import { storage } from "@/src/utils/storage";

/**
 * L'accord en genre.
 *
 * « Prête pour votre première analyse ? » sur l'ecran d'accueil : la moitie des
 * gens qui lisent ça sont au masculin, et le detail se remarque. Le français
 * n'a pas de forme neutre commode, donc soit on demande, soit on se trompe une
 * fois sur deux.
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QUE CE REGLAGE NE FAIT PAS : il ne touche PAS a l'analyse. Le moteur ne
 * lit ni le genre declare ni quoi que ce soit d'autre du profil pour compter
 * des lesions — le motif hormonal qu'il repere se deduit de la repartition des
 * lesions sur le visage, pas d'une case cochee. Demander le genre pour ensuite
 * changer un resultat medical serait une autre affaire, et ce n'est pas ce qui
 * se passe ici.
 * ────────────────────────────────────────────────────────────────────────
 *
 * La valeur reste sur l'appareil. Elle ne part sur aucun serveur : c'est une
 * preference de redaction, pas une donnee de sante.
 */

export type Genre = "f" | "m" | "n";

const KEY = "skyn_genre";

/** La forme par defaut : ni feminin ni masculin, une tournure qui evite l'accord. */
export const DEFAULT_GENRE: Genre = "n";

export async function getGenre(): Promise<Genre> {
  const v = (await storage.getItem(KEY, "")) as string;
  return v === "f" || v === "m" || v === "n" ? v : DEFAULT_GENRE;
}

export async function setGenre(g: Genre): Promise<void> {
  await storage.setItem(KEY, g);
}

/**
 * Choisit la forme qui convient.
 *
 * La variante neutre est OBLIGATOIRE : sans elle, quelqu'un qui n'a pas voulu
 * repondre recevrait quand meme un accord, choisi par defaut a sa place. C'est
 * exactement ce qu'on cherche a eviter, donc le type l'impose.
 */
export function accord(genre: Genre, formes: { f: string; m: string; n: string }): string {
  return formes[genre] ?? formes.n;
}

/** L'accord courant, relu a chaque montage. */
export function useGenre(): Genre {
  const [genre, setG] = useState<Genre>(DEFAULT_GENRE);

  useEffect(() => {
    let vivant = true;
    getGenre().then((g) => {
      if (vivant) setG(g);
    });
    return () => {
      vivant = false;
    };
  }, []);

  return genre;
}
