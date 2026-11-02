import { useEffect, useState } from "react";

export function usePrefersDark(): boolean {
  const q = "(prefers-color-scheme: dark)";
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q).matches : true);
  const [dark, setDark] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return;
    const m = window.matchMedia(q);
    const on = () => setDark(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return dark;
}
