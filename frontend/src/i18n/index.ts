/** Tiny i18n layer (spec 004 FR-024; research R12): no library, three typed dictionaries. */
import { useChat } from "../store/chat";
import { en, type Key } from "./en";
import { translate, uiLang } from "./translate";
import { type Lang } from "./lang";

export { LANGS, UI_LANG, asLang, storeLang, storedLang, type Lang } from "./lang";
export { translate, uiLang } from "./translate";

/** The interface language: English while `UI_LANG` pins it, else the user's choice, else the conversation's. */
export function useLang(): Lang {
  const manual = useChat((s) => s.manualLang);
  const convo = useChat((s) => s.convoLang);
  return uiLang(manual, convo);
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
