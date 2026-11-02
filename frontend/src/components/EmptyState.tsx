import { Logo } from "./Logo";
import { FlagIcon, TrophyIcon, WrenchIcon } from "./icons";

export const EXAMPLES = [
  {
    text: "Compare VW Golf GTI Mk8 and Hyundai i30 N for a race enthusiast.",
    hint: "Live research · drag race",
    icon: <FlagIcon />,
  },
  {
    text: "And for a smart buyer?",
    hint: "Reuses the cache · maintenance",
    icon: <WrenchIcon />,
  },
  {
    text: "Add the Tesla Model 3 Performance.",
    hint: "Researches only the new car",
    icon: <TrophyIcon />,
  },
];

export function EmptyState({
  onPick,
  disabled,
}: {
  onPick: (t: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col items-center px-2 pb-8 pt-10 text-center sm:pt-16">
      <div className="scale-125">
        <Logo />
      </div>
      <h1 className="mt-6 font-display text-3xl font-bold tracking-tight sm:text-4xl">
        Ask{" "}
        <span className="bg-gradient-to-r from-accent to-amber-400 bg-clip-text text-transparent">
          AutoMind
        </span>{" "}
        about any car
      </h1>
      <p className="mt-3 max-w-md text-sm text-muted">
        Compare cars with sourced specs, drag-race simulations and profile
        scores — every number shows where it came from and how sure we are.
      </p>
      <div className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-3">
        {EXAMPLES.map((e) => (
          <button
            key={e.text}
            type="button"
            disabled={disabled}
            onClick={() => onPick(e.text)}
            className="card group flex flex-col items-start gap-2 p-4 text-left transition hover:-translate-y-0.5 hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
              {e.icon}
            </span>
            <span className="text-sm font-medium leading-snug text-fg">
              {e.text}
            </span>
            <span className="text-[11px] text-muted">{e.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
