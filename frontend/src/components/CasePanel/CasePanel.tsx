/**
 * The case file: what AutoMind understood about you and the cars (FR-002, FR-009).
 * Desktop: a collapsible right sidebar. Phones (<768 px): a bottom sheet.
 * Every edit is sent as PATCH and applies from the next message.
 */
import { useEffect, useState, type ReactNode } from "react";
import type { CaseFile } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { patchCase, useCasePanel, type CasePatch } from "../../store/case";
import { useChat } from "../../store/chat";
import { Weights } from "./Weights";

const PERSONAS: { v: CaseFile["persona"]; label: string }[] = [
  { v: "UNKNOWN", label: "Not sure yet" },
  { v: "BUYER", label: "Everyday / family buyer" },
  { v: "PERFORMANCE", label: "Performance enthusiast" },
  { v: "EXPERT", label: "Engineer / expert" },
];
const USAGE = [
  "CITY",
  "MOTORWAY",
  "MOUNTAINS",
  "OFFROAD",
  "TRACK",
  "FAMILY",
] as const;
const DEPTHS = ["QUICK", "STANDARD", "DEEP"] as const;
const RESOLUTION: Record<string, { label: string; cls: string }> = {
  UNRESOLVED: { label: "to identify", cls: "text-muted border-line" },
  PROPOSED: { label: "to confirm", cls: "text-warn border-warn/40" },
  CONFIRMED: { label: "confirmed", cls: "text-good border-good/40" },
  AUTO_OK: { label: "identified", cls: "text-good border-good/40" },
};
const nice = (s: string) =>
  s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted">
        {title}
      </h3>
      {children}
    </section>
  );
}

function NumberField(props: {
  label: string;
  value: number | null | undefined;
  unit: string;
  onCommit: (v: number | null) => void;
  step?: number;
}) {
  const [text, setText] = useState(
    props.value == null ? "" : String(props.value),
  );
  useEffect(
    () => setText(props.value == null ? "" : String(props.value)),
    [props.value],
  );
  const commit = () => {
    const v = text.trim() === "" ? null : Number(text.replace(",", "."));
    if (v === null || Number.isFinite(v)) props.onCommit(v);
  };
  return (
    <label className="flex items-center justify-between gap-2 text-sm">
      <span className="text-fg/80">{props.label}</span>
      <span className="flex items-center gap-1">
        <input
          inputMode="decimal"
          className="w-24 rounded border border-line/70 bg-panel2 px-2 py-1 text-right tabular"
          value={text}
          step={props.step}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) =>
            e.key === "Enter" && (e.target as HTMLInputElement).blur()
          }
        />
        <span className="w-10 text-xs text-muted">{props.unit}</span>
      </span>
    </label>
  );
}

