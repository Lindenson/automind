/** Interface language helpers without React or the store (no import cycle). */
export type Lang = "en" | "ru" | "es";
export const LANGS: Lang[] = ["ru", "es", "en"];

/**
 * Product decision (spec 010 FR-042): the interface is English on every screen; assistant replies keep the
 * user's language (that is the server's job). Set this to `null` to let the interface follow the user's choice
 * or the conversation again (spec 004 FR-024): every interface string is already in the ru/es dictionaries.
 */
export const UI_LANG: Lang | null = "en";
const STORAGE_KEY = "automind.lang";

export function asLang(x: string | null | undefined): Lang | null {
  const v = (x ?? "").slice(0, 2).toLowerCase();
  return v === "ru" || v === "es" || v === "en" ? v : null;
}

/** The language the user chose by hand (kept in this browser), if any. */
export function storedLang(): Lang | null {
  try {
    return asLang(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function storeLang(lang: Lang | null): void {
  try {
    if (lang) localStorage.setItem(STORAGE_KEY, lang);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* private window: the choice lasts for this page only */
  }
}

