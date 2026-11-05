import type { Transport, TransportHandlers } from "../lib/transport";
import { uuid } from "../lib/util";
import { mockBlocks, mockText, type MockProfile } from "./data";
import { MockCase, carEditFlow, challengeFlow, errorFlow, intakeFlow, reportFlow, type Step as FlowStep } from "./flows";

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

/**
 * Local stand-in for the backend: replays a realistic turn with delays.
 * A message with "error" or "limit" shows those states; "v1" (or "classic") replays the old report; anything else
 * runs the v2 flow: case file → intake card → "Agreed" → research grid → verdict report (spec 010 T097). The
 * report's "Change", "wrong?" and the card's buttons answer too.
 */
export function createMockTransport(h: TransportHandlers): Transport {
  let timers: ReturnType<typeof setTimeout>[] = [];
  let turn = 0;
  h.onState("mock");

  const emit = (at: number, msg: unknown) => {
    // Round-trip through JSON so the UI sees exactly what a socket would deliver.
    timers.push(setTimeout(() => h.onMessage(JSON.parse(JSON.stringify(msg))), at));
  };

  const mc = new MockCase();
  const play = (steps: FlowStep[]) => {
    let at = 60;
    for (const s of steps) {
      at += s.delay;
      emit(at, s.msg);
    }
  };

  return {
    send(msg) {
      if (msg.type === "confirm") {
        if (msg.choice === "stop") play([{ delay: 200, msg: { type: "assistant_message", message_id: uuid(), created_at: new Date().toISOString(), text: "OK — the cars are kept; tell me when to research.", blocks: [] } }]);
        else play(reportFlow(mc, !mc.confirmed));
        return true;
      }
      if (msg.type === "intake_edit") {
        play([{ delay: 200, msg: mc.caseFile([`${msg.car_key ?? "you"}: ${msg.field} → ${msg.value}`]) }, ...intakeFlow(mc).slice(2)]);
        return true;
      }
      if (msg.type === "car_edit") {
        play(carEditFlow(mc, msg.car_key, msg.field, msg.value));
        return true;
      }
      if (msg.type === "find") {
        play(reportFlow(mc, false));
        return true;
      }
      if (msg.type === "challenge") {
        play(challengeFlow(msg.car_id, msg.attribute));
        return true;
      }
      if (msg.type !== "user_message") return true; // hello/cancel/rating are no-ops in mock mode
      emit(60, { type: "user_message_ack", message_id: msg.message_id, created_at: new Date().toISOString() });
      const kind = /\blimit\b/i.test(msg.text) ? "limit" : /\berror\b/i.test(msg.text) ? "error" : null;
      if (kind) {
        play(errorFlow(kind));
        return true;
      }
      if (!/\b(v1|classic)\b/i.test(msg.text)) {
        play(mc.confirmed ? reportFlow(mc, false) : intakeFlow(mc));
        return true;
      }
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
