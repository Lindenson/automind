/**
 * Criteria weights (FR-026): sliders show the current weights normalized to 100 %. Releasing a
 * slider sends the whole weight set (PATCH); scores are recomputed from cached data on the next turn.
 */
import { useEffect, useMemo, useState } from "react";
import { patchCase } from "../../store/case";
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

/** Effective weights: the user's override, else the ones used in the latest criteria scores. */
function useEffectiveWeights(): Record<string, number> {
  const override = useChat((s) =>
    s.caseFile?.data.weights_overridden ? s.caseFile.data.weights : null,
  );
  const messages = useChat((s) => s.messages);
  return useMemo(() => {
    if (override && Object.keys(override).length) return override;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]!;
      if (m.role !== "assistant") continue;
      const b = m.blocks.find((x) => x.type === "criteria_scores");
      if (b && b.type === "criteria_scores")
        return Object.fromEntries(b.criteria.map((c) => [c.key, c.weight]));
    }
    return {};
  }, [override, messages]);
}

export function Weights({ onError }: { onError: (e: string | null) => void }) {
  const chatId = useChat((s) => s.chatId);
  const criteria = useCriteria();
  const effective = useEffectiveWeights();
  const [draft, setDraft] = useState<Record<string, number>>(effective);
  useEffect(() => setDraft(effective), [effective]);
  const [adding, setAdding] = useState("");

  const total = Object.values(draft).reduce((a, b) => a + b, 0) || 1;
  const shown = criteria.filter((c) => (draft[c.key] ?? 0) > 0);
  const others = criteria.filter((c) => !((draft[c.key] ?? 0) > 0));

  const commit = async (next: Record<string, number>) => {
    const clean = Object.fromEntries(
      Object.entries(next).filter(([, v]) => v > 0),
    );
    if (Object.keys(clean).length === 0) return;
    onError(await patchCase(chatId, { weights: clean }));
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
            onPointerUp={() => void commit(draft)}
            onKeyUp={() => void commit(draft)}
          />
        </label>
      ))}
      {others.length > 0 && (
        <select
          className="w-full rounded border border-line/70 bg-panel2 px-2 py-1 text-xs"
          value={adding}
          onChange={(e) => {
            const key = e.target.value;
            setAdding("");
            if (key) void commit({ ...draft, [key]: 15 });
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
