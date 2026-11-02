import { cx } from "../lib/util";

export function Logo({ small }: { small?: boolean }) {
  return (
    <div
      className={cx(
        "flex items-center justify-center rounded-xl bg-gradient-to-br from-panel2 to-panel ring-1 ring-line",
        small ? "h-8 w-8" : "h-9 w-9",
      )}
    >
      <svg
        viewBox="0 0 32 32"
        className={small ? "h-5 w-5" : "h-6 w-6"}
        aria-hidden
      >
        <path
          d="M6 21a10 10 0 0 1 20 0"
          fill="none"
          stroke="rgb(var(--accent))"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d="M16 21l6-6"
          stroke="rgb(var(--accent2))"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <circle cx="16" cy="21" r="2.5" fill="rgb(var(--fg))" />
      </svg>
    </div>
  );
}
