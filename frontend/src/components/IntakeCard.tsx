import { useT } from "../i18n";
import type { CardItem, ConfirmRequest, IntakeCard as Card } from "../lib/protocol";
import { useChat } from "../store/chat";

/**
 * The intake confirmation card (spec 005 FR-019–FR-021): the cars as resolved, the person, the research cost.
 * Every item shows its basis; option chips edit it (applied by code); one "yes" starts the research.
 */
const BASIS_CLS: Record<CardItem["basis"], string> = {
  STATED: "border-emerald-500/50 text-emerald-300",
  INFERRED: "border-sky-500/50 text-sky-300",
  LOOKED_UP: "border-accent/50 text-accent",
  ASSUMED: "border-amber-500/50 text-amber-300",
};

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
          <span
            title={tip}
            className={`ml-1.5 rounded border px-1 align-middle text-[10px] uppercase ${BASIS_CLS[it.basis]}`}
          >
            {t(`card.basis.${it.basis}` as "card.basis.STATED")}
          </span>
        </span>
      </div>
      {it.options && it.options.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {it.options.map((o) => (
            <button
              key={o}
              type="button"
              onClick={() => edit(carKey, it.field, o)}
              className="min-h-9 rounded-full border border-line/70 px-3 py-1 text-xs hover:border-accent/60"
            >
              {o}
            </button>
          ))}
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
      <div className="grid gap-3 sm:grid-cols-2">
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
