import { useEffect, useState } from "react";
import type { Stage } from "../lib/protocol";
import type { PendingTurn } from "../store/chat";
import { cx } from "../lib/util";
import { CheckIcon } from "./icons";

const STAGE_LABEL: Record<Stage, string> = {
  understanding: "Understand",
  asking: "Ask",
  resolving: "Resolve",
  cache: "Cache",
  researching: "Research",
  searching: "Search",
  reading: "Read",
  relevance: "Variant check",
  validating: "Validate",
  feasibility: "Fits your case?",
  followup: "Follow-up",
  estimating: "Estimate",
  computing: "Compute",
  analyzing: "Analyze",
  composing: "Compose",
  done: "Done",
};

const PIPELINE: Stage[] = [
  "understanding",
  "resolving",
  "cache",
  "researching",
  "validating",
  "analyzing",
  "composing",
];

/** v2 stages that share a slot on the rail. */
const RAIL_SLOT: Partial<Record<Stage, Stage>> = {
  asking: "understanding",
  estimating: "resolving",
  followup: "researching",
  searching: "researching",
  reading: "researching",
  relevance: "validating",
  feasibility: "analyzing",
  computing: "analyzing",
};
const slot = (st: Stage): Stage => RAIL_SLOT[st] ?? st;
const MAX_ROWS = 6;

export function StatusTimeline({ pending }: { pending: PendingTurn }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);

  const statuses = pending.statuses;
  const last = statuses[statuses.length - 1];
  const reached = new Set(statuses.map((s) => slot(s.stage)));
  const currentIdx = last ? PIPELINE.indexOf(slot(last.stage)) : -1;
  const hidden = Math.max(0, statuses.length - MAX_ROWS);
  const visible = statuses.slice(hidden);
  const elapsed = ((now - pending.startedAt) / 1000).toFixed(1);

  return (
    <div
      className="card relative animate-fadeUp overflow-hidden p-3 sm:p-4"
      aria-live="polite"
    >
      <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-line/40">
        <div className="h-full w-1/3 animate-sweep bg-gradient-to-r from-transparent via-accent to-transparent" />
      </div>

      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Spinner />
          <span>AutoMind is working</span>
        </div>
        <span className="tabular text-xs text-muted">{elapsed} s</span>
      </div>

      {/* stage rail */}
      <div className="mb-3 flex items-center gap-1 overflow-hidden">
        {PIPELINE.map((st, i) => {
          const done =
            reached.has(st) && (i < currentIdx || last?.stage === "done");
          const active = i === currentIdx && last?.stage !== "done";
          const skipped = !reached.has(st) && i < currentIdx;
          return (
            <div key={st} className="min-w-0 flex-1" title={STAGE_LABEL[st]}>
              <div
                className={cx(
                  "h-1 rounded-full transition-colors duration-500",
                  active
                    ? "animate-pulse bg-accent"
                    : done
                      ? "bg-accent/70"
                      : skipped
                        ? "bg-line/40"
                        : "bg-line/70",
                )}
              />
              <div
                className={cx(
                  "mt-1 hidden truncate text-[10px] sm:block",
                  active
                    ? "text-accent"
                    : done
                      ? "text-fg/70"
                      : "text-muted/60",
                )}
              >
                {STAGE_LABEL[st]}
              </div>
            </div>
          );
        })}
      </div>

      <ol className="space-y-1.5">
        {hidden > 0 && (
          <li className="pl-6 text-[11px] text-muted/70">
            +{hidden} earlier steps
          </li>
        )}
        {statuses.length === 0 && (
          <li className="flex items-center gap-2 text-sm text-muted">
            <span className="flex h-4 w-4 items-center justify-center">
              <span className="h-1.5 w-1.5 animate-ping rounded-full bg-accent" />
            </span>
            Sending your question…
          </li>
        )}
        {visible.map((s, i) => {
          const isLast = i === visible.length - 1 && s.stage !== "done";
          return (
            <li
              key={`${s.at}-${i}`}
              className="flex animate-fadeUp items-start gap-2 text-sm"
            >
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                {isLast ? (
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
                  </span>
                ) : (
                  <span className="text-good">
                    <CheckIcon />
                  </span>
                )}
              </span>
              <span className="w-[72px] shrink-0 text-[10px] font-semibold uppercase leading-5 tracking-wider text-muted">
                {STAGE_LABEL[s.stage]}
              </span>
              <span
                className={cx(
                  "min-w-0 break-words",
                  isLast ? "text-fg" : "text-muted",
                )}
              >
                {s.text}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin text-accent"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="3"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
