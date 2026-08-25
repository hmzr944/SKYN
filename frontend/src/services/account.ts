import { supabase } from "@/src/services/supabase";
import { eraseAll } from "@/src/services/userData";

/**
 * La suppression de compte.
 *
 * Elle manquait, et les reglages affirmaient pourtant que « la suppression
 * efface tout, immediatement ». C'etait faux : l'effacement ne touchait que le
 * stockage local, alors que l'app ecrit aussi les scores dans Supabase.
 *
 * Deux raisons de la faire, et la premiere n'est pas la conformite :
 * quelqu'un qui confie l'etat de sa peau doit pouvoir le reprendre. La seconde
 * est qu'Apple refuse depuis 2022 toute app permettant de creer un compte sans
 * permettre de le supprimer depuis l'app (regle 5.1.1 v).
 *
 * ────────────────────────────────────────────────────────────────────────
 * CE QUI SE PASSE COTE SERVEUR
 *
 * Les lignes de donnees s'effacent avec la cle publique, a condition qu'une
 * policy DELETE existe. Le COMPTE d'authentification, lui, ne peut pas
 * l'etre : cela demande la cle de service, qui n'a rien a faire dans une
 * application. Le passage oblige est une fonction SQL en `security definer`,
 * a creer une fois dans Supabase :
 *
 *   create or replace function public.delete_account()
 *   returns void language plpgsql security definer set search_path = '' as $$
 *   begin
 *     delete from public.skyn_reports where user_id = auth.uid()::text;
 *     delete from auth.users where id = auth.uid();
 *   end; $$;
 *   revoke all on function public.delete_account() from public;
 *   grant execute on function public.delete_account() to authenticated;
 *
 * Tant qu'elle n'existe pas, cette fonction rend `compte: "impossible"` et
 * l'interface le DIT. Elle ne pretend jamais avoir supprime plus qu'elle n'a
 * supprime — c'est tout l'interet d'avoir un resultat detaille plutot qu'un
 * booleen.
 * ────────────────────────────────────────────────────────────────────────
 */

export interface DeletionResult {
  /** Nombre de cles effacees sur l'appareil. */
  local: number;
  /** Les analyses sauvegardees en ligne. */
  donnees: "supprimees" | "echec" | "sans_objet";
  /** Le compte d'authentification lui-meme. */
  compte: "supprime" | "impossible" | "sans_objet";
}

/** Efface tout ce qui existe, ici et en ligne, et rend le detail de ce qui a marche. */
export async function deleteAccount(userId: string | null): Promise<DeletionResult> {
  const distant = !!userId && userId !== "guest";
  const res: DeletionResult = {
    local: 0,
    donnees: distant ? "echec" : "sans_objet",
    compte: distant ? "impossible" : "sans_objet",
  };

  if (distant) {
    // La fonction efface les lignes ET le compte : c'est le chemin normal.
    try {
      const { error } = await supabase.rpc("delete_account");
      if (!error) {
        res.donnees = "supprimees";
        res.compte = "supprime";
      }
    } catch {
      /* on tente le repli ci-dessous */
    }

    // Repli : au moins retirer les donnees, meme si le compte survit. Mieux
    // vaut un compte vide qu'un compte plein qu'on croyait supprime.
    if (res.donnees !== "supprimees") {
      try {
        const { error } = await supabase
          .from("skyn_reports")
          .delete()
          .eq("user_id", userId);
        if (!error) res.donnees = "supprimees";
      } catch {
        /* res.donnees reste "echec" */
      }
    }
  }

  // Le local en dernier : si le reseau echoue, on garde de quoi reessayer.
  res.local = await eraseAll();
  try {
    await supabase.auth.signOut();
  } catch {
    /* la session locale part avec le reste */
  }
  return res;
}

/** Ce qu'on affiche apres coup. Decrit ce qui s'est passe, jamais mieux. */
export function deletionMessage(r: DeletionResult): string {
  const local = `${r.local} entrée${r.local > 1 ? "s" : ""} effacée${r.local > 1 ? "s" : ""} sur cet appareil.`;
  if (r.compte === "supprime") return `Compte supprimé. ${local}`;
  if (r.compte === "sans_objet") return local;
  if (r.donnees === "supprimees") {
    return (
      `${local} Vos analyses en ligne ont été supprimées, mais le compte lui-même ` +
      `n'a pas pu être fermé. Écrivez-nous et nous le fermerons.`
    );
  }
  return (
    `${local} La suppression en ligne n'a pas abouti — vérifiez votre connexion ` +
    `et réessayez.`
  );
}
