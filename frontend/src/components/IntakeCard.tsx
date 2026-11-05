import { useState } from "react";
import { useT } from "../i18n";
import type { CardItem, ConfirmRequest, IntakeCard as Card } from "../lib/protocol";
import { cx } from "../lib/util";
import { useChat } from "../store/chat";
import { BASIS_CLS, Reveal } from "./badges";
import { Logo } from "./Logo";

/**
 * The intake confirmation card (spec 005 FR-019–FR-021): the cars as resolved, the person, the research cost.
 * Every item shows its basis; option chips edit it (applied by code); one "yes" starts the research.
 */

/** Fields the server can apply from typed text (application/intake_card.apply_edit): an inline edit when they have
 *  no chips (spec 010 FR-037, audit F2). */
export const TYPED_FIELDS: Record<"car" | "profile", string[]> = {
  car: ["engine", "year"],
  profile: ["annual_km"],
};

export function typedEdit(it: CardItem, carKey: string | null): boolean {
  return !(it.options && it.options.length > 0) && TYPED_FIELDS[carKey ? "car" : "profile"].includes(it.field);
}

function InlineEdit({ it, carKey, label }: { it: CardItem; carKey: string | null; label: string }) {
  const t = useT();
  const edit = useChat((s) => s.editIntake);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open)
    return (
      <button
        type="button"
        aria-label={t("card.edit.aria", { field: label })}
        onClick={() => {
          setText(it.field === "annual_km" ? it.value.replace(/[^\d]/g, "") : it.value);
          setOpen(true);
        }}
        className="ml-1.5 text-[11px] text-accent underline-offset-2 hover:underline"
      >
        {t("card.edit")}
      </button>
    );
  return (
    <form
      className="mt-1 flex gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && text.trim() !== it.value) edit(carKey, it.field, text.trim());
        setOpen(false);
      }}
    >
      <input
        autoFocus
        aria-label={t("card.edit.aria", { field: label })}
        inputMode={it.field === "engine" ? "text" : "numeric"}
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, 80))}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="min-w-0 flex-1 rounded border border-line/70 bg-panel2 px-1.5 py-1 text-sm"
      />
      <button type="submit" className="rounded bg-accent/15 px-2 text-xs font-medium">
        {t("card.edit.save")}
      </button>
    </form>
  );
}

