export function uuid(): string {
  try {
    if (
      typeof crypto !== "undefined" &&
      typeof crypto.randomUUID === "function"
    )
      return crypto.randomUUID();
  } catch {
    /* non-secure context */
  }
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const CHAT_KEY = "automind.chat_id";

export function loadChatId(): string {
  try {
    const v = localStorage.getItem(CHAT_KEY);
    if (v) return v;
  } catch {
    /* storage blocked */
  }
  return saveChatId(uuid());
}

export function saveChatId(id: string): string {
  try {
    localStorage.setItem(CHAT_KEY, id);
  } catch {
    /* storage blocked */
  }
  return id;
}

export function isMockMode(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("mock") === "1";
  } catch {
    return false;
  }
}

/** Distinct, colour-blind friendly-ish series colours (orange, sky, violet, lime). */
export const CAR_COLORS = [
  "#f97316",
  "#38bdf8",
  "#a78bfa",
  "#84cc16",
  "#f472b6",
] as const;

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** "8 years" in the interface language; Russian needs its three plural forms. */
export function yearsLabel(n: number, lang: string, fallback: string): string {
  if (lang !== "ru") return fallback;
  const word =
    n % 10 === 1 && n % 100 !== 11
      ? "год"
      : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)
        ? "года"
        : "лет";
  return `${n} ${word}`;
}
