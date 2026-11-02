import type { Transport, TransportHandlers } from "../lib/transport";
import { uuid } from "../lib/util";
import { mockBlocks, mockText, type MockProfile } from "./data";

type Step = { delay: number; msg: Record<string, unknown> };

function script(text: string, turn: number): { steps: Step[]; profile: MockProfile; fromCache: boolean } {
  const profile: MockProfile = /buyer|cheap|cost|value/i.test(text) ? "smart_buyer" : "performance";
  const fromCache = turn > 0;
  const st = (stage: string, t: string, car?: string) => ({ type: "status", stage, text: t, ...(car ? { car } : {}) });
  const steps: Step[] = [
    { delay: 350, msg: st("understanding", "Understanding your request …") },
    { delay: 700, msg: st("resolving", "Resolved: VW Golf GTI Mk8 (2020–), Hyundai i30 N (2021–) · profile: " + (profile === "performance" ? "race enthusiast" : "smart buyer")) },
    { delay: 600, msg: st("cache", fromCache ? "Cache hit for both cars — skipping research" : "Cache miss for 2 cars — starting research") },
  ];
  if (!fromCache) {
    steps.push(
      { delay: 900, msg: st("researching", "Researching VW Golf GTI Mk8 (2020–) …", "VW Golf GTI Mk8") },
      { delay: 1100, msg: st("researching", "Researching Hyundai i30 N (2021–) …", "Hyundai i30 N") },
      { delay: 900, msg: st("validating", "Validating 18 extracted values against source excerpts …") },
    );
  }
  steps.push(
    { delay: 800, msg: st("analyzing", "Running metrics, drag race simulation and profile scores …") },
    { delay: 900, msg: st("composing", "Composing the answer …") },
    { delay: 500, msg: st("done", "Done") },
  );
  return { steps, profile, fromCache };
}

/** Local stand-in for the backend: replays a realistic turn with delays. */
export function createMockTransport(h: TransportHandlers): Transport {
  let timers: ReturnType<typeof setTimeout>[] = [];
  let turn = 0;
  h.onState("mock");

  const emit = (at: number, msg: unknown) => {
    // Round-trip through JSON so the UI sees exactly what a socket would deliver.
    timers.push(setTimeout(() => h.onMessage(JSON.parse(JSON.stringify(msg))), at));
  };

  return {
    send(msg) {
      if (msg.type !== "user_message") return true; // hello/confirm/cancel are no-ops in mock mode
      emit(60, { type: "user_message_ack", message_id: msg.message_id, created_at: new Date().toISOString() });
      const { steps, profile, fromCache } = script(msg.text, turn++);
      let at = 60;
      for (const s of steps) {
        at += s.delay;
        emit(at, s.msg);
      }
      emit(at + 150, {
        type: "assistant_message",
        message_id: uuid(),
        created_at: new Date(Date.now() + at).toISOString(),
        text: mockText(profile),
        blocks: mockBlocks(profile, fromCache),
      });
      return true;
    },
    close() {
      timers.forEach(clearTimeout);
      timers = [];
    },
  };
}