function Row({ it, carKey }: { it: CardItem; carKey: string | null }) {
  const t = useT();
  const edit = useChat((s) => s.editIntake);
  const label = t(`card.field.${it.field}` as "card.field.engine");
  const tip = it.evidence ? `“${it.evidence}”` : it.source?.name ?? undefined;
  return (
    <div
      className={`rounded px-2 py-1 ${it.changed ? "bg-accent/15 ring-1 ring-accent/40" : ""}`}
      data-testid={`card-${carKey ?? "profile"}-${it.field}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-xs text-muted">{label}</span>
        <span className="min-w-0 text-right text-sm">
          {it.changed && it.before && <s className="mr-1 text-muted">{it.before}</s>}
          {it.source?.url ? (
            <a href={it.source.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              {it.value}
            </a>
          ) : (
            it.value
          )}
          <Reveal
            reason={tip}
            what={label}
            className={`ml-1.5 rounded border px-1 align-middle text-[10px] uppercase ${BASIS_CLS[it.basis]}`}
          >
            {t(`card.basis.${it.basis}` as "card.basis.STATED")}
          </Reveal>
          {typedEdit(it, carKey) && <InlineEdit it={it} carKey={carKey} label={label} />}
        </span>
      </div>
      {it.options && it.options.length > 0 && (
        // audit F10: the chips say what they change; they edit this one line, they do not confirm the card
        <div className="mt-1 flex flex-wrap items-center gap-1.5" role="group" aria-label={t("card.changeTo", { field: label })}>
          <span className="text-[11px] text-muted" aria-hidden>
            {t("card.changeTo", { field: label.toLowerCase() })}
          </span>
          {it.options.map((o) => {
            // the current value is marked (audit F10); tapping it again changes nothing
            const selected = o === it.value;
            return (
              <button
                key={o}
                type="button"
                aria-label={
                  selected
                    ? t("card.option.current", { field: label, option: o })
                    : t("card.option.aria", { field: label.toLowerCase(), option: o })
                }
                aria-pressed={selected}
                onClick={() => !selected && edit(carKey, it.field, o)}
                className={cx(
                  "min-h-9 rounded-full border px-3 py-1 text-xs",
                  selected
                    ? "border-accent bg-accent/15 font-semibold text-fg"
                    : "border-line/70 hover:border-accent/60",
                )}
              >
                {selected && <span aria-hidden>✓ </span>}
                {o}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function IntakeCard({ req, card }: { req: ConfirmRequest; card: Card }) {
  const t = useT();
  const answer = useChat((s) => s.answerConfirm);
  return (
    <div className="card animate-fadeUp space-y-3 border-accent/40 p-3 sm:p-4" role="group" aria-label={t("card.title")}>
      {/* audit F10: the card is part of the dialogue — it comes from AutoMind like any other reply */}
      <div className="flex items-center gap-2 text-xs text-muted" data-testid="card-from">
        <Logo small />
        <span className="font-display font-semibold text-fg">AutoMind</span>
        <span>{t("card.asks")}</span>
      </div>
      <p className="text-sm">{req.text}</p>
      <p className="text-xs text-muted">{t("card.check")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {card.cars.map((car) => (
          <section key={car.key} className="min-w-0 rounded-lg border border-line/60 bg-panel2/60 p-2">
            <h2 className="mb-1 break-words text-sm font-semibold">{car.display_name}</h2>
            <div className="space-y-0.5">
              {car.items.map((it) => (
                <Row key={it.field} it={it} carKey={car.key} />
              ))}
            </div>
          </section>
        ))}
      </div>
      {card.profile.length > 0 && (
        <section className="rounded-lg border border-line/60 p-2">
          <h2 className="mb-1 text-sm font-semibold">{t("card.you")}</h2>
          {card.profile.map((it) => (
            <Row key={it.field} it={it} carKey={null} />
          ))}
        </section>
      )}
      {req.estimate && (
        <p className="text-xs text-muted" data-testid="card-cost">
          {t("card.cost", { eur: req.estimate.eur.toFixed(2), areas: req.estimate.areas.join(", ") })}
        </p>
      )}
      {/* audit F10: confirming is separate from editing — one primary action, the others say what they do */}
      <div className="space-y-2 border-t border-line/50 pt-3" data-testid="card-actions">
        <p className="text-sm font-medium">{t("card.ready")}</p>
        <div className="flex flex-wrap gap-2">
          {req.options.map((o, i) => (
            <button
              key={o.id}
              type="button"
              onClick={() => answer(o.id)}
              data-primary={i === 0 || undefined}
              className={
                i === 0
                  ? "min-h-11 rounded-full bg-accent-solid px-5 py-1.5 text-sm font-semibold text-on-accent shadow hover:opacity-90"
                  : "min-h-11 rounded-full px-3 py-1.5 text-sm text-muted underline-offset-2 hover:text-fg hover:underline"
              }
            >
              {o.label}
            </button>
          ))}
        </div>
        {req.options
          .filter((o) => SKIP_IDS.has(o.id))
          .map((o) => (
            <p key={o.id} className="text-xs text-muted" data-testid="card-skip-note">
              {t("card.stop.note", { label: o.label })}
            </p>
          ))}
        <p className="text-xs text-muted">{t("card.typeToChange")}</p>
      </div>
    </div>
  );
}

/** Answers that decline the research (orchestration/nodes/confirm.py): their consequence is spelled out. */
const SKIP_IDS = new Set(["stop", "skip"]);
