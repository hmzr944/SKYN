import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { storage } from "@/src/utils/storage";
import fr, { type Dictionary } from "@/src/i18n/locales/fr";
import en from "@/src/i18n/locales/en";

export type Locale = "fr" | "en";
const LOCALE_KEY = "skyn_locale";
const DICTIONARIES: Record<Locale, Dictionary> = { fr, en };

/** Chemin en points vers une clé imbriquée du dictionnaire, ex. "settings.title". */
type DotPath<T, Prefix extends string = ""> = T extends string
  ? Prefix extends `${infer P}.`
    ? P
    : never
  : { [K in keyof T & string]: DotPath<T[K], `${Prefix}${K}.`> }[keyof T & string];

export type TranslationKey = DotPath<Dictionary>;

function lookup(dict: Dictionary, path: string): string | undefined {
  const parts = path.split(".");
  let node: unknown = dict;
  for (const p of parts) {
    if (node == null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[p];
  }
  return typeof node === "string" ? node : undefined;
}

function interpolate(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

type Ctx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  /** Traduit une clé "section.cle" ; retombe sur le français si absente de
   * la langue courante, puis sur la clé elle-meme si absente des deux (un
   * oubli reste visible au lieu de planter l'ecran). */
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
};

const LocaleContext = createContext<Ctx | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("fr");

  useEffect(() => {
    storage.getItem(LOCALE_KEY, "fr" as Locale).then((v) => {
      if (v === "en" || v === "fr") setLocaleState(v);
    });
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    storage.setItem(LOCALE_KEY, l);
  }, []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const value =
        lookup(DICTIONARIES[locale], key) ?? lookup(DICTIONARIES.fr, key) ?? key;
      return interpolate(value, vars);
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useTranslation(): Ctx {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useTranslation() doit être appelé sous LocaleProvider");
  return ctx;
}
