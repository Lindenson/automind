/**
 * "Change" on a car (spec 010 FR-037): the same kind of choices as the intake card — generation, engine, gearbox,
 * trim — from the case payload's options, plus "Not this car" and "Remove". Sent as a structured `car_edit`, applied
 * by code on the server (no interpretation of free text).
 */
import { useCallback, useId, useState } from "react";
import { useT } from "../i18n";
import type { Key } from "../i18n/en";
import type { CarEditField, CarOptions, CaseCar } from "../lib/protocol";
import { cx, useEscape } from "../lib/util";
import { useChat } from "../store/chat";

export const CHANGE_FIELDS = ["generation", "engine", "gearbox", "trim"] as const;
type ChoiceField = (typeof CHANGE_FIELDS)[number];

/** The choice fields that have options (in the order shown). */
export function choiceFields(options: CarOptions | null | undefined): ChoiceField[] {
  return CHANGE_FIELDS.filter((f) => (options?.[f]?.length ?? 0) > 0);
}

export function CarChange({
  car,
  name,
  open: controlled,
  onOpenChange,
  className,
}: {
  car: Pick<CaseCar, "key" | "options">;
  /** how the car is named to the user */
  name: string;
  open?: boolean;
  onOpenChange?: (v: boolean) => void;
  className?: string;
}) {
  const t = useT();
  const id = useId();
  const [own, setOwn] = useState(false);
  const open = controlled ?? own;
  const setOpen = useCallback((v: boolean) => (onOpenChange ? onOpenChange(v) : setOwn(v)), [onOpenChange]);
  const close = useCallback(() => setOpen(false), [setOpen]);
  useEscape(open, close);
  return (
    <span className={cx("inline-flex flex-col items-start", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={t("change.aria", { car: name })}
        onClick={() => setOpen(!open)}
        className="rounded-full border border-line/70 px-2 py-0.5 text-[11px] font-medium text-muted hover:border-accent/60 hover:text-accent"
      >
        {t("change.button")}
      </button>
      {open && <ChangePanel id={id} car={car} name={name} onDone={close} />}
    </span>
  );
}

function ChangePanel({
  id,
  car,
  name,
  onDone,
}: {
  id: string;
  car: Pick<CaseCar, "key" | "options">;
  name: string;
  onDone: () => void;
}) {
  const t = useT();
  const carEdit = useChat((s) => s.carEdit);
  const busy = useChat((s) => Boolean(s.pending));
  const [typing, setTyping] = useState<CarEditField | null>(null);
  const [text, setText] = useState("");
  const go = (field: CarEditField, value?: string) => {
    if (carEdit(car.key, field, value)) onDone();
  };
  const fields = choiceFields(car.options);
  const typed: CarEditField[] = ["engine", "trim", "not_this_car"];
  return (
    <div
      id={id}
      role="group"
      aria-label={t("change.aria", { car: name })}
      className="mt-1 w-full min-w-[14rem] space-y-2 rounded-lg border border-line/70 bg-panel p-2 text-xs shadow-sm"
      data-testid={`change-${car.key}`}
    >
      {fields.map((f) => (
        <div key={f}>
          <div className="mb-1 text-muted">{t(`change.field.${f}` as Key)}</div>
          <div className="flex flex-wrap gap-1.5">
            {(car.options?.[f] ?? []).map((o) => (
              <button
                key={o}
                type="button"
                disabled={busy}
                onClick={() => go(f, o)}
                className="min-h-8 rounded-full border border-line/70 px-2.5 py-0.5 hover:border-accent/60 disabled:opacity-40"
              >
                {o}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-1.5">
        {typed.map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={typing === f}
            onClick={() => {
              setTyping(typing === f ? null : f);
              setText("");
            }}
            className={cx(
              "min-h-8 rounded-full border px-2.5 py-0.5",
              typing === f ? "border-accent text-fg" : "border-line/70 text-muted hover:border-accent/60",
            )}
          >
            {f === "not_this_car"
              ? t("change.notThis")
              : t("change.other", { field: t(`change.field.${f}` as Key).toLowerCase() })}
          </button>
        ))}
        <button
          type="button"
          disabled={busy}
          onClick={() => go("remove")}
          className="min-h-8 rounded-full border border-bad/40 px-2.5 py-0.5 text-bad hover:bg-bad/10 disabled:opacity-40"
        >
          {t("change.remove")}
        </button>
      </div>
      {typing && (
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) go(typing, text);
          }}
        >
          <input
            autoFocus
            aria-label={
              typing === "not_this_car"
                ? t("change.notThis.placeholder")
                : t("change.other", { field: t(`change.field.${typing}` as Key).toLowerCase() })
            }
            placeholder={typing === "not_this_car" ? t("change.notThis.placeholder") : ""}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 120))}
            className="min-w-0 flex-1 rounded border border-line/70 bg-panel2 px-1.5 py-1"
          />
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="rounded bg-accent/15 px-2 font-medium disabled:opacity-40"
          >
            {t("change.apply")}
          </button>
        </form>
      )}
    </div>
  );
}
