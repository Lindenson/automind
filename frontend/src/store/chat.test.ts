import { beforeEach, describe, expect, it } from "vitest";
import { useChat } from "./chat";

const base = { seq: 1, turn_id: "t1" };

describe("chat store (protocol v2)", () => {
  beforeEach(() => useChat.getState().newChat());

  it("rebuilds progress after a reload and shows a confirmation card", () => {
    const { handleRaw } = useChat.getState();
    handleRaw({
      ...base,
      type: "status",
      stage: "resolving",
      text: "Identifying",
    });
    expect(useChat.getState().pending?.statuses).toHaveLength(1);
    handleRaw({
      ...base,
      seq: 2,
      type: "confirm_request",
      kind: "variants",
      text: "Confirm?",
      options: [{ id: "o1", label: "Prado J150" }],
    });
    const s = useChat.getState();
    expect(s.pending).toBeNull();
    expect(s.confirm?.options[0]?.label).toBe("Prado J150");
  });

  it("keeps the newest case version and records usage per turn", () => {
    const { handleRaw } = useChat.getState();
    handleRaw({
      ...base,
      type: "case_file",
      version: 3,
      case: { persona: "BUYER" },
      changes: ["persona: UNKNOWN → BUYER"],
    });
    handleRaw({
      ...base,
      type: "case_file",
      version: 2,
      case: { persona: "EXPERT" },
      changes: [],
    });
    expect(useChat.getState().caseFile?.data.persona).toBe("BUYER");
    handleRaw({
      ...base,
      type: "usage",
      llm_calls: 3,
      input_tokens: 10,
      output_tokens: 2,
      search_calls: 1,
      cost_eur: 0.01,
    });
    expect(useChat.getState().usageByTurn.t1?.llm_calls).toBe(3);
  });

  it("clears the turn on cancel and on the final answer", () => {
    const { handleRaw } = useChat.getState();
    handleRaw({ ...base, type: "status", stage: "researching", text: "x" });
    handleRaw({ ...base, type: "turn_cancelled" });
    expect(useChat.getState().pending).toBeNull();
    handleRaw({
      ...base,
      type: "assistant_message",
      message_id: "m1",
      created_at: "2026-11-01T00:00:00Z",
      text: "hi",
      blocks: [],
      action: "REPORT",
    });
    expect(useChat.getState().messages.at(-1)).toMatchObject({
      role: "assistant",
      turn_id: "t1",
    });
  });
});

describe("spec 004 progress grid", () => {
  it("keeps the latest state per car and area", () => {
    useChat.getState().newChat();
    const { handleRaw } = useChat.getState();
    const p = { type: "progress", seq: 1, turn_id: "t1", car: "Mazda CX-5", car_key: "car#1", round: 0 };
    handleRaw({ ...p, area: "specs", state: "queued" });
    handleRaw({ ...p, seq: 2, area: "specs", state: "done", accepted: 12 });
    handleRaw({ ...p, seq: 3, area: "price", state: "searching" });
    const grid = useChat.getState().pending?.grid ?? {};
    expect(grid["car#1|specs"]?.state).toBe("done");
    expect(grid["car#1|specs"]?.accepted).toBe(12);
    expect(grid["car#1|price"]?.state).toBe("searching");
  });
});
