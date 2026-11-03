/**
 * Criteria weights (FR-026; spec 007 US2): sliders show the current weights normalized to 100 %, each with its
 * reasons (persona, profile, wishes, the user's own change). Releasing a slider sends the whole set (PATCH); it is
 * kept as an adjustment on top of the automatic weights, and "back to automatic" removes it.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { patchCase } from "../../store/case";
import { useT } from "../../i18n";
import { useChat } from "../../store/chat";

type Crit = { key: string; label: string; definition: string };

let criteriaCache: Crit[] | null = null;

function useCriteria(): Crit[] {
  const [list, setList] = useState<Crit[]>(criteriaCache ?? []);
  useEffect(() => {
    if (criteriaCache) return;
    fetch("/api/v1/criteria", { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { criteria?: Crit[] } | null) => {
        if (d?.criteria) {
          criteriaCache = d.criteria;
          setList(d.criteria);
        }
      })
      .catch(() => undefined);
  }, []);
  return list;
}

export type WeightLine = {
  final: number;
  base: number;
  manual: number;
  reasons: { code: string; points: number }[];
};
export type WeightsView = {
  weights: Record<string, WeightLine>;
  manual: boolean;
  excluded: string[];
};

/** The current weights with their reasons (spec 007 FR-011), fetched after every case change, so the sliders
 *  follow a persona or profile edit before the next research. */
function useWeightsView(): WeightsView | null {
  const chatId = useChat((s) => s.chatId);
  const version = useChat((s) => s.caseFile?.version ?? 0);
  const [view, setView] = useState<WeightsView | null>(null);
  useEffect(() => {
    if (!chatId) return;
    let live = true;
    fetch(`/api/v1/chats/${chatId}/weights`, {
      headers: { Accept: "application/json" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: WeightsView | null) => {
        if (live && d?.weights) setView(d);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [chatId, version]);
  return view;
}

function useEffectiveWeights(view: WeightsView | null): Record<string, number> {
  return useMemo(
    () =>
      Object.fromEntries(
        Object.entries(view?.weights ?? {})
          .filter(([, l]) => l.final > 0)
          .map(([k, l]) => [k, l.final]),
      ),
    [view],
  );
}

/** "+10 % — family" for each reason of a weight. */
export function ReasonLine({ line }: { line: WeightLine }) {
  const t = useT();
  const parts = line.reasons.map(
    (r) =>
      `${r.points > 0 ? "+" : ""}${Math.round(r.points)} ${t(`reason.${r.code}` as "reason.manual")}`,
  );
  if (Math.abs(line.manual) >= 0.5)
    parts.push(
      `${line.manual > 0 ? "+" : ""}${Math.round(line.manual)} ${t("reason.manual")}`,
    );
  if (parts.length === 0) return null;
  return (
    <span className="block text-[10px] leading-tight text-muted">
      {parts.join(" · ")}
    </span>
  );
}

const DEBOUNCE_MS = 600;

export function Weights({ onError }: { onError: (e: string | null) => void }) {
  const t = useT();
  const chatId = useChat((s) => s.chatId);
  const criteria = useCriteria();
  const view = useWeightsView();
  const effective = useEffectiveWeights(view);
  const [draft, setDraft] = useState<Record<string, number>>(effective);
  useEffect(() => setDraft(effective), [effective]);
  const [adding, setAdding] = useState("");

  const total = Object.values(draft).reduce((a, b) => a + b, 0) || 1;
  const shown = criteria.filter((c) => (draft[c.key] ?? 0) > 0);
  const others = criteria.filter((c) => !((draft[c.key] ?? 0) > 0));

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  // spec 007 J (T075): one PATCH after the slider settles, not one per movement
  const commit = (next: Record<string, number>) => {
    // zeros are sent too: a criterion set to 0 is excluded until "back to automatic" (spec 007 FR-010)
    if (!Object.values(next).some((v) => v > 0)) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void patchCase(chatId, { weights: next }).then(onError);
    }, DEBOUNCE_MS);
  };

  if (criteria.length === 0 || Object.keys(effective).length === 0) {
    return (
      <p className="text-sm text-muted">
        Weights appear after the first comparison.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {view?.manual && (
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="rounded border border-amber-500/50 px-1.5 py-0.5 text-amber-300">
            {t("weights.manual")}
          </span>
          <button
            type="button"
            className="underline-offset-2 hover:underline"
            onClick={async () =>
              onError(await patchCase(chatId, { reset_weights: true }))
            }
          >
            {t("weights.reset")}
          </button>
        </div>
      )}
      {shown.map((c) => (
        <label key={c.key} className="block text-xs" title={c.definition}>
          <span className="flex justify-between">
            <span>{c.label}</span>
            <span className="tabular text-muted">
              {Math.round(((draft[c.key] ?? 0) / total) * 100)}%
            </span>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={draft[c.key] ?? 0}
            aria-label={`${c.label} weight`}
            className="w-full accent-[rgb(var(--accent))]"
            onChange={(e) =>
              setDraft({ ...draft, [c.key]: Number(e.target.value) })
            }
            onPointerUp={() => commit(draft)}
            onKeyUp={() => commit(draft)}
          />
          {view?.weights[c.key] && <ReasonLine line={view.weights[c.key]!} />}
        </label>
      ))}
      {others.length > 0 && (
        <select
          className="w-full rounded border border-line/70 bg-panel2 px-2 py-1 text-xs"
          value={adding}
          onChange={(e) => {
            const key = e.target.value;
            setAdding("");
            if (key) commit({ ...draft, [key]: 15 });
          }}
        >
          <option value="">+ add a criterion…</option>
          {others.map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