export function CaseBody() {
  const chatId = useChat((s) => s.chatId);
  const cf = useChat((s) => s.caseFile);
  const running = useChat((s) => s.pending !== null);
  const [error, setError] = useState<string | null>(null);
  const c = cf?.data;

  const save = async (p: CasePatch) => {
    setError(await patchCase(chatId, p));
  };

  if (!c)
    return (
      <p className="text-sm text-muted">
        Tell me what you are looking for — I will keep track of it here.
      </p>
    );
  const rates = c.rates_override as Record<string, number | null | undefined>;
  return (
    <div
      className={cx("space-y-4", running && "pointer-events-none opacity-60")}
      aria-busy={running}
    >
      {error && (
        <p className="rounded border border-bad/40 bg-bad/10 px-2 py-1 text-xs text-bad">
          {error}
        </p>
      )}
      <Section title="Who you are">
        <select
          className="w-full rounded border border-line/70 bg-panel2 px-2 py-1.5 text-sm"
          value={c.persona}
          onChange={(e) =>
            void save({ persona: e.target.value as CaseFile["persona"] })
          }
        >
          {PERSONAS.map((p) => (
            <option key={p.v} value={p.v}>
              {p.label}
            </option>
          ))}
        </select>
      </Section>

      <Section title="Cars">
        {c.cars.length === 0 && <p className="text-sm text-muted">None yet.</p>}
        <ul className="space-y-1.5">
          {c.cars.map((car) => {
            const r = RESOLUTION[car.resolution] ?? RESOLUTION.UNRESOLVED!;
            return (
              <li
                key={car.key}
                className="rounded border border-line/60 bg-panel2/60 px-2 py-1.5 text-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 font-medium">
                    {car.label ?? car.request_text}
                  </span>
                  <span
                    className={cx(
                      "shrink-0 rounded border px-1 text-[10px] uppercase",
                      r.cls,
                    )}
                  >
                    {r.label}
                  </span>
                </div>
                <div className="text-xs text-muted">
                  {nice(car.condition)}
                  {car.year ? ` · ~${car.year}` : ""}
                  {car.mileage_km
                    ? ` · ${car.mileage_km.toLocaleString()} km`
                    : ""}
                </div>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="What matters">
        {c.priorities.length === 0 && (
          <p className="text-sm text-muted">No priorities stated.</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {c.priorities.map((p) => (
            <span
              key={p.criterion}
              className="flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-xs"
            >
              {nice(p.criterion)}{" "}
              <span className="text-muted">{p.strength.toLowerCase()}</span>
              <button
                type="button"
                aria-label={`remove ${p.criterion}`}
                className="text-muted hover:text-bad"
                onClick={() => void save({ remove_priority: p.criterion })}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        {c.unmapped_wishes.length > 0 && (
          <p className="text-xs text-muted">
            Not assessable with data: {c.unmapped_wishes.join(", ")}
          </p>
        )}
      </Section>

      <Section title="Weights">
        <Weights onError={setError} />
      </Section>

      <Section title="Usage">
        <div className="flex flex-wrap gap-1.5">
          {USAGE.map((u) => {
            const on = c.usage.includes(u);
            return (
              <button
                key={u}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  void save({
                    usage: on
                      ? c.usage.filter((x) => x !== u)
                      : [...c.usage, u],
                  })
                }
                className={cx(
                  "rounded-full border px-2 py-0.5 text-xs",
                  on
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-line/70 text-muted hover:text-fg",
                )}
              >
                {nice(u)}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Money and driving">
        <NumberField
          label="Budget"
          unit="€"
          value={c.budget.max_eur}
          onCommit={(v) => void save({ budget: { max_eur: v } })}
        />
        <NumberField
          label="Per year"
          unit="km"
          value={c.annual_km}
          onCommit={(v) => v && void save({ annual_km: v })}
        />
        <NumberField
          label="Petrol"
          unit="€/l"
          step={0.01}
          value={rates.fuel_eur_per_l}
          onCommit={(v) => void save({ rates_override: { fuel_eur_per_l: v } })}
        />
        <NumberField
          label="Diesel"
          unit="€/l"
          step={0.01}
          value={rates.diesel_eur_per_l}
          onCommit={(v) =>
            void save({ rates_override: { diesel_eur_per_l: v } })
          }
        />
        <NumberField
          label="Electricity"
          unit="€/kWh"
          step={0.01}
          value={rates.electricity_eur_per_kwh}
          onCommit={(v) =>
            void save({ rates_override: { electricity_eur_per_kwh: v } })
          }
        />
        <NumberField
          label="Workshop"
          unit="€/h"
          value={rates.labour_eur_per_h}
          onCommit={(v) =>
            void save({ rates_override: { labour_eur_per_h: v } })
          }
        />
        <p className="text-[11px] text-muted">
          Empty = default rate (shown as an assumption in costs).
        </p>
      </Section>

      <Section title="Research depth">
        <div className="grid grid-cols-3 overflow-hidden rounded border border-line/70 text-xs">
          {DEPTHS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={c.depth === d}
              onClick={() => void save({ depth: d })}
              className={cx(
                "py-1",
                c.depth === d
                  ? "bg-accent/20 text-accent"
                  : "text-muted hover:text-fg",
              )}
            >
              {nice(d)}
            </button>
          ))}
        </div>
      </Section>

      {cf.changes.length > 0 && (
        <Section title="Last changes">
          <ul className="list-inside list-disc text-xs text-muted">
            {cf.changes.slice(-4).map((ch) => (
              <li key={ch}>{ch}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

/** Desktop sidebar (≥768 px). */
export function CaseSidebar() {
  const open = useCasePanel((s) => s.open);
  if (!open) return null;
  return (
    <aside
      className="scroll-thin hidden w-80 shrink-0 overflow-y-auto border-l border-line/60 bg-panel/40 p-4 md:block"
      aria-label="Case file"
    >
      <h2 className="mb-3 font-display text-sm font-bold">Your case</h2>
      <CaseBody />
    </aside>
  );
}

/** Phone bottom sheet (<768 px). */
export function CaseSheet() {
  const { open, setOpen } = useCasePanel();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 md:hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Case file"
    >
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/40"
        onClick={() => setOpen(false)}
      />
      <div className="scroll-thin absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t border-line/60 bg-bg p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-bold">Your case</h2>
          <button
            type="button"
            className="text-sm text-muted"
            onClick={() => setOpen(false)}
          >
            Close
          </button>
        </div>
        <CaseBody />
      </div>
    </div>
  );
}
