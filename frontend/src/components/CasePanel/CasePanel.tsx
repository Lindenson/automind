import { useLang, useT } from "../../i18n";
/**
 * The case file: what AutoMind understood about you and the cars (FR-002, FR-009).
 * Desktop: a collapsible right sidebar. Phones (<768 px): a bottom sheet.
 * Every edit is sent as PATCH. After a report it recomputes the report at once (a rescore); while a turn runs
 * the edit is queued on the server and applied when the turn ends.
 */
import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import type { Key } from "../../i18n/en";
import type { CaseCar, CaseFile } from "../../lib/protocol";
import { CarChange } from "../CarChange";
import { cx, useEscape, yearsLabel } from "../../lib/util";
import { BASIS_CLS } from "../badges";
import { patchCase, useCasePanel, type CasePatch } from "../../store/case";
import { useChat } from "../../store/chat";
import { Weights } from "./Weights";

const PERSONAS: CaseFile["persona"][] = ["UNKNOWN", "BUYER", "PERFORMANCE", "EXPERT"];
const USAGE = [
  "CITY",
  "MOTORWAY",
  "MOUNTAINS",
  "OFFROAD",
  "TRACK",
  "FAMILY",
] as const;
const DEPTHS = ["QUICK", "STANDARD", "DEEP"] as const;
const RESOLUTION: Record<string, { label: Key; cls: string }> = {
  UNRESOLVED: { label: "case.res.UNRESOLVED", cls: "text-muted border-line" },
  PROPOSED: { label: "case.res.PROPOSED", cls: "text-warn border-warn/40" },
  CONFIRMED: { label: "case.res.CONFIRMED", cls: "text-good border-good/40" },
  AUTO_OK: { label: "case.res.AUTO_OK", cls: "text-good border-good/40" },
  UNKNOWN_MODEL: { label: "case.res.UNKNOWN_MODEL", cls: "text-warn border-warn/40" },
};
const nice = (s: string) =>
  s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");

