/** Spec 006 US7: the electric section — the same rows for every electric or plug-in car, gaps marked. */
import { useBlockTitle, useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { fmtNum } from "../../lib/util";
import { BlockCard } from "../badges";
import { GaugeIcon } from "../icons";

type Car = BlockOf<"electric">["cars"][number];
type Key =
  | "electric.battery"
  | "electric.range"
  | "electric.consumption"
  | "electric.charging_home"
  | "electric.charging_dc"
  | "electric.electric_share"
  | "electric.cost_per_100km"
  | "electric.label";

const num = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? null : fmtNum(v, d);

function cell(c: Car, row: string, t: ReturnType<typeof useT>): string | null {
  const v = c.values;
  const nf = t("electric.not_found");
  switch (row) {
    case "battery": {
      const u = num(v.battery.usable_kwh, 1);
      const g = num(v.battery.gross_kwh, 1);
      if (!u && !g) return null;
      return [
        u && `${u} kWh`,
        g && `${t("electric.gross")} ${g} kWh`,
        v.battery.chemistry,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    case "range": {
      const w = num(v.range.wltp_km);
      const r = num(v.range.real_km);
      if (!w && !r) return null;
      return `${t("electric.wltp")} ${w ? `${w} km` : nf} · ${t("electric.real")} ${r ? `≈${r} km` : nf}`;
    }
    case "consumption": {
      const k = num(
        v.consumption.real_kwh_per_100km ?? v.consumption.kwh_per_100km,
        1,
      );
      return k ? `${k} kWh/100 km` : null;
    }
    case "charging_home": {
      const ac = num(v.charging_home.ac_kw, 1);
      const h = num(v.charging_home.full_h, 1);
      return ac
        ? `${ac} kW${h ? ` · ${t("electric.full_in", { h })}` : ""}`
        : null;
    }
    case "charging_dc": {
      const p = num(v.charging_dc.peak_kw);
      const m = num(v.charging_dc.min_10_80);
      if (!p && !m) return null;
      return [p && `${p} kW`, m && t("electric.dc_time", { m })]
        .filter(Boolean)
        .join(" · ");
    }
    case "electric_share":
      return v.electric_share.share === null ||
        v.electric_share.share === undefined
        ? c.powertrain === "BEV"
          ? "100 %"
          : null
        : `${fmtNum(v.electric_share.share * 100, 0)} %`;
    case "cost_per_100km": {
      const home = num(v.cost_per_100km.home_eur, 2);
      const pub = num(v.cost_per_100km.public_eur, 2);
      if (!home && !pub) return null;
      return `${t("electric.home")} ${home ? `€${home}` : nf} · ${t("electric.public")} ${pub ? `€${pub}` : nf}`;
    }
    case "label":
      return v.label ? v.label.label : null;
    default:
      return null;
  }
}

export function Electric({ b }: { b: BlockOf<"electric"> }) {
  const t = useT();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<GaugeIcon />}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 pr-2 font-normal" />
              {b.cars.map((c) => (
                <th key={c.car_id} className="py-1 pr-2 font-medium text-fg">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.rows.map((row) => (
              <tr key={row} className="border-t border-line/40 align-top">
                <td className="py-1 pr-2 text-muted">
                  {t(`electric.${row}` as Key)}
                </td>
                {b.cars.map((c) => {
                  const v = cell(c, row, t);
                  return (
                    <td
                      key={c.car_id}
                      className={
                        v ? "py-1 pr-2 tabular" : "py-1 pr-2 text-muted"
                      }
                    >
                      {v ?? t("electric.not_found")}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {b.not_electric.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-muted">
          {b.not_electric.map((o) => (
            <li key={o.car_id}>
              {o.label}:{" "}
              {o.cost_per_100km_eur
                ? `€${fmtNum(o.cost_per_100km_eur, 2)}`
                : t("electric.not_found")}{" "}
              {t("electric.per_100km")}
            </li>
          ))}
        </ul>
      )}
      {b.incentives.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium">
            {t("electric.incentives")}
          </div>
          <ul className="space-y-0.5 text-xs">
            {b.incentives.map((i) => (
              <li
                key={i.key}
                className={i.status === "ACTIVE" ? "" : "text-muted"}
              >
                <span className="chip mr-1 text-[10px]">
                  {t(`electric.status_${i.status}` as "electric.status_ACTIVE")}
                </span>
                {i.label}
                {i.amount_eur
                  ? ` · ${t("electric.up_to")} €${fmtNum(i.amount_eur, 0)}`
                  : ""}
                {i.percent ? ` · ${fmtNum(i.percent, 0)} %` : ""}
                {i.valid_to ? ` · ${t("electric.until")} ${i.valid_to}` : ""}
                {i.subtractable ? ` · ${t("electric.in_break_even")}` : ""}
                {i.source_url && (
                  <a
                    className="ml-1 underline"
                    href={i.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("electric.source")}
                  </a>
                )}{" "}
                <span className="text-muted">
                  ({t("electric.as_of")} {i.as_of})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {b.notes.length > 0 && (
        <p className="mt-2 text-[10px] text-muted">{b.notes.join(" · ")}</p>
      )}
    </BlockCard>
  );
}
