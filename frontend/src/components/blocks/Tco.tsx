import { useBlockTitle, useLang, useT } from "../../i18n";
/**
 * Ownership cost (FR-033..FR-035): annual and 5-year totals per car, a stacked bar by item, every item
 * labelled SOURCED or ASSUMPTION with its inputs. For used cars the repair reserve is shown in two
 * parts: documented big-ticket items and the base reserve.
 */
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum, yearsLabel } from "../../lib/util";
import {
  AssumptionBadge,
  BlockCard,
  ProvenanceBadge,
  SourcesButton,
} from "../badges";
import { useCarColor } from "../carColors";
import { WrenchIcon } from "../icons";

type Car = BlockOf<"tco">["cars"][number];
type Item = Car["items"][number];

const KIND_ORDER = [
  "MAINTENANCE",
  "ENERGY",
  "TYRES",
  "ROAD_TAX",
  "BIG_TICKET",
  "BASE_RESERVE",
] as const;
const KIND_LABEL: Record<Item["kind"], string> = {
  MAINTENANCE: "Maintenance",
  ENERGY: "Energy",
  TYRES: "Tyres",
  ROAD_TAX: "Road tax",
  BIG_TICKET: "Due repairs",
  BASE_RESERVE: "Base reserve",
  DEPRECIATION: "Depreciation",
};
const OPACITY: Record<Item["kind"], number> = {
  MAINTENANCE: 1,
  ENERGY: 0.78,
  TYRES: 0.6,
  ROAD_TAX: 0.45,
  BIG_TICKET: 0.34,
  BASE_RESERVE: 0.24,
  DEPRECIATION: 0,
};
const eur = (v: number | null) => (v === null ? "—" : `€${fmtNum(v, 0)}`);

/** Spec 006 FR-020: the energy line split into electricity and fuel. */
function Split({ parts }: { parts: NonNullable<Item["parts"]> }) {
  const t = useT();
  return (
    <span className="block text-[10px] text-fg/80">
      {parts.map((p) => (
        <span key={p.energy} className="mr-2 inline-block">
          {t("tco.split", {
            energy: t(`energy.${p.energy}` as "energy.petrol"),
            km: fmtNum(p.km, 0),
            per: fmtNum(p.per_100km, 1),
            unit: p.unit,
            price: fmtNum(p.price, 3),
          })}{" "}
          = €{fmtNum(p.annual_eur, 0)}
        </span>
      ))}
    </span>
  );
}

function Row({ it }: { it: Item }) {
  return (
    <li
      className="flex items-start justify-between gap-2 py-1 text-xs"
      title={it.inputs.join("\n")}
    >
      <span className="min-w-0 flex-1">
        <span className={cx(it.annual_eur === null && "text-muted")}>
          {it.label}
        </span>
        <span className="block truncate text-[10px] text-muted">
          {it.inputs.join(" · ")}
        </span>
        {it.parts && it.parts.length > 1 && <Split parts={it.parts} />}
      </span>
      <span className="flex shrink-0 items-center gap-1.5 tabular">
        {eur(it.annual_eur)}/yr
        {it.basis === "SOURCED" ? (
          <ProvenanceBadge p="SOURCED_FACT" />
        ) : (
          <AssumptionBadge />
        )}
        {it.sources.length > 0 && <SourcesButton sources={it.sources} />}
      </span>
    </li>
  );
}

function CarCost({
  car,
  color,
  max,
  over,
}: {
  car: Car;
  color: string;
  max: number;
  over: string;
}) {
  const t = useT();
  const regular = car.items.filter(
    (i) =>
      i.kind !== "BIG_TICKET" &&
      i.kind !== "BASE_RESERVE" &&
      i.kind !== "DEPRECIATION",
  );
  const depreciation = car.items.filter((i) => i.kind === "DEPRECIATION");
  const bigTicket = car.items.filter((i) => i.kind === "BIG_TICKET");
  const reserve = car.items.filter((i) => i.kind === "BASE_RESERVE");
  const byKind = KIND_ORDER.map(
    (k) =>
      [
        k,
        car.items
          .filter((i) => i.kind === k)
          .reduce((a, i) => a + (i.annual_eur ?? 0), 0),
      ] as const,
  );
  return (
    <div className="min-w-0 rounded-xl border border-line/50 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <span
          className="min-w-0 truncate font-display text-sm font-semibold"
          style={{ color }}
        >
          {car.label}
          {car.condition === "USED" && (
            <span className="ml-1 text-xs font-normal text-muted">
              used{car.age_years ? `, ~${car.age_years} y` : ""}
            </span>
          )}
        </span>
        <span className="ml-auto text-right">
          <span className="font-display text-xl font-bold tabular">
            {eur(car.annual_total)}
          </span>
          <span className="text-xs text-muted">/yr</span>
          <span className="block text-xs text-muted sm:inline">
            <span className="hidden sm:inline"> · </span>
            {eur(car.five_year_total)} {over}
          </span>
        </span>
      </div>
      <div
        className="flex h-2.5 overflow-hidden rounded-full bg-panel2"
        aria-label="cost by item"
      >
        {byKind.map(([k, v]) =>
          v > 0 ? (
            <div
              key={k}
              title={`${KIND_LABEL[k]}: ${eur(v)}/yr`}
              style={{
                width: `${(v / max) * 100}%`,
                background: color,
                opacity: OPACITY[k],
              }}
            />
          ) : null,
        )}
      </div>
      <ul className="mt-2 divide-y divide-line/30">
        {regular.map((it) => (
          <Row key={it.kind + it.label} it={it} />
        ))}
      </ul>
      {(bigTicket.length > 0 || reserve.length > 0) && (
        <div className="mt-2 rounded-lg bg-panel2/60 p-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            Repair reserve (used car)
          </div>
          <div className="mt-1 text-[11px] text-muted">
            a) Documented items due within 5 years
          </div>
          {bigTicket.length === 0 ? (
            <p className="text-xs text-muted">
              None documented for this age and mileage.
            </p>
          ) : (
            <ul>
              {bigTicket.map((it) => (
                <Row key={it.label} it={it} />
              ))}
            </ul>
          )}
          <div className="mt-1 text-[11px] text-muted">
            b) Base reserve by age and class
          </div>
          <ul>
            {reserve.map((it) => (
              <Row key={it.label} it={it} />
            ))}
          </ul>
        </div>
      )}
      {depreciation.length > 0 && (
        <div className="mt-2 border-t border-line/30 pt-1">
          <div className="text-[11px] text-muted">{t("tco.depreciation")}</div>
          <ul>
            {depreciation.map((it) => (
              <Row key={it.label} it={it} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Tco({ b }: { b: BlockOf<"tco"> }) {
  const color = useCarColor();
  const t = useT();
  const lang = useLang();
  const max = Math.max(1, ...b.cars.map((c) => c.annual_total));
  const over = t("tco.over", {
    years: yearsLabel(b.years, lang, t("profile.years", { n: b.years })),
  });
  return (
    <BlockCard
      title={useBlockTitle(b.type, b.title)}
      icon={<WrenchIcon />}
      right={<span className="chip">{fmtNum(b.annual_km, 0)} km/yr</span>}
    >
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {b.cars.map((c) => (
          <CarCost
            key={c.car_id}
            car={c}
            color={color(c.car_id)}
            max={max}
            over={over}
          />
        ))}
      </div>
    </BlockCard>
  );
}
