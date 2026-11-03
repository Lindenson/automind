import { useT } from "../i18n";
import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "../store/chat";
import type { ChatMessage } from "../lib/protocol";
import { fmtTime } from "../lib/util";
import { useChat } from "../store/chat";
import { BlockView } from "./blocks/BlockView";
import type { Block } from "../lib/protocol";
import { RatingControl } from "./RatingControl";
import { buildCarColors, CarColorContext } from "./carColors";
import { Logo } from "./Logo";
import { WarnIcon } from "./icons";

export const Message = memo(function Message({ m }: { m: UiMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex animate-fadeUp justify-end">
        <div className="max-w-[85%] sm:max-w-[75%]">
          <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-gradient-to-br from-accent to-orange-600 px-4 py-2.5 text-[15px] text-white shadow-lg shadow-accent/10">
            {m.text}
          </div>
          <div className="mt-1 text-right text-[10px] text-muted">
            {fmtTime(m.created_at)}
          </div>
        </div>
      </div>
    );
  }
  if (m.role === "error") {
    return (
      <div
        className="flex animate-fadeUp items-start gap-2 rounded-xl border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-sm"
        role="alert"
      >
        <span className="mt-0.5 text-bad">
          <WarnIcon />
        </span>
        <span>{m.text}</span>
      </div>
    );
  }
  return <AssistantMessage m={m} />;
});

const SECTIONS = new Set([
  "comparison", "engineering", "performance", "cost_over_time", "value_retention", "reliability", "reviews",
  "manufacturer", "data_panel", "sources",
]);

/** Consecutive blocks of one section become one collapsible part (spec 004 FR-002). */
function groupSections(blocks: Block[]): { section?: string; open: boolean; blocks: Block[] }[] {
  const out: { section?: string; open: boolean; blocks: Block[] }[] = [];
  for (const b of blocks) {
    const last = out[out.length - 1];
    if (b.section && last && last.section === b.section) last.blocks.push(b);
    else out.push({ section: b.section, open: Boolean(b.open), blocks: [b] });
  }
  return out;
}

function AssistantMessage({ m }: { m: ChatMessage }) {
  const colors = useMemo(() => buildCarColors(m.blocks), [m.blocks]);
  const t = useT();
  // spec 004 FR-001: the verdict card comes first, before the explanation
  const lead = m.blocks.filter((b) => b.type === "verdict");
  const rest = m.blocks.filter((b) => b.type !== "verdict");
  return (
    <div className="flex animate-fadeUp gap-3">
      <div className="hidden shrink-0 sm:block">
        <Logo small />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="font-display font-semibold text-fg">AutoMind</span>
          <span>{fmtTime(m.created_at)}</span>
          <UsageBadge turnId={m.turn_id} />
        </div>
        <CarColorContext.Provider value={colors}>
          {lead.map((b, i) => (
            <BlockView key={`lead-${i}`} block={b} />
          ))}
        </CarColorContext.Provider>
        {m.text && (
          <div className="md">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ node: _n, ...p }) => (
                  <a {...p} target="_blank" rel="noreferrer noopener" />
                ),
              }}
            >
              {m.text}
            </ReactMarkdown>
          </div>
        )}
        <CarColorContext.Provider value={colors}>
          {groupSections(rest).map((g, i) =>
            g.section ? (
              <details key={i} open={g.open} className="group rounded-xl border border-line/40 p-2 sm:p-3">
                <summary className="min-h-11 cursor-pointer select-none py-2 text-sm font-semibold capitalize">
                  {SECTIONS.has(g.section) ? t(`section.${g.section}` as "section.comparison") : g.section.replace(/_/g, " ")}
                </summary>
                <div className="mt-2 space-y-3">
                  {g.blocks.map((b, j) => (
                    <BlockView key={j} block={b} />
                  ))}
                </div>
              </details>
            ) : (
              g.blocks.map((b, j) => <BlockView key={`${i}-${j}`} block={b} />)
            ),
          )}
        </CarColorContext.Provider>
        {lead.length > 0 && <RatingControl messageId={m.message_id} />}
      </div>
    </div>
  );
}

/** AI usage of the turn that produced this answer (FR-042): calls, tokens and estimated cost. */
function UsageBadge({ turnId }: { turnId?: string | null }) {
  const u = useChat((s) => (turnId ? s.usageByTurn[turnId] : undefined));
  if (!u) return null;
  return (
    <span
      className="chip text-[10px]"
      title={`${u.llm_calls} AI calls · ${u.input_tokens.toLocaleString()} in / ${u.output_tokens.toLocaleString()} out tokens · ${u.search_calls} searches`}
    >
      {u.llm_calls} calls · {u.search_calls} searches · €{u.cost_eur.toFixed(3)}
    </span>
  );
}
