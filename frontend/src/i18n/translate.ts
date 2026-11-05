/** Dictionaries and `translate` without React or the store, so the store can use them (no import cycle). */
import { en, type Key } from "./en";
import { es } from "./es";
import { UI_LANG, type Lang } from "./lang";
import { ru } from "./ru";

const DICTS: Record<Lang, Record<Key, string>> = { en, ru, es };

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s = DICTS[lang][key] ?? en[key] ?? key;
  for (const [k, v] of Object.entries(vars ?? {})) s = s.split(`{${k}}`).join(String(v));
  return s;
}

/** The interface language: pinned (product decision), else the user's choice, else the conversation's, else English. */
export function uiLang(manual: Lang | null, convo: Lang | null): Lang {
  return UI_LANG ?? manual ?? convo ?? "en";
}
