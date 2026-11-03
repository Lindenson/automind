/** Tiny i18n layer (spec 004 FR-024; research R12): no library, three typed dictionaries. */
import { useChat } from "../store/chat";
import { en, type Key } from "./en";
import { es } from "./es";
import { ru } from "./ru";

import { type Lang } from "./lang";
export { LANGS, asLang, storeLang, storedLang, type Lang } from "./lang";
const DICTS: Record<Lang, Record<Key, string>> = { en, ru, es };

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s = DICTS[lang][key] ?? en[key] ?? key;
  for (const [k, v] of Object.entries(vars ?? {})) s = s.replace(`{${k}}`, String(v));
  return s;
}

/** The interface language: the user's choice, else the conversation's (latest reply), else English. */
export function useLang(): Lang {
  const manual = useChat((s) => s.manualLang);
  const convo = useChat((s) => s.convoLang);
  return manual ?? convo ?? "en";
}

export function useT(): (key: Key, vars?: Record<string, string | number>) => string {
  const lang = useLang();
  return (key, vars) => translate(lang, key, vars);
}

/** A block title in the interface language (titles from the server are English). */
export function useBlockTitle(type: string, fallback: string): string {
  const t = useT();
  const key = `block.${type}` as Key;
  return key in en ? t(key) : fallback;
}
