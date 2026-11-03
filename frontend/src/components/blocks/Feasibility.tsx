import { useBlockTitle } from "../../i18n";
/**
 * Does the request fit the user's case? (spec 003 US3, FR-019..FR-023). One verdict per car and check,
 * the numbers compared with their basis (sourced or assumption), and the used-car age range with its
 * basis (editorial price ranges or the depreciation estimate).
 */
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum } from "../../lib/util";
import { AssumptionBadge, BlockCard } from "../badges";
import { WarnIcon } from "../icons";

type Check = BlockOf<"feasibility">["cars"][number]["checks"][number];

const VERDICT: Record<Check["verdict"], { text: string; cls: string }> = {
  FITS: { text: "fits", cls: "bg-good/15 text-good" },
  DOES_NOT_FIT: { text: "does not fit", cls: "bg-bad/15 text-bad" },
  USED_ONLY: { text: "only used", cls: "bg-warn/15 text-warn" },
  OTHER_CLASS: { text: "another class", cls: "bg-warn/15 text-warn" },
  UNKNOWN: { text: "could not check", cls: "bg-panel2 text-muted" },
};

function CheckRow({ c }: { c: Check }) {
  const v = VERDICT[c.verdict];
  return (
    <li className="space-y-1 rounded-lg border border-line/40 bg-panel2/30 p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{c.label}</span>
        <span
          className={cx(
            "rounded px-1.5 py-0.5 text-[11px] font-semibold",
            v.cls,
          )}
        >
          {v.text}
        </span>
        {c.used_age && (
          <span className="text-xs text-muted">
            ≈ {c.used_age.from_years}–{c.used_age.to_years} years old (
            {c.used_age.basis === "EDITORIAL"
              ? "from buying guides"
              : "estimate"}
            )
          </span>
        )}
      </div>
      <p className="text-sm text-fg/90">{c.summary}</p>
      {c.compared.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {c.compared.map((n, i) => (
            <li
              key={i}
              className="flex items-center gap-1"
              title={n.inputs.join("; ")}
            >
              <span>{n.label}:</span>
              <span className="tabular font-medium text-fg">
                {n.value === null ? "—" : fmtNum(n.value)} {n.unit}
              </span>
              {n.basis === "ASSUMPTION" && <AssumptionBadge />}
              {n.sources[0] && (
                <a
                  href={n.sources[0].url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline"
                >
                  source
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
      {c.missing && c.missing.length > 0 && (
        <p className="text-xs text-muted">Missing: {c.missing.join(", ")}</p>
      )}
    </li>
  );
}

export function Feasibility({ b }: { b: BlockOf<"feasibility"> }) {
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<WarnIcon />}>
      {b.constraints.length > 0 && (
        <p className="mb-3 text-xs text-muted">
          Your case: {b.constraints.join(" · ")}
        </p>
      )}
      <div className="space-y-4">
        {b.cars.map((car) => (
          <div key={car.car_id}>
            <div className="mb-1.5 text-sm font-semibold">{car.label}</div>
            <ul className="space-y-2">
              {car.checks.map((c, i) => (
                <CheckRow key={i} c={c} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
