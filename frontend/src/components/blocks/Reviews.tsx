import { useBlockTitle } from "../../i18n";
/** Review summary (FR-037): recurring points (≥2 sources) first, isolated opinions marked as such. */
import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { BlockCard, SourcesButton } from "../badges";
import { useCarColor } from "../carColors";
import { BookIcon } from "../icons";

type Point = BlockOf<"reviews">["cars"][number]["pros"][number];

function Points({
  title,
  items,
  tone,
}: {
  title: string;
  items: Point[];
  tone: "good" | "bad";
}) {
  return (
    <div>
      <div
        className={cx(
          "mb-1 text-[11px] font-semibold uppercase tracking-wide",
          tone === "good" ? "text-good" : "text-bad",
        )}
      >
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-muted">—</p>
      ) : (
        <ul className="space-y-1">
          {items.map((p, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs">
              <span className="chip shrink-0 text-[10px]">{p.tag}</span>
              <span
                className={cx("min-w-0 flex-1", !p.recurring && "text-muted")}
              >
                {p.text}
                {!p.recurring && (
                  <i className="ml-1 text-[10px]">(single source)</i>
                )}
              </span>
              {p.sources.length > 0 && <SourcesButton sources={p.sources} area="reviews" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Reviews({ b }: { b: BlockOf<"reviews"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<BookIcon />}>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {b.cars.map((car) => (
          <div
            key={car.car_id}
            className="rounded-xl border border-line/50 p-3"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span
                className="truncate font-display text-sm font-semibold"
                style={{ color: color(car.car_id) }}
              >
                {car.label}
              </span>
              <span
                className={cx("chip shrink-0", !car.minimum_met && "text-warn")}
              >
                {car.review_count} points · {car.source_count} sources
                {car.minimum_met ? "" : " · insufficient data"}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Points title="Pros" items={car.pros} tone="good" />
              <Points title="Cons" items={car.cons} tone="bad" />
            </div>
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
