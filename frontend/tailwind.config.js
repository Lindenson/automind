/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        panel2: "rgb(var(--panel2) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        accent2: "rgb(var(--accent2) / <alpha-value>)",
        "accent-solid": "rgb(var(--accent-solid) / <alpha-value>)",
        "on-accent": "rgb(var(--on-accent) / <alpha-value>)",
        good: "rgb(var(--good) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        bad: "rgb(var(--bad) / <alpha-value>)",
        prov: {
          claim: "rgb(var(--prov-claim) / <alpha-value>)",
          measured: "rgb(var(--prov-measured) / <alpha-value>)",
          sourced: "rgb(var(--prov-sourced) / <alpha-value>)",
          derived: "rgb(var(--prov-derived) / <alpha-value>)",
          simulated: "rgb(var(--prov-simulated) / <alpha-value>)",
          assumption: "rgb(var(--prov-assumption) / <alpha-value>)",
        },
        basis: {
          stated: "rgb(var(--basis-stated) / <alpha-value>)",
          inferred: "rgb(var(--basis-inferred) / <alpha-value>)",
          found: "rgb(var(--basis-found) / <alpha-value>)",
          assumed: "rgb(var(--basis-assumed) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["'Space Grotesk'", "Inter", "ui-sans-serif", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      keyframes: {
        fadeUp: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "none" } },
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(250%)" } },
      },
      animation: {
        fadeUp: "fadeUp .35s ease-out both",
        sweep: "sweep 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
