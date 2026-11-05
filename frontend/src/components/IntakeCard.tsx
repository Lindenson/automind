import { useState } from "react";
import { useT } from "../i18n";
import type { CardItem, ConfirmRequest, IntakeCard as Card } from "../lib/protocol";
import { cx } from "../lib/util";
import { useChat } from "../store/chat";
import { BASIS_CLS, Reveal } from "./badges";

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
        <div className="mt-1 flex flex-wrap gap-1.5">
          {it.options.map((o) => {
            // the current value is marked (audit F10); tapping it again changes nothing
            const selected = o === it.value;
            return (
              <button
                key={o}
                type="button"
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
      <p className="text-sm">{req.text}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {card.cars.map((car) => (
          <section key={car.key} className="min-w-0 rounded-lg border border-line/60 bg-panel2/60 p-2">
            <h3 className="mb-1 break-words text-sm font-semibold">{car.display_name}</h3>
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
          <h3 className="mb-1 text-sm font-semibold">{t("card.you")}</h3>
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
      <div className="flex flex-wrap gap-2">
        {req.options.map((o, i) => (
          <button
            key={o.id}
            type="button"
            onClick={() => answer(o.id)}
            className={
              i === 0
                ? "min-h-11 rounded-full bg-accent px-4 py-1.5 text-sm font-semibold text-bg hover:opacity-90"
                : "min-h-11 rounded-full border border-line/70 px-4 py-1.5 text-sm hover:border-accent/60"
            }
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">{t("card.typeToChange")}</p>
    </div>
  );
}
