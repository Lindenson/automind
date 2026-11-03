/** Interface language helpers without React or the store (no import cycle). */
export type Lang = "en" | "ru" | "es";
export const LANGS: Lang[] = ["ru", "es", "en"];
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

