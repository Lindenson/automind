/** Spec 010 T026 (US2): "bad source" on an accepted source of an answer (contracts/ws-feedback.md). */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FeedbackAckSchema, parseServerMsg, type ClientMsg, type SourceRef } from "../lib/protocol";
import { badSourceKey, useChat } from "../store/chat";
import { BadSourceButton, MessageIdContext, SourceItem } from "./badges";

const src: SourceRef = {
  name: "Golf GTI data sheet",
  url: "https://example.com/golf",
  type: "SPEC_DATABASE",
  retrieved_at: "2026-11-01T10:00:00Z",
};

let sent: ClientMsg[] = [];
const fakeSocket = () => {
  sent = [];
  useChat.getState().setTransport({ send: (m) => (sent.push(m), true), close: () => undefined });
};

beforeEach(() => {
  useChat.getState().newChat();
  fakeSocket();
});
afterEach(() => useChat.getState().setTransport(null));

describe("protocol", () => {
  it("parses feedback_ack, with and without ignored", () => {
    expect(parseServerMsg({ type: "feedback_ack", kind: "bad_source", url: "https://x" })).toMatchObject({
      type: "feedback_ack",
      url: "https://x",
    });
    expect(FeedbackAckSchema.parse({ type: "feedback_ack", kind: "bad_source", url: "u", ignored: true }).ignored).toBe(true);
    expect(parseServerMsg({ type: "feedback_ack", kind: "rating", url: "u" })).toBeNull();
  });
});

describe("badSource store action", () => {
  it("sends the contract payload and marks the source pending", () => {
    const ok = useChat.getState().badSource({
      messageId: "m1",
      url: src.url,
      carId: "car#1",
      attribute: "power_kw",
      area: "specs",
    });
    expect(ok).toBe(true);
    expect(sent).toEqual([
      { type: "bad_source", message_id: "m1", url: src.url, car_id: "car#1", attribute: "power_kw", area: "specs" },
    ]);
    expect(useChat.getState().badSources[badSourceKey("m1", src.url)]).toBe("pending");
  });

  it("omits the optional fields it does not have and does not send twice", () => {
    useChat.getState().badSource({ messageId: "m1", url: src.url });
    useChat.getState().badSource({ messageId: "m1", url: src.url });
    expect(sent).toEqual([{ type: "bad_source", message_id: "m1", url: src.url }]);
  });

  it("does nothing without a socket", () => {
    useChat.getState().setTransport(null);
    expect(useChat.getState().badSource({ messageId: "m1", url: src.url })).toBe(false);
    expect(useChat.getState().badSources).toEqual({});
  });

  it("marks it noted on the ack, or ignored", () => {
    useChat.getState().badSource({ messageId: "m1", url: src.url });
    useChat.getState().badSource({ messageId: "m2", url: "https://other.example" });
    useChat.getState().handleRaw({ type: "feedback_ack", kind: "bad_source", url: src.url });
    useChat.getState().handleRaw({ type: "feedback_ack", kind: "bad_source", url: "https://other.example", ignored: true });
    expect(useChat.getState().badSources).toEqual({
      [badSourceKey("m1", src.url)]: "noted",
      [badSourceKey("m2", "https://other.example")]: "ignored",
    });
  });
});

describe("SourceItem bad source action", () => {
  it("shows the action on an accepted source of a message", () => {
    const html = renderToStaticMarkup(<SourceItem s={src} messageId="m1" />);
    expect(html).toContain('aria-label="Mark this source as bad"');
    expect(html).toContain("bad source");
  });

  it("takes the message id from the rendering message", () => {
    const html = renderToStaticMarkup(
      <MessageIdContext.Provider value="m1">
        <SourceItem s={src} />
      </MessageIdContext.Provider>,
    );
    expect(html).toContain('aria-label="Mark this source as bad"');
  });

  it("hides it without a message id, a url, or on a rejected source", () => {
    expect(renderToStaticMarkup(<SourceItem s={src} />)).not.toContain("Mark this source as bad");
    expect(renderToStaticMarkup(<SourceItem s={{ ...src, url: "" }} messageId="m1" />)).not.toContain(
      "Mark this source as bad",
    );
    expect(
      renderToStaticMarkup(<SourceItem s={{ ...src, rejected: { reason: "other variant" } }} messageId="m1" />),
    ).not.toContain("Mark this source as bad");
  });

  // static rendering reads the store's initial state, so the states are checked on the button itself
  it("turns into a disabled 'noted ✓' after the ack, or 'not recorded' when ignored", () => {
    const idle = renderToStaticMarkup(<BadSourceButton />);
    expect(idle).not.toMatch(/ disabled=""/);
    expect(idle).toContain("<svg");

    const noted = renderToStaticMarkup(<BadSourceButton state="noted" />);
    expect(noted).toContain("noted ✓");
    expect(noted).toMatch(/ disabled=""/);

    const ignored = renderToStaticMarkup(<BadSourceButton state="ignored" />);
    expect(ignored).toContain("not recorded");
    expect(ignored).toMatch(/ disabled=""/);

    expect(renderToStaticMarkup(<BadSourceButton state="pending" />)).toMatch(/ disabled=""/);
  });
});
