/** Spec 010 T097: every mock message passes the protocol schemas, so mock screens show real UI states. */
import { describe, expect, it } from "vitest";
import { parseBlocks, parseServerMsg } from "../lib/protocol";
import { MockCase, carEditFlow, challengeFlow, errorFlow, intakeFlow, reportFlow } from "./flows";

describe("mock flows", () => {
  it("are valid server messages, blocks included", () => {
    const mc = new MockCase();
    const steps = [
      ...intakeFlow(mc),
      ...reportFlow(mc, true),
      ...carEditFlow(mc, "car#1", "engine", "1.5 TSI 150 CV"),
      ...carEditFlow(mc, "car#2", "remove"),
      ...challengeFlow("vw-golf-gti-mk8", "zero_100"),
      ...errorFlow("error"),
      ...errorFlow("limit"),
    ];
    const types = new Set<string>();
    for (const s of steps) {
      const m = parseServerMsg(s.msg);
      expect(m, JSON.stringify(s.msg).slice(0, 120)).not.toBeNull();
      types.add(m!.type);
      const raw = (s.msg as { blocks?: unknown[] }).blocks;
      if (raw) expect(parseBlocks(raw).length).toBe(raw.length);
    }
    for (const t of ["case_file", "confirm_request", "agreed", "progress", "assistant_message", "challenge_result", "error"])
      expect(types.has(t), t).toBe(true);
  });
});
