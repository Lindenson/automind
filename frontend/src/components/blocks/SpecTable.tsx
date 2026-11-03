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

export function SpecTable({ b }: { b: BlockOf<"spec_table"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={b.title} icon={<TableIcon />}>
      <div className="-mx-4 -my-4 overflow-x-auto scroll-thin">
        <table className="w-full min-w-[480px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line/60 bg-panel2/50">
              <th className="sticky left-0 z-10 w-[28%] bg-panel px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
                Spec
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
                        title={`Researched ${fmtDate(c.researched_at)}`}
                      >
                        <CacheIcon /> cached
                      </span>
                    ) : (
                      <span title="Researched in this turn">
                        researched {fmtDate(c.researched_at)}
                      </span>
                    )}
                  </div>
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
                    <span className="ml-1 text-[11px] font-normal text-muted/70">
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
                          className="text-[13px] italic text-muted/70"
                          title="This value could not be found or verified"
                        >
                          unavailable
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
                        <span
                          className={
                            v.better
                              ? "tabular font-semibold text-good"
                              : "tabular font-medium text-fg"
                          }
                          title={v.better ? "clearly better (above the meaningful threshold)" : undefined}
                        >
                          {text}
                        </span>
                        {v.confidence && <ConfidenceDot c={v.confidence} />}
                        {v.provenance && <ProvenanceBadge p={v.provenance} />}
                        <SourcesButton sources={v.sources} />
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
