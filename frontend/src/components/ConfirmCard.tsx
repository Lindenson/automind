import { useT } from "../i18n";
/**
 * Confirmation before research (FR-006 variants, FR-041 cost). Buttons answer directly; a typed
 * message in the composer also answers (the hub interprets it, e.g. as a correction).
 */
import ReactMarkdown from "react-markdown";
import type { ConfirmRequest } from "../lib/protocol";
import { useChat } from "../store/chat";

export function ConfirmCard({ req }: { req: ConfirmRequest }) {
  const t = useT();
  const answer = useChat((s) => s.answerConfirm);
  const isCost = req.kind === "cost";
  // every kind except variants/cost: the options are the answers (also kinds added later)
  const isChoice = req.kind !== "cost" && req.kind !== "variants";
  return (
    <div
      className="card animate-fadeUp space-y-3 border-accent/40 p-3 sm:p-4"
      role="group"
      aria-label={isCost ? "Confirm research cost" : isChoice ? "Choose how to continue" : "Confirm variants"}
    >
      <div className="prose-sm text-sm">
        <ReactMarkdown>{req.text}</ReactMarkdown>
      </div>
      {isCost && req.estimate && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-muted">{t("confirm.estimate")}</dt>
            <dd className="tabular font-semibold">
              €{req.estimate.eur.toFixed(2)}
            </dd>
          </div>
          <div>
            <dt className="text-muted">{t("confirm.cars")}</dt>
            <dd className="tabular">{req.estimate.cars}</dd>
          </div>
          <div>
            <dt className="text-muted">{t("confirm.depth")}</dt>
            <dd>{req.estimate.depth.toLowerCase()}</dd>
          </div>
          <div>
            <dt className="text-muted">{t("confirm.areas")}</dt>
            <dd>{req.estimate.areas.join(", ")}</dd>
          </div>
        </dl>
      )}
      <div className="flex flex-wrap gap-2">
        {isCost ? (
          <>
            <button
              type="button"
              className="rounded-full bg-accent px-4 py-1.5 text-sm font-semibold text-bg hover:opacity-90"
              onClick={() => answer("run")}
            >
              Run research
            </button>
            <button
              type="button"
              className="rounded-full border border-line/70 px-4 py-1.5 text-sm hover:border-accent/60"
              onClick={() => answer("skip")}
            >
              Answer with what you have
            </button>
          </>
        ) : isChoice ? (
          req.options.map((o, i) => (
            <button
              key={o.id}
              type="button"
              onClick={() => answer(o.id)}
              className={
                i === 0
                  ? "rounded-full bg-accent px-4 py-1.5 text-sm font-semibold text-bg hover:opacity-90"
                  : "rounded-full border border-line/70 px-4 py-1.5 text-sm hover:border-accent/60"
              }
            >
              {o.label}
            </button>
          ))
        ) : (
          <>
            {req.options.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => answer(o.id)}
                className="rounded-xl border border-accent/50 bg-accent/10 px-3 py-1.5 text-left text-sm hover:bg-accent/20"
              >
                <span className="font-medium">{o.label}</span>
                {o.detail && (
                  <span className="block text-xs text-muted">{o.detail}</span>
                )}
              </button>
            ))}
            <button
              type="button"
              className="rounded-xl bg-accent px-3 py-1.5 text-sm font-semibold text-bg hover:opacity-90"
              onClick={() => answer("confirm")}
            >
              Yes, these
            </button>
          </>
        )}
      </div>
      <p className="text-xs text-muted">
        {isCost || isChoice
          ? "Or type what to change below."
          : "Something else? Type it below — e.g. “the diesel one, 2014”."}
      </p>
    </div>
  );
}
