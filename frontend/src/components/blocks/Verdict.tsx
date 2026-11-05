import { createContext, useContext } from "react";
import { useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum } from "../../lib/util";
import { useChat } from "../../store/chat";
import { useCarColor } from "../carColors";
import { MessageIdContext, Reveal } from "../badges";
import { ratingDomId } from "../RatingControl";

const CONF: Record<string, { cls: string }> = {
  HIGH: { cls: "border-good/40 text-good" },
  MEDIUM: { cls: "border-warn/40 text-warn" },
  LOW: { cls: "border-bad/40 text-bad" },
};

/** True when the same report has a data panel: its per-car "Find it" replaces the verdict's (audit F11). */
export const DataPanelPresent = createContext(false);

/** The verdict card: first block of every report (spec 004 FR-001). Built by code; every number is sourced. */
export function Verdict({ b, versions }: { b: BlockOf<"verdict">; /** the cars with their version lines (FR-036) */ versions?: string }) {
  const t = useT();
  const color = useCarColor();
  const conf = CONF[b.confidence] ?? CONF.MEDIUM!;
  const hasPanel = useContext(DataPanelPresent);
  return (
    <section
      aria-label={t("verdict.aria")}
      className="card animate-fadeUp space-y-3 border-accent/50 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="flex min-w-0 items-center gap-2 text-base font-semibold sm:text-lg">
          {b.pick_car_id && (
            <span
              aria-hidden
              className="inline-block h-3 w-3 shrink-0 rounded-full"
              style={{ background: color(b.pick_car_id) }}
            />
          )}
          <span className="min-w-0">{b.headline}</span>
        </h2>
        {versions && (
          <p className="order-last w-full text-xs text-muted" data-testid="verdict-for">
            {t("verdict.for", { cars: versions })}
          </p>
        )}
        <span
          className={cx(
            "shrink-0 rounded-full border px-2 py-0.5 text-xs",
            conf.cls,
          )}
        >
          {t(`verdict.conf.${b.confidence}` as "verdict.conf.HIGH")}
        </span>
      </div>
      {b.reasons.length > 0 && (
        <ul className="space-y-1 text-sm">
          {b.reasons.map((r) => (
            <li key={r.insight_id} className="flex gap-2">
              <span aria-hidden className="text-accent">
                •
              </span>
              <span className="min-w-0">{r.text}</span>
            </li>
          ))}
        </ul>
      )}
      {b.trade_off && (
        <p className="rounded-lg bg-accent/10 px-3 py-2 text-sm">
          <span className="font-medium">{t("verdict.tradeoff")}</span>
          {b.trade_off.text}
        </p>
      )}
      {b.profile_notes.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-line/50 px-3 py-2 text-sm">
          {b.profile_notes.map((n) => (
            <li key={n} className="min-w-0">
              {n}
            </li>
          ))}
        </ul>
      )}
      {(b.break_even || b.labels) && <Electrified b={b} />}
      <p className="text-xs text-muted">{b.confidence_reason}</p>
      {b.would_change && <p className="text-sm text-fg/80">{b.would_change}</p>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        {b.gaps.length > 0 && b.find && !hasPanel ? <FindIt /> : <span />}
        <RateLink />
      </div>
    </section>
  );
}

/** audit F12: the rating sits at the end of a long report; the verdict points to it. */
function RateLink() {
  const t = useT();
  const messageId = useContext(MessageIdContext);
  if (!messageId) return null;
  return (
    <button
      type="button"
      data-testid="rate-link"
      onClick={() => {
        const el = document.getElementById(ratingDomId(messageId));
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
      }}
      className="min-h-9 text-xs text-muted underline-offset-2 hover:text-fg hover:underline"
    >
      {t("verdict.rate")} <span aria-hidden>↓</span>
    </button>
  );
}

/** "Find it": research the missing key data and rebuild the report (spec 004 US1 scenario 4, US4). */
function FindIt() {
  const t = useT();
  const send = useChat((s) => s.send);
  const busy = useChat((s) => Boolean(s.pending));
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => send(t("verdict.find.text"))}
      className="min-h-11 rounded-full border border-accent/50 bg-accent/10 px-4 py-2 text-sm hover:bg-accent/20 disabled:opacity-50"
    >
      {t("verdict.find")}
    </button>
  );
}

/** Spec 006 FR-015/016: the break-even of an electrified car and the DGT labels, both computed by code. */
function Electrified({ b }: { b: BlockOf<"verdict"> }) {
  const t = useT();
  const be = b.break_even;
  const e = be?.electrified_label ?? "";
  const c = be?.against_label ?? "";
  let text: string | null = null;
  if (be?.verdict === "YEARS" && be.years !== null)
    text = t("verdict.be_years", { e, c, n: fmtNum(be.years, 1) }) + (be.beyond_ownership ? t("verdict.be_beyond") : "");
  else if (be?.verdict === "NEVER") text = t("verdict.be_never", { e, c });
  else if (be?.verdict === "ALREADY_CHEAPER") text = t("verdict.be_cheaper", { e, c });
  else if (be?.verdict === "CHEAPER_TO_BUY") text = t("verdict.be_buy", { e, c });
  const labels = Object.values(b.labels ?? {}).filter((l) => l.label !== "UNKNOWN");
  return (
    <div className="space-y-1 text-sm">
      {text && (
        <p>
          {text}{" "}
          <Reveal reason={be?.inputs.join("; ")} what={text} className="text-xs text-muted">
            {t("reason.show")}
          </Reveal>
        </p>
      )}
      {labels.length > 0 && (
        <p className="text-xs text-muted">
          {t("verdict.labels")}
          {labels.map((l) => l.rule).join("; ")}
        </p>
      )}
    </div>
  );
}