function Section({
  title,
  id,
  children,
}: {
  title: string;
  /** id of the heading, so a control can be labelled by it (`aria-labelledby`) */
  id?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-1.5">
      <h3 id={id} className="text-[11px] font-semibold uppercase tracking-wide text-muted">
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
  const rescore = useChat((s) => s.rescore);
  const [error, setError] = useState<string | null>(null);
  const t = useT();
  const personaId = useId();
  const c = cf?.data;

  const save = async (p: CasePatch) => {
    setError(await patchCase(chatId, p));
  };

  if (!c)
    return (
      <p className="text-sm text-muted">{t("case.empty")}</p>
    );
  const rates = c.rates_override as Record<string, number | null | undefined>;
  return (
    <div className="space-y-4" aria-busy={running}>
      {rescore !== "idle" && (
        <p
          role="status"
          className={cx(
            "rounded border px-2 py-1 text-xs",
            rescore === "failed"
              ? "border-bad/40 bg-bad/10 text-bad"
              : "border-accent/40 bg-accent/10",
          )}
        >
          {t(rescore === "failed" ? "panel.rescore_failed" : "panel.updating")}
        </p>
      )}
      {error && (
        <p className="rounded border border-bad/40 bg-bad/10 px-2 py-1 text-xs text-bad">
          {error}
        </p>
      )}
      <Section title={t("case.who")} id={personaId}>
        <select
          aria-labelledby={personaId}
          className="w-full rounded border border-line/70 bg-panel2 px-2 py-1.5 text-sm"
          value={c.persona}
          onChange={(e) =>
            void save({ persona: e.target.value as CaseFile["persona"] })
          }
        >
          {PERSONAS.map((p) => (
            <option key={p} value={p}>
              {t(`persona.${p}` as "persona.BUYER")}
            </option>
          ))}
        </select>
      </Section>

      <AboutYou
        profile={(c as Record<string, unknown>).profile}
        annualKm={c.annual_km}
        basis={c.basis}
        ownershipYears={c.ownership_years ?? null}
        save={save}
      />

      <Section title={t("case.cars")}>
        {c.cars.length === 0 && (
          <p className="text-sm text-muted">{t("case.none")}</p>
        )}
        {c.cars.length > 1 && (
          <p className="mb-1.5 text-xs text-muted" data-testid="compare-level">
            {t("case.level", {
              level: t(`case.level.${c.compare_level}` as "case.level.BASE"),
            })}
            {c.compare_level_source === "USER_TRIM"
              ? t("case.level.user")
              : t("case.level.default")}
          </p>
        )}
        <ul className="space-y-1.5">
          {c.cars.map((car) => (
            <CarRow key={car.key} car={car} />
          ))}
        </ul>
      </Section>

      <Section title={t("case.matters")}>
        {c.priorities.length === 0 && (
          <p className="text-sm text-muted">{t("case.noPriorities")}</p>
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
                aria-label={t("case.removePriority", { p: p.criterion })}
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
            {t("case.unmapped", { list: c.unmapped_wishes.join(", ") })}
          </p>
        )}
      </Section>

      <Section title={t("case.weights")}>
        <Weights onError={setError} />
      </Section>

      <Section title={t("case.usage")}>
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
                {t(`case.usage.${u}` as "case.usage.CITY")}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title={t("case.money")}>
        <NumberField
          label={t("case.budget")}
          unit="€"
          value={c.budget.max_eur}
          onCommit={(v) => void save({ budget: { max_eur: v } })}
        />
        <label className="flex items-center justify-between gap-2 text-sm">
          <span className="text-fg/80">{t("case.budgetFor")}</span>
          <select
            className="rounded border border-line/70 bg-panel2 px-2 py-1 text-sm"
            value={c.budget.intent ?? "UNKNOWN"}
            onChange={(e) =>
              void save({
                budget: {
                  intent: e.target.value as "NEW" | "USED" | "ANY" | "UNKNOWN",
                },
              })
            }
          >
            {(["UNKNOWN", "NEW", "USED", "ANY"] as const).map((v) => (
              <option key={v} value={v}>
                {t(`case.intent.${v}`)}
              </option>
            ))}
          </select>
        </label>
        <NumberField
          label={t("case.runningLimit")}
          unit="€/month"
          value={
            c.running_cost_limit
              ? Math.round(
                  c.running_cost_limit.period === "YEAR"
                    ? c.running_cost_limit.amount_eur / 12
                    : c.running_cost_limit.amount_eur,
                )
              : null
          }
          onCommit={(v) =>
            void save(
              v
                ? { running_cost_limit: { amount_eur: v, period: "MONTH" } }
                : { clear_running_cost_limit: true },
            )
          }
        />
        <NumberField
          label={t("case.people")}
          unit=""
          value={c.needs.passengers}
          onCommit={(v) => void save({ needs: { passengers: v } })}
        />
        <label className="flex items-center justify-between gap-2 text-sm">
          <span className="text-fg/80">{t("case.luggage")}</span>
          <select
            className="rounded border border-line/70 bg-panel2 px-2 py-1 text-sm"
            value={c.needs.luggage ?? "MEDIUM"}
            onChange={(e) =>
              void save({
                needs: { luggage: e.target.value as "LOW" | "MEDIUM" | "HIGH" },
              })
            }
          >
            {(["LOW", "MEDIUM", "HIGH"] as const).map((v) => (
              <option key={v} value={v}>
                {t(`case.luggage.${v}`)}
              </option>
            ))}
          </select>
        </label>
        <NumberField
          label={t("case.towing")}
          unit="kg"
          value={c.needs.towing_kg}
          onCommit={(v) => void save({ needs: { towing_kg: v } })}
        />
        <NumberField
          label={t("case.perYear")}
          unit="km"
          value={c.annual_km}
          onCommit={(v) => v && void save({ annual_km: v })}
        />
        <NumberField
          label={t("case.petrol")}
          unit="€/l"
          step={0.01}
          value={rates.fuel_eur_per_l}
          onCommit={(v) => void save({ rates_override: { fuel_eur_per_l: v } })}
        />
        <NumberField
          label={t("case.diesel")}
          unit="€/l"
          step={0.01}
          value={rates.diesel_eur_per_l}
          onCommit={(v) =>
            void save({ rates_override: { diesel_eur_per_l: v } })
          }
        />
        <NumberField
          label={t("case.electricity")}
          unit="€/kWh"
          step={0.01}
          value={rates.electricity_eur_per_kwh}
          onCommit={(v) =>
            void save({ rates_override: { electricity_eur_per_kwh: v } })
          }
        />
        <NumberField
          label={t("case.workshop")}
          unit="€/h"
          value={rates.labour_eur_per_h}
          onCommit={(v) =>
            void save({ rates_override: { labour_eur_per_h: v } })
          }
        />
        <p className="text-[11px] text-muted">
          {t("case.defaultRate")}
        </p>
      </Section>

      <Section title={t("case.depth")}>
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
              {t(`case.depth.${d}`)}
            </button>
          ))}
        </div>
      </Section>

      {cf.changes.length > 0 && (
        <Section title={t("case.lastChanges")}>
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

/** A car of the case: its version line and "Change" (spec 010 FR-036/FR-037). A car still to confirm or of an
 *  unknown model has its badge as the button that opens the change. */
export function CarRow({ car }: { car: CaseCar }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const focus = useCasePanel((s) => s.focus);
  const r = RESOLUTION[car.resolution] ?? RESOLUTION.UNRESOLVED!;
  const name = car.label ?? car.request_text;
  const actionable = car.resolution === "PROPOSED" || car.resolution === "UNKNOWN_MODEL";
  useEffect(() => {
    if (focus !== car.key) return;
    document.getElementById(`case-car-${car.key}`)?.scrollIntoView?.({ block: "nearest" });
    useCasePanel.setState({ focus: null });
  }, [focus, car.key]);
  const badge = cx("shrink-0 rounded border px-1 text-[10px] uppercase", r.cls);
  return (
    <li
      id={`case-car-${car.key}`}
      className="rounded border border-line/60 bg-panel2/60 px-2 py-1.5 text-sm"
      data-testid={`case-car-${car.key}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 font-medium">{name}</span>
        {actionable ? (
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${t(r.label)} — ${t("change.aria", { car: name })}`}
            onClick={() => setOpen(!open)}
            className={cx(badge, "underline decoration-dotted underline-offset-2 hover:bg-panel")}
          >
            {t(r.label)}
          </button>
        ) : (
          <span className={badge}>{t(r.label)}</span>
        )}
      </div>
      {car.variant_label && (
        <div className="text-xs text-fg/80" data-testid="case-version">
          {car.variant_label}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-1 text-xs text-muted">
        <span>
          {nice(car.condition)}
          {car.year ? ` · ~${car.year}` : ""}
          {car.mileage_km ? ` · ${car.mileage_km.toLocaleString()} km` : ""}
        </span>
      </div>
      <CarChange car={car} name={name} open={open} onOpenChange={setOpen} className="mt-1 w-full" />
    </li>
  );
}

/** Desktop sidebar (≥768 px). */
export function CaseSidebar() {
  const t = useT();
  const open = useCasePanel((s) => s.open);
  if (!open) return null;
  return (
    <aside
      className="scroll-thin hidden w-80 shrink-0 overflow-y-auto border-l border-line/60 bg-panel/40 p-4 md:block"
      aria-label={t("case.aria")}
    >
      <h2 className="mb-3 font-display text-sm font-bold">{t("case.title")}</h2>
      <CaseBody />
    </aside>
  );
}

/** Phone bottom sheet (<768 px). */
export function CaseSheet() {
  const t = useT();
  const { open, setOpen } = useCasePanel();
  const close = useCallback(() => setOpen(false), [setOpen]);
  // the sheet only shows below 768 px; Escape closes the panel at any width (audit F14)
  useEscape(open, close);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 md:hidden"
      role="dialog"
      aria-modal="true"
      aria-label={t("case.aria")}
    >
      <button
        type="button"
        aria-label={t("case.close")}
        className="absolute inset-0 bg-black/40"
        onClick={() => setOpen(false)}
      />
      <div className="scroll-thin absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t border-line/60 bg-bg p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-bold">{t("case.title")}</h2>
          <button
            type="button"
            className="text-sm text-muted"
            onClick={() => setOpen(false)}
          >
            {t("case.close")}
          </button>
        </div>
        <CaseBody />
      </div>
    </div>
  );
}

const PROFILE_OPTIONS = {
  family: ["SINGLE", "COUPLE", "FAMILY"],
  driving_style: ["CALM", "MIXED", "SPORTY"],
  home_charging: ["YES", "WORK", "NO"],
} as const;
const YEARS = [2, 3, 4, 5, 6, 8, 10, 12, 15];

function Basis({ b }: { b?: string }) {
  const t = useT();
  if (!b) return null;
  return (
    <span
      className={cx(
        "ml-1 rounded border px-1 text-[9px] uppercase",
        BASIS_CLS[b],
      )}
    >
      {t(`card.basis.${b}` as "card.basis.STATED")}
    </span>
  );
}

/** Who the user is (spec 007 FR-014): every field is editable here; an edit is a statement and, after a
 *  report, recomputes it at once. Inferred fields show the words they came from. */
function AboutYou({
  profile,
  annualKm,
  basis,
  ownershipYears,
  save,
}: {
  profile: unknown;
  annualKm: number;
  basis: Record<string, string>;
  ownershipYears: number | null;
  save: (p: CasePatch) => Promise<void> | void;
}) {
  const t = useT();
  const lang = useLang();
  const p = (profile ?? {}) as Record<string, unknown>;
  const evidence = (p.evidence ?? {}) as Record<string, string>;
  const sel = "rounded border border-line/70 bg-panel2 px-1.5 py-1 text-sm";
  return (
    <Section title={t("case.about")}>
      <div className="space-y-1.5 text-sm">
        {(Object.keys(PROFILE_OPTIONS) as (keyof typeof PROFILE_OPTIONS)[]).map(
          (k) => (
            <label
              key={k}
              className="flex flex-wrap items-center justify-between gap-x-2"
              data-testid={`profile-${k}`}
            >
              <span className="text-muted">
                {t(`profile.${k}` as "profile.family")}
                <Basis b={p[k] != null ? basis[k] : undefined} />
              </span>
              <select
                className={sel}
                value={(p[k] as string | null) ?? ""}
                onChange={(e) =>
                  void save({ profile: { [k]: e.target.value || null } })
                }
              >
                <option value="">{t("profile.unset")}</option>
                {PROFILE_OPTIONS[k].map((v) => (
                  <option key={v} value={v}>
                    {t(`profile.${k}.${v}` as "profile.family.FAMILY")}
                  </option>
                ))}
              </select>
              {evidence[k] && evidence[k] !== "set in the panel" && (
                <span className="w-full text-right text-xs text-muted">
                  “{evidence[k]}”
                </span>
              )}
            </label>
          ),
        )}
        <label
          className="flex flex-wrap items-center justify-between gap-x-2"
          data-testid="profile-ownership"
        >
          <span className="text-muted">
            {t("card.field.ownership_years")}
            <Basis b={basis.ownership_years ?? "ASSUMED"} />
          </span>
          <select
            className={sel}
            value={ownershipYears ?? 5}
            onChange={(e) =>
              void save({ ownership_years: Number(e.target.value) })
            }
          >
            {YEARS.map((n) => (
              <option key={n} value={n}>
                {yearsLabel(n, lang, t("profile.years", { n }))}
              </option>
            ))}
          </select>
        </label>
      </div>
      {typeof p.region === "string" && p.region && (
        <div
          className="mt-1 flex flex-wrap justify-between gap-x-2 text-sm"
          data-testid="profile-region"
        >
          <span className="text-muted">{t("case.region")}</span>
          <span className="text-right">
            {p.region}
            {typeof p.climate === "string" &&
              ` · ${t(`case.climate.${p.climate}` as "case.climate.HOT")}`}
          </span>
        </div>
      )}
      <p className="mt-1 text-xs text-muted">
        {typeof p.annual_km_min === "number" &&
        typeof p.annual_km_max === "number" &&
        p.annual_km_min !== p.annual_km_max
          ? t("case.kmRange", {
              min: p.annual_km_min.toLocaleString(),
              max: p.annual_km_max.toLocaleString(),
              km: annualKm.toLocaleString(),
            })
          : t("case.kmYear", { km: annualKm.toLocaleString() })}
        <Basis b={basis.annual_km ?? "ASSUMED"} />
      </p>
    </Section>
  );
}
