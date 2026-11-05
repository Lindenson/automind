/** Spec 010 T045: copy to the clipboard, with a textarea fallback where the Clipboard API is missing (plain http). */
import { useEffect, useState } from "react";
import { cx } from "../lib/util";

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* denied or not a secure context: fall back */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function CopyButton({
  text,
  label,
  copiedLabel = "copied ✓",
  className,
  ariaLabel,
}: {
  text: string;
  label: string;
  copiedLabel?: string;
  className?: string;
  ariaLabel?: string;
}) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(t);
  }, [state]);
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        void copyText(text).then((ok) => setState(ok ? "ok" : "fail"));
      }}
      className={cx(
        "rounded-md border border-line px-2 py-1 text-xs font-medium hover:bg-panel2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2",
        state === "ok" && "text-good",
        state === "fail" && "text-bad",
        className,
      )}
    >
      <span aria-live="polite">{state === "ok" ? copiedLabel : state === "fail" ? "copy failed" : label}</span>
    </button>
  );
}
