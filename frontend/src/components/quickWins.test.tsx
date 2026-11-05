/** Spec 010 T088 (audit quick wins): behaviour that can be checked without a browser. */
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import { scrollTarget } from "../lib/scroll";
import type { ClientMsg } from "../lib/protocol";
import { useChat, type UiMessage } from "../store/chat";
import { ConfidenceDot, ProvenanceBadge } from "./badges";
import { textAfterSend } from "./Composer";
import { IntakeCard } from "./IntakeCard";
import { ProgressGrid } from "./ProgressGrid";
import { StatusTimeline } from "./StatusTimeline";
import { RatingControl, asksReasons, ratingNote } from "./RatingControl";
import { DataPanelPresent, Verdict } from "./blocks/Verdict";
import { VerdictBlockSchema } from "../lib/protocol";

const user = (id: string): UiMessage => ({ role: "user", message_id: id, created_at: "", text: "q", blocks: [] });
const answer = (id: string): UiMessage => ({ role: "assistant", message_id: id, created_at: "", text: "a", blocks: [] });

describe("a new answer is shown from its start (audit F4)", () => {
  it("targets the new assistant message", () => {
    expect(scrollTarget(1, [user("u1"), answer("a1")])).toEqual({ kind: "message", id: "a1" });
  });
  it("keeps the bottom for the user's own message, status updates and a history load", () => {
    expect(scrollTarget(0, [user("u1")])).toEqual({ kind: "bottom" });
    expect(scrollTarget(2, [user("u1"), answer("a1")])).toEqual({ kind: "bottom" });
    expect(scrollTarget(0, [user("u1"), answer("a1"), user("u2"), answer("a2")])).toEqual({ kind: "bottom" });
  });
});

describe("the composer keeps the text when sending fails (audit F8)", () => {
  beforeEach(() => {
    useChat.getState().newChat();
    useChat.setState({ pending: null });
  });

  it("clears only after a successful send", () => {
    expect(textAfterSend("Compare Golf and i30", true)).toBe("");
    expect(textAfterSend("Compare Golf and i30", false)).toBe("Compare Golf and i30");
  });

  it("send() reports whether the message went out", () => {
    const sent: ClientMsg[] = [];
    useChat.getState().setTransport({ send: () => false, close: () => undefined });
    expect(useChat.getState().send("hello")).toBe(false);
    expect(useChat.getState().messages.at(-1)).toMatchObject({ role: "error" });
    expect(useChat.getState().pending).toBeNull();

    useChat.getState().setTransport({ send: (m) => (sent.push(m), true), close: () => undefined });
    expect(useChat.getState().send("hello")).toBe(true);
    expect(sent).toHaveLength(1);
    // busy now: a second message is refused and stays in the composer
    expect(useChat.getState().send("again")).toBe(false);
    useChat.getState().setTransport(null);
  });
});

describe("rating anchors and reasons (audit F12)", () => {
  it("asks reasons only for ratings of 2 and below", () => {
    expect(asksReasons(null)).toBe(false);
    expect(asksReasons(1)).toBe(true);
    expect(asksReasons(2)).toBe(true);
    expect(asksReasons(3)).toBe(false);
  });

  it("puts the chosen reasons into the note, before the user's words", () => {
    expect(ratingNote(1, ["Wrong car or version", "Doubtful numbers"], " no GTI ")).toBe(
      "Wrong car or version; Doubtful numbers; no GTI",
    );
    expect(ratingNote(2, ["Didn't understand what I want"], "")).toBe("Didn't understand what I want");
    expect(ratingNote(4, ["Doubtful numbers"], "fine")).toBe("fine");
  });

  it("shows the scale anchors", () => {
    const html = renderToStaticMarkup(<RatingControl messageId="m1" />);
    expect(html).toContain("useless");
    expect(html).toContain("very useful");
    expect(html).toContain('role="group"');
  });
});

describe("badges and accessibility (audit F5, F14)", () => {
  it("gives the confidence dot a role and a name", () => {
    const html = renderToStaticMarkup(<ConfidenceDot c="LOW" />);
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="Confidence: low"');
  });

  it("uses theme tokens, not fixed Tailwind shades", () => {
    const html = renderToStaticMarkup(<ProvenanceBadge p="ASSUMPTION" />);
    expect(html).toContain("text-prov-assumption");
    expect(html).not.toMatch(/text-amber-\d00/);
  });
});

describe("intake card options (audit F10)", () => {
  it("marks the current value as selected", () => {
    const html = renderToStaticMarkup(
      <IntakeCard
        req={{ type: "confirm_request", seq: 1, request_id: "r1", kind: "intake", text: "Check", options: [] } as never}
        card={{
          cars: [
            {
              key: "car#1",
              display_name: "VW Golf GTI",
              items: [{ field: "gearbox", value: "DSG", basis: "STATED", options: ["DSG", "Manual"] }],
            },
          ],
          profile: [],
        } as never}
      />,
    );
    expect(html).toMatch(/aria-pressed="true"[^>]*>.*DSG/);
    expect(html).toMatch(/aria-pressed="false"[^>]*>Manual/);
  });

  it("says the card is being updated after an edit, not that a question is sent", () => {
    const pending = { userMessageId: "", startedAt: Date.now(), statuses: [] };
    expect(renderToStaticMarkup(<StatusTimeline pending={{ ...pending, kind: "edit" }} />)).toContain(
      "Updating the card with your change",
    );
    expect(renderToStaticMarkup(<StatusTimeline pending={pending} />)).toContain("Sending your question");
  });
});

describe("progress grid (audit F7, F9)", () => {
  it("has sentence-case areas, a legend and the elapsed time", () => {
    const html = renderToStaticMarkup(
      <ProgressGrid
        pending={{
          userMessageId: "",
          startedAt: Date.now(),
          statuses: [],
          grid: {
            "car#1|value_retention": {
              type: "progress", seq: 1, car: "Golf", car_key: "car#1", area: "value_retention", state: "done", round: 0,
            } as never,
          },
        }}
      />,
    );
    // the grid: sentence case (no CSS capitalize), a legend, the elapsed time
    expect(html).toContain("Value retention");
    expect(html).not.toContain("capitalize");
    expect(html).toContain("progress-legend");
    expect(html).toContain("✓ found");
    expect(html).toContain("progress-elapsed");
  });
});

describe("one find action per report (audit F11)", () => {
  const b = VerdictBlockSchema.parse({
    type: "verdict",
    headline: "Golf GTI",
    pick_car_id: null,
    tie: false,
    confidence: "MEDIUM",
    confidence_reason: "some data missing",
    gaps: ["reliability"],
  });
  it("shows the verdict's button without a data panel and hides it with one", () => {
    expect(renderToStaticMarkup(<Verdict b={b} />)).toContain("Find the missing data");
    const withPanel = renderToStaticMarkup(
      <DataPanelPresent.Provider value={true}>
        <Verdict b={b} />
      </DataPanelPresent.Provider>,
    );
    expect(withPanel).not.toContain("Find the missing data");
  });
});
