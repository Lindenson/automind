/** UI audit 2026-11-05 follow-up (F7, F8, F10–F13, F15): behaviour that can be checked without a browser. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientMsg } from "../lib/protocol";
import { VerdictBlockSchema } from "../lib/protocol";
import { GONE_CODES, type ConnState } from "../lib/transport";
import { createMockTransport } from "../mock/mockTransport";
import { errorFlow, errorScenario, MockCase, reportFlow, scenarioText } from "../mock/flows";
import { errorKind, useChat, type ErrorEntry, type PendingTurn } from "../store/chat";
import { MessageIdContext } from "./badges";
import { DataPanelPresent, Verdict } from "./blocks/Verdict";
import { QuickReplies } from "./blocks/QuickReplies";
import { Suggestions } from "./blocks/Suggestions";
import { tableMinWidth } from "./blocks/SpecTable";
import { ErrorNotice, nextStep } from "./ErrorNotice";
import { ConnBanner } from "./Header";
import { IntakeCard } from "./IntakeCard";
import { markRated, RatingControl, wasRated } from "./RatingControl";
import { StatusTimeline } from "./StatusTimeline";
import { Notice } from "./blocks/Notice";
import { trapTarget } from "../lib/util";

const status = (stage: string, text: string, at = 0) => ({ type: "status", stage, text, at }) as never;
const cell = (car_key: string, car: string, area: string, state = "searching") =>
  ({ type: "progress", car, car_key, area, state, round: 0 }) as never;

function reset() {
  useChat.getState().newChat();
  useChat.setState({ pending: null, conn: "mock", connAttempt: 0, transport: null });
}

describe("F7 long-research progress", () => {
  beforeEach(reset);
  const pending: PendingTurn = {
    userMessageId: "u1",
    startedAt: Date.now() - 5000,
    statuses: [
      status("understanding", "Understanding your request"),
      status("resolving", "Resolved: VW Golf GTI Mk8 (2.0 TSI · DSG), Hyundai i30 N"),
      status("researching", "Researching specs"),
    ],
    grid: {
      "car#1|specs": cell("car#1", "VW Golf GTI Mk8", "specs", "done"),
      "car#1|reliability": cell("car#1", "VW Golf GTI Mk8", "reliability"),
      "car#2|value_retention": cell("car#2", "Hyundai i30 N", "value_retention"),
    },
  };

  it("keeps the stage rail, the Resolved line, the elapsed time and Stop together with the grid", () => {
    useChat.setState({ pending });
    const html = renderToStaticMarkup(<StatusTimeline pending={pending} />);
    expect(html).toContain("Researching"); // card title
    expect(html).toContain("Resolve"); // the stage rail
    expect(html).toMatch(/data-testid="timeline-resolved".*Resolved: VW Golf GTI Mk8/);
    expect(html).toContain('data-testid="progress-grid"');
    expect(html).toContain('data-testid="progress-legend"');
    expect(html).toContain('data-testid="progress-elapsed"');
    expect(html).toContain("Stop"); // in the card header
    // the last step is still said in words under the grid
    expect(html).toContain("Researching specs");
  });

  it("scrolls the grid inside its box with the car column pinned, and hints at it on phones", () => {
    const html = renderToStaticMarkup(<StatusTimeline pending={pending} />);
    expect(html).toMatch(/overflow-x-auto[^"]*" tabindex="0" role="region"/);
    expect(html).toMatch(/<th scope="row" class="sticky left-0[^"]*bg-panel/);
    expect(html).toContain("Swipe sideways for all areas");
  });

  it("pins the Resolved line when later steps push it out of the list", () => {
    const many: PendingTurn = {
      userMessageId: "u1",
      startedAt: Date.now(),
      statuses: [
        status("resolving", "Resolved: Golf GTI"),
        ...Array.from({ length: 8 }, (_, i) => status("researching", `step ${i}`)),
      ],
    };
    const html = renderToStaticMarkup(<StatusTimeline pending={many} />);
    expect(html).toMatch(/data-testid="timeline-resolved".*Resolved: Golf GTI/);
    expect(html).not.toContain("progress-grid");
  });
});

describe("F8 errors, limits and connection give a next step", () => {
  beforeEach(reset);

  it("classifies the server's errors", () => {
    expect(errorKind("chat_deleted", "This chat was deleted.")).toBe("gone");
    expect(errorKind("chat_not_found", "No such chat.")).toBe("gone");
    expect(errorKind(null, "busy: a turn is already running in this chat")).toBe("busy");
    expect(errorKind("daily_cap", "Today's research budget is used up.")).toBe("limit");
    expect(errorKind(null, "The AI service is overloaded or out of quota right now.")).toBe("overloaded");
    expect(errorKind(null, "Something went wrong on my side.")).toBe("generic");
  });

  it("offers one action per kind", () => {
    const o = { running: false, canRetry: true };
    expect(nextStep("generic", o).action).toBe("retry");
    expect(nextStep("generic", { ...o, canRetry: false }).action).toBe("reload");
    expect(nextStep("overloaded", o)).toEqual({ next: "error.next.overloaded", action: "retry" });
    expect(nextStep("limit", o).action).toBe("continue");
    expect(nextStep("busy", { ...o, running: true }).action).toBe("stop");
    expect(nextStep("busy", o).action).toBe("reload");
    expect(nextStep("stopped", o).action).toBe("ask");
    expect(nextStep("offline", o).action).toBe("reconnect");
    expect(nextStep("gone", o).action).toBe("newChat");
  });

  it("stores the kind and the question to retry; a busy error keeps the running research on screen", () => {
    const sent: ClientMsg[] = [];
    useChat.getState().setTransport({ send: (m) => (sent.push(m), true), close: () => undefined });
    useChat.getState().send("Compare Golf and i30");
    const { handleRaw } = useChat.getState();
    handleRaw({ type: "error", text: "busy: a turn is already running in this chat" });
    expect(useChat.getState().pending).not.toBeNull();
    handleRaw({ type: "error", code: "daily_cap", text: "Today's research budget is used up." });
    expect(useChat.getState().pending).toBeNull();
    const errs = useChat.getState().messages.filter((m): m is ErrorEntry => m.role === "error");
    expect(errs.map((e) => e.kind)).toEqual(["busy", "limit"]);
    expect(errs[1]!.retry).toBe("Compare Golf and i30");
    handleRaw({ type: "turn_cancelled", turn_id: "t1" });
    expect(useChat.getState().messages.at(-1)).toMatchObject({ kind: "stopped", retry: "Compare Golf and i30" });
  });

  it("marks a message that could not be sent as offline, and a deleted chat as gone", () => {
    useChat.getState().setTransport({ send: () => false, close: () => undefined });
    expect(useChat.getState().send("hello")).toBe(false);
    expect(useChat.getState().messages.at(-1)).toMatchObject({ role: "error", kind: "offline" });
    useChat.getState().handleRaw({ type: "error", code: "chat_not_found", text: "No such chat." });
    expect(useChat.getState().messages).toEqual([
      expect.objectContaining({ kind: "gone", text: "This chat can't be opened here." }),
    ]);
  });

  it("renders what happened, the advice and the action", () => {
    const m: ErrorEntry = {
      role: "error", message_id: "e1", created_at: "", text: "Today's research budget is used up.", kind: "limit",
    };
    const html = renderToStaticMarkup(<ErrorNotice m={m} />);
    expect(html).toContain("Today&#x27;s research budget is used up.");
    expect(html).toContain("continue with the cars already researched");
    expect(html).toContain(">Continue with researched data</button>");
    const offline = renderToStaticMarkup(<ErrorNotice m={{ ...m, text: "Not connected.", kind: "offline" }} />);
    expect(offline).toContain(">Reconnect now</button>");
  });

  it("shows a banner with the attempt and Retry now, or New chat for a refused chat", () => {
    useChat.getState().setConn("closed", 3);
    expect(useChat.getState().connAttempt).toBe(3);
    const closed = renderToStaticMarkup(<ConnBanner conn="closed" attempt={useChat.getState().connAttempt} onNewChat={() => undefined} />);
    expect(closed).toContain("attempt 3");
    expect(closed).toContain(">Retry now</button>");
    const gone = renderToStaticMarkup(<ConnBanner conn="gone" attempt={0} onNewChat={() => undefined} />);
    expect(gone).toContain("can&#x27;t be opened here");
    expect(gone).toContain(">New chat</button>");
    for (const c of ["open", "mock", "connecting"] as ConnState[])
      expect(renderToStaticMarkup(<ConnBanner conn={c} attempt={2} onNewChat={() => undefined} />)).toBe("");
    useChat.getState().setConn("open", 5);
    expect(useChat.getState().connAttempt).toBe(0);
  });

  it("Retry now reconnects through the transport; refused chats do not reconnect", () => {
    const reconnect = vi.fn();
    useChat.getState().setTransport({ send: () => true, close: () => undefined, reconnect });
    useChat.getState().reconnect();
    expect(reconnect).toHaveBeenCalledOnce();
    expect([...GONE_CODES].sort()).toEqual([4403, 4404, 4410]);
  });
});

describe("F10 intake card", () => {
  const req = {
    type: "confirm_request", seq: 1, request_id: "r1", kind: "intake", text: "Is this right?",
    options: [{ id: "yes", label: "Yes, research these" }, { id: "stop", label: "Not now" }],
  } as never;
  const card = {
    cars: [
      {
        key: "car#1",
        display_name: "VW Golf GTI",
        items: [{ field: "gearbox", value: "DSG", basis: "STATED", options: ["DSG", "Manual"] }],
      },
    ],
    profile: [],
  } as never;
  const html = renderToStaticMarkup(<IntakeCard req={req} card={card} />);

  it("comes from AutoMind, like a reply", () => {
    expect(html).toMatch(/data-testid="card-from".*AutoMind.*Check before I research/);
  });

  it("says what each chip changes", () => {
    expect(html).toContain("Change gearbox to:");
    expect(html).toContain('aria-label="Change gearbox to Manual"');
    expect(html).toContain('aria-label="Gearbox: DSG (current)"');
  });

  it("separates confirming from editing: one primary action, the skip's consequence spelled out", () => {
    const actions = html.slice(html.indexOf('data-testid="card-actions"'));
    expect(actions).toContain("All correct?");
    expect(actions.match(/data-primary="true"/g)).toHaveLength(1);
    expect(actions).toMatch(/data-primary="true"[^>]*>Yes, research these/);
    expect(actions).toContain("“Not now” keeps the cars and answers from what AutoMind already knows");
    // the chips are above the actions, not among them
    expect(actions).not.toContain("Change gearbox to");
  });
});

describe("F11 report hierarchy", () => {
  const sugg = {
    type: "suggestions",
    items: [
      { id: "s1", label: "Compare insurance", request: { kind: "message", text: "Compare insurance" } },
      { id: "s2", label: "Find reliability data", request: { kind: "find", text: "Find reliability" } },
    ],
  } as never;

  it("labels next steps and leaves out the find step when the data panel has one", () => {
    const alone = renderToStaticMarkup(<Suggestions b={sugg} />);
    expect(alone).toContain("Next:");
    expect(alone).toContain('aria-label="Next steps"');
    expect(alone).toContain("Find reliability data");
    const withPanel = renderToStaticMarkup(
      <DataPanelPresent.Provider value={true}>
        <Suggestions b={sugg} />
      </DataPanelPresent.Provider>,
    );
    expect(withPanel).toContain("Compare insurance");
    expect(withPanel).not.toContain("Find reliability data");
  });

  it("styles quick replies as the user's answers", () => {
    const html = renderToStaticMarkup(
      <QuickReplies b={{ type: "quick_replies", question: "Track days?", items: [{ label: "Yes", text: "Yes" }] } as never} />,
    );
    expect(html).toContain("Your answer:");
    expect(html).toContain('aria-label="Quick answers"');
    expect(html).toContain("rounded-br-md");
  });
});

describe("F12 rating discoverability", () => {
  const b = VerdictBlockSchema.parse({
    type: "verdict", headline: "Golf GTI", pick_car_id: null, tie: false, confidence: "HIGH",
    confidence_reason: "all data", gaps: [],
  });

  it("the verdict points to the rating of its report", () => {
    const html = renderToStaticMarkup(
      <MessageIdContext.Provider value="m1">
        <Verdict b={b} />
      </MessageIdContext.Provider>,
    );
    expect(html).toContain("Rate this answer");
    expect(renderToStaticMarkup(<Verdict b={b} />)).not.toContain("Rate this answer");
    expect(renderToStaticMarkup(<RatingControl messageId="m1" />)).toContain('id="rate-m1"');
  });

  describe("remembers a rated report in this browser", () => {
    let store: Record<string, string>;
    beforeEach(() => {
      store = {};
      vi.stubGlobal("localStorage", {
        getItem: (k: string) => store[k] ?? null,
        setItem: (k: string, v: string) => void (store[k] = v),
        removeItem: (k: string) => void delete store[k],
      });
    });
    afterEach(() => vi.unstubAllGlobals());

    it("shows the thanks instead of the scale after a reload", () => {
      expect(wasRated("m2")).toBe(false);
      markRated("m2");
      expect(wasRated("m2")).toBe(true);
      const html = renderToStaticMarkup(<RatingControl messageId="m2" />);
      expect(html).toContain("Thanks");
      expect(html).not.toContain("useless");
    });
  });
});

describe("F13 mobile layout", () => {
  it("fits two cars of the spec table in a 390 px screen", () => {
    const px = (rem: string) => parseFloat(rem) * 16;
    expect(px(tableMinWidth(2))).toBeLessThanOrEqual(390 - 2 * 12);
    expect(px(tableMinWidth(4))).toBeGreaterThan(390);
  });
});

describe("F15 mock covers the flows", () => {
  it("the report flow fills the timeline and ends with replies and next steps", () => {
    const steps = reportFlow(new MockCase(), true).map((s) => s.msg);
    expect(steps.some((m) => m.type === "status" && String(m.text).startsWith("Resolved:"))).toBe(true);
    const report = steps.find((m) => m.type === "assistant_message") as { blocks: { type: string }[] };
    expect(report.blocks.map((b) => b.type)).toEqual(expect.arrayContaining(["quick_replies", "suggestions"]));
  });

  it("has the busy and overloaded errors and scenario links", () => {
    expect(errorFlow("busy").at(-1)!.msg.text).toMatch(/^busy:/);
    expect(errorFlow("overloaded").at(-1)!.msg.text).toMatch(/overloaded/);
    expect(errorScenario("show me the limit")).toBe("limit");
    expect(errorScenario("Compare Golf GTI and i30 N")).toBeNull();
    expect(scenarioText("busy")).toBe("show me the busy");
    expect(scenarioText(null)).toBeNull();
  });

  describe("mock transport", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("answers a cancel with turn_cancelled", () => {
      const got: { type?: string }[] = [];
      const t = createMockTransport({ onMessage: (m) => got.push(m as never), onState: () => undefined }, null);
      t.send({ type: "cancel", turn_id: "t1" });
      vi.runAllTimers();
      expect(got.map((m) => m.type)).toEqual(["turn_cancelled"]);
    });

    it("loses the connection in the reconnect scenario and comes back on Retry now", () => {
      const states: [ConnState, number | undefined][] = [];
      const t = createMockTransport({ onMessage: () => undefined, onState: (s, a) => states.push([s, a]) }, "reconnect");
      vi.advanceTimersByTime(1000);
      expect(states.at(-1)).toEqual(["closed", 3]);
      expect(t.send({ type: "user_message", message_id: "m", text: "hi" })).toBe(false);
      t.reconnect!();
      vi.runAllTimers();
      expect(states.at(-1)![0]).toBe("mock");
    });
  });
});

describe("F14 accessibility", () => {
  it("keeps Tab inside a dialog: wraps at both ends, leaves the middle alone", () => {
    const items = ["close", "chat1", "chat2"];
    expect(trapTarget(items, "chat2", false)).toBe("close");
    expect(trapTarget(items, "close", true)).toBe("chat2");
    expect(trapTarget(items, "chat1", false)).toBeNull();
    expect(trapTarget(items, null, false)).toBe("close"); // focus outside: back in
    expect(trapTarget([], null, false)).toBeNull();
  });

  it("a warning in a report is a note, not an alert", () => {
    const html = renderToStaticMarkup(<Notice b={{ type: "notice", level: "warning", text: "Few sources" } as never} />);
    expect(html).toContain('role="note"');
    expect(html).not.toContain('role="alert"');
  });

  it("errors stay alerts and offer their action", () => {
    const html = renderToStaticMarkup(
      <ErrorNotice m={{ role: "error", message_id: "e", created_at: "", text: "x", kind: "generic", retry: "q" }} />,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain(">Try again</button>");
  });
});
