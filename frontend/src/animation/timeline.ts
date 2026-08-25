import {
  cancelAnimation,
  runOnJS,
  withDelay,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";

import { ease } from "./ease";

/**
 * Une timeline, sur le modele de GSAP.
 *
 * ────────────────────────────────────────────────────────────────────────
 * POURQUOI. Les sequences de l'app etaient ecrites en retards empiles :
 *
 *     drop.value  = withDelay(1250, ...)
 *     draw.value  = withDelay(1350, ...)
 *     word.value  = withDelay(2020, ...)
 *
 * Chaque nombre etait calcule a la main a partir des precedents. Allonger un
 * seul temps obligeait a recalculer tous les suivants, et l'ecart passait
 * inapercu jusqu'a ce qu'on regarde l'animation image par image — c'est
 * exactement comme ça que la maree s'est retrouvee a finir sa course hors de
 * l'ecran pendant que le logo se dessinait dans le vide.
 *
 * GSAP resout ça avec le PARAMETRE DE POSITION : on place chaque etape par
 * rapport a la precedente ou a un repere nomme, et les temps absolus sont
 * deduits. Deplacer une etape deplace la suite.
 * ────────────────────────────────────────────────────────────────────────
 *
 * Les durees sont en SECONDES, comme chez GSAP, et converties en millisecondes
 * au moment d'emettre l'animation. Melanger les deux unites dans un meme
 * fichier est une source d'erreur silencieuse ; autant garder celle du
 * vocabulaire d'origine.
 */

export type Easing = (p: number) => number;

export interface TweenVars {
  /** En secondes. */
  duration?: number;
  ease?: Easing;
}

/**
 * Ou placer une etape.
 *
 *   nombre        temps absolu, en secondes
 *   "+=0.2"       0,2 s apres la FIN de la timeline
 *   "-=0.2"       0,2 s avant la fin
 *   "<"           au DEBUT de l'etape precedente
 *   "<0.2"        0,2 s apres le debut de la precedente
 *   ">"           a la FIN de la precedente (defaut)
 *   ">0.2"        0,2 s apres la fin de la precedente
 *   "repere"      a un repere pose par `label()`
 *   "repere+=0.1" 0,1 s apres ce repere
 */
export type Position = number | string;

interface Etape {
  sv: SharedValue<number>;
  depuis?: number;
  vers: number;
  debut: number;
  duree: number;
  ease: Easing;
}

export interface TimelineOptions {
  /** Herite par toutes les etapes qui ne precisent rien. */
  defaults?: TweenVars;
  /**
   * « Reduire les animations » : tout devient instantane, mais l'etat final
   * reste le meme. On ne supprime pas le contenu, on supprime le trajet.
   */
  reduced?: boolean;
}

const DEFAUTS: Required<TweenVars> = { duration: 0.5, ease: ease.out };

export function timeline(options: TimelineOptions = {}) {
  const base: Required<TweenVars> = { ...DEFAUTS, ...options.defaults };
  const reduced = !!options.reduced;

  const etapes: Etape[] = [];
  const reperes: Record<string, number> = {};
  let fin = 0;
  /** Debut et fin de la derniere etape ajoutee : ce a quoi "<" et ">" renvoient. */
  let precedent = { debut: 0, fin: 0 };

  function resoudre(pos: Position | undefined): number {
    if (pos === undefined) return precedent.fin;
    if (typeof pos === "number") return Math.max(0, pos);

    const p = pos.trim();

    // Relatif a la derniere etape ajoutee.
    if (p[0] === "<" || p[0] === ">") {
      const ancre = p[0] === "<" ? precedent.debut : precedent.fin;
      const reste = p.slice(1).trim();
      if (!reste) return ancre;
      return Math.max(0, ancre + lireDecalage(reste));
    }

    // Relatif a la fin de la timeline.
    if (p.startsWith("+=") || p.startsWith("-=")) {
      return Math.max(0, fin + lireDecalage(p));
    }

    // Repere, eventuellement decale.
    const m = p.match(/^([\w-]+)\s*([+-]=.+)?$/);
    if (m && reperes[m[1]] !== undefined) {
      return Math.max(0, reperes[m[1]] + (m[2] ? lireDecalage(m[2]) : 0));
    }

    // Position inconnue : on enchaine plutot que d'inventer un temps.
    return precedent.fin;
  }

  function lireDecalage(s: string): number {
    const t = s.trim();
    if (t.startsWith("+=")) return Number(t.slice(2)) || 0;
    if (t.startsWith("-=")) return -(Number(t.slice(2)) || 0);
    return Number(t) || 0;
  }

  function ajouter(
    sv: SharedValue<number>,
    vers: number,
    vars: TweenVars | undefined,
    pos: Position | undefined,
    depuis?: number,
  ) {
    const duree = vars?.duration ?? base.duration;
    const debut = resoudre(pos);
    etapes.push({ sv, depuis, vers, debut, duree, ease: vars?.ease ?? base.ease });
    precedent = { debut, fin: debut + duree };
    fin = Math.max(fin, precedent.fin);
    return api;
  }

  const api = {
    /** Anime jusqu'a `vers`, depuis la valeur courante. */
    to(sv: SharedValue<number>, vers: number, vars?: TweenVars, pos?: Position) {
      return ajouter(sv, vers, vars, pos);
    },

    /** Pose la valeur de depart puis anime : l'equivalent de `gsap.fromTo`. */
    fromTo(
      sv: SharedValue<number>,
      depuis: number,
      vers: number,
      vars?: TweenVars,
      pos?: Position,
    ) {
      return ajouter(sv, vers, vars, pos, depuis);
    },

    /** Pose une valeur sans transition, a une position donnee. */
    set(sv: SharedValue<number>, valeur: number, pos?: Position) {
      return ajouter(sv, valeur, { duration: 0 }, pos);
    },

    /**
     * Anime plusieurs valeurs en decale.
     *
     * `each` : ecart entre deux voisines, en secondes.
     * `amount` : duree TOTALE du decalage, repartie sur l'ensemble. Utile
     * quand le nombre d'elements varie — la sequence garde alors la meme
     * duree quel qu'en soit le nombre.
     * `from` : d'ou part la propagation.
     */
    stagger(
      svs: SharedValue<number>[],
      vers: number,
      vars: TweenVars & {
        each?: number;
        amount?: number;
        from?: "start" | "end" | "center" | "edges" | "random";
      } = {},
      pos?: Position,
    ) {
      const n = svs.length;
      if (!n) return api;
      const pas =
        vars.amount !== undefined ? (n > 1 ? vars.amount / (n - 1) : 0) : vars.each ?? 0.06;

      const rangs = ordre(n, vars.from ?? "start");
      const depart = resoudre(pos);
      let derniereFin = depart;

      svs.forEach((sv, i) => {
        const debut = depart + rangs[i] * pas;
        const duree = vars.duration ?? base.duration;
        etapes.push({ sv, vers, debut, duree, ease: vars.ease ?? base.ease });
        derniereFin = Math.max(derniereFin, debut + duree);
      });

      precedent = { debut: depart, fin: derniereFin };
      fin = Math.max(fin, derniereFin);
      return api;
    },

    /** Pose un repere nomme, pour y accrocher des etapes. */
    label(nom: string, pos?: Position) {
      reperes[nom] = pos === undefined ? fin : resoudre(pos);
      return api;
    },

    /** Duree totale, en secondes. */
    duration() {
      return fin;
    },

    /**
     * Emet toutes les animations.
     *
     * Rien ne se produit avant cet appel : la timeline se construit d'abord
     * entierement, ce qui permet a `+=`, `<` et aux reperes de se resoudre sur
     * une sequence complete.
     */
    play(onComplete?: () => void) {
      for (const e of etapes) {
        cancelAnimation(e.sv);
        if (e.depuis !== undefined) e.sv.value = e.depuis;

        if (reduced || e.duree === 0) {
          // Instantane, mais toujours a la bonne position dans la sequence :
          // un `set` place a 1,2 s reste place a 1,2 s.
          e.sv.value = reduced ? e.vers : withDelay(ms(e.debut), withTiming(e.vers, { duration: 0 }));
          continue;
        }
        e.sv.value = withDelay(
          ms(e.debut),
          withTiming(e.vers, { duration: ms(e.duree), easing: e.ease }),
        );
      }

      if (onComplete) {
        const quand = reduced ? 0 : ms(fin);
        const t = setTimeout(onComplete, quand);
        return () => clearTimeout(t);
      }
      return () => {};
    },

    /** Coupe tout ce qui est en cours, sans revenir en arriere. */
    kill() {
      for (const e of etapes) cancelAnimation(e.sv);
    },
  };

  return api;
}

function ms(secondes: number) {
  return Math.round(secondes * 1000);
}

/**
 * Rang de propagation de chaque element, en nombre de « pas ».
 *
 * `center` et `edges` ne sont pas des fantaisies : une liste qui s'ouvre
 * depuis son centre se lit comme un depliage, une liste qui s'ouvre depuis ses
 * bords comme une convergence. Le sens de propagation porte une information
 * que l'ordre seul ne porte pas.
 */
function ordre(n: number, from: "start" | "end" | "center" | "edges" | "random"): number[] {
  const rangs = new Array(n).fill(0);
  switch (from) {
    case "end":
      for (let i = 0; i < n; i++) rangs[i] = n - 1 - i;
      break;
    case "center": {
      const c = (n - 1) / 2;
      for (let i = 0; i < n; i++) rangs[i] = Math.abs(i - c);
      break;
    }
    case "edges": {
      const c = (n - 1) / 2;
      for (let i = 0; i < n; i++) rangs[i] = c - Math.abs(i - c);
      break;
    }
    case "random": {
      const melange = [...Array(n).keys()];
      for (let i = n - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [melange[i], melange[j]] = [melange[j], melange[i]];
      }
      for (let i = 0; i < n; i++) rangs[i] = melange[i];
      break;
    }
    default:
      for (let i = 0; i < n; i++) rangs[i] = i;
  }
  return rangs;
}

/** Rend `runOnJS` disponible aux appelants sans reimporter reanimated. */
export { runOnJS };
