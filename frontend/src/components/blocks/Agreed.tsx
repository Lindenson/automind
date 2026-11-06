/** What was agreed after a confirmation (spec 010 FR-035): a compact read-only entry that stays in the chat. */
import { useT } from "../../i18n";
import type { Key } from "../../i18n/en";
import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { BASIS_CLS } from "../badges";

export function Agreed({ b }: { b: BlockOf<"agreed"> }) {
  const t = useT();
  return (
    <details className="group rounded-xl border border-good/40 bg-good/5 px-3 py-2 text-sm" data-testid="agreed">
      <summary className="flex min-h-9 cursor-pointer select-none flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className="font-semibold text-good">✓ {t("agreed.title")}</span>
        <span className="min-w-0 truncate text-muted">
          {b.cars.map((c) => c.label).join(" · ")}
        </span>
        {b.cars
          .filter((c) => c.note)
          .map((c) => (
            <span key={c.key} className="basis-full text-xs text-muted" data-testid="agreed-market">
              {c.note}
            </span>
          ))}
      </summary>
      <ul className="mt-2 space-y-1.5">
        {b.cars.map((c) => (
          <li key={c.key} className="min-w-0">
            <div className="font-medium">{c.label}</div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
              {c.variant_label && <span data-testid="agreed-version">{c.variant_label}</span>}
              <span className={cx("rounded border px-1 text-[10px] uppercase", BASIS_CLS[c.basis])}>
                {t(`card.basis.${c.basis}` as Key)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
