import { useBlockTitle, useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { fmtDate } from "../../lib/util";
import {
  BlockCard,
  CarSwatch,
  ConfidenceDot,
  ProvenanceBadge,
  SourcesButton,
} from "../badges";
import { useCarColor } from "../carColors";
import { CacheIcon, TableIcon } from "../icons";
import { ChallengeButton, ChallengedValue } from "../ChallengeButton";
import { CarChange } from "../CarChange";
import { useChat } from "../../store/chat";
import type { Provenance } from "../../lib/protocol";

const LEGEND: Provenance[] = ["MANUFACTURER_CLAIM", "MEASURED", "SIMULATED_ESTIMATE", "ASSUMPTION"];

/** One line above the table (spec 010 FR-040): what the badges and the dot mean. */
export function SpecLegend() {
  const t = useT();
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted" data-testid="spec-legend">
      <span>{t("table.legend")}</span>
      {LEGEND.map((p) => (
        <span key={p} className="inline-flex items-center gap-1">
          <ProvenanceBadge p={p} />
          <span>{t(`prov.${p}.full` as "prov.MEASURED.full")}</span>
        </span>
      ))}
      <span>· {t("table.legend.conf")}</span>
    </p>
  );
}

/** "Change" in a column header: the case car with this version (spec 010 FR-037). */
function ColumnChange({ variantId, name }: { variantId: string; name: string }) {
  const car = useChat((s) => s.caseFile?.data.cars.find((c) => c.variant_id === variantId));
  if (!car) return null;
  return <CarChange car={car} name={name} className="mt-1.5" />;
}

export function SpecTable({ b }: { b: BlockOf<"spec_table"> }) {
  const color = useCarColor();
  const t = useT();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<TableIcon />}>
      <div className="-mx-4 -mt-2 mb-2 px-4">
        <SpecLegend />
      </div>
      <div className="-mx-4 -mb-4 overflow-x-auto scroll-thin">
        <table className="w-full min-w-[480px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line/60 bg-panel2/50">
              <th className="sticky left-0 z-10 w-[28%] bg-panel px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
                {t("table.spec")}
              </th>
              {b.cars.map((c) => (
                <th
                  key={c.id}
                  className="px-3 py-3 text-left align-top font-normal"
                >
                  <div className="flex items-center gap-2 font-display text-[13px] font-semibold text-fg">
                    <CarSwatch color={color(c.id)} />
                    <span>{c.label}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                    <span className="chip py-0">{c.powertrain}</span>
                    {c.from_cache ? (
                      <span
                        className="chip py-0 text-accent2"
                        title={t("table.researchedAt", { date: fmtDate(c.researched_at) })}
                      >
                        <CacheIcon /> {t("table.cached")}
                      </span>
                    ) : (
                      <span title={t("table.researchedNow")}>
                        {t("table.researched", { date: fmtDate(c.researched_at) })}
                      </span>
                    )}
                  </div>
                  <ColumnChange variantId={c.id} name={c.label} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.rows.map((row) => (
              <tr
                key={row.key}
                className="border-b border-line/40 last:border-0 hover:bg-panel2/40"
              >
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-panel px-4 py-2.5 text-left align-top font-medium text-muted"
                >
                  {row.label}
                  {row.unit && (
                    <span className="ml-1 text-[11px] font-normal text-muted">
                      ({row.unit})
                    </span>
                  )}
                </th>
                {b.cars.map((c) => {
                  const v = row.values.find((x) => x.car_id === c.id);
                  if (!v || !v.available) {
                    return (
                      <td key={c.id} className="px-3 py-2.5 align-top">
                        <span
                          className="text-[13px] italic text-muted"
                          title={t("table.unavailable.title")}
                        >
                          {t("table.unavailable")}
                        </span>
                      </td>
                    );
                  }
                  const text =
                    v.display ??
                    (v.value !== null
                      ? `${v.value}${row.unit ? ` ${row.unit}` : ""}`
                      : "—");
                  return (
                    <td key={c.id} className="px-3 py-2.5 align-top">
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <ChallengedValue carId={c.id} attribute={row.key}>
                          <span
                            className={
                              v.better
                                ? "tabular font-semibold text-good"
                                : "tabular font-medium text-fg"
                            }
                            title={v.better ? t("table.better") : undefined}
                          >
                            {text}
                          </span>
                        </ChallengedValue>
                        {v.confidence && <ConfidenceDot c={v.confidence} />}
                        {v.provenance && <ProvenanceBadge p={v.provenance} />}
                        <SourcesButton
                          sources={v.sources}
                          what={`${row.label}, ${c.label}`}
                          carId={c.id}
                          attribute={row.key}
                          area="specs"
                        />
                        <ChallengeButton carId={c.id} attribute={row.key} label={row.label} />
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BlockCard>
  );
}
