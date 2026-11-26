/** Chat 6e001ee0: the version question's "another one (I'll type it)" chip puts the cursor in the composer. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QuickRepliesBlockSchema } from "../../lib/protocol";
import { useChat } from "../../store/chat";
import { QuickReplies } from "./QuickReplies";

describe("typing chip", () => {
  const b = QuickRepliesBlockSchema.parse({
    type: "quick_replies",
    items: [
      { label: "1.6 PHEV · двигатель 118 kW · 2024–", text: "1.6 PHEV · двигатель 118 kW · 2024–" },
      { label: "Другая (напишу)", text: "Другая (напишу)", typing: true },
      { label: "Выбери сам", text: "Выбери сам" },
    ],
  });

  it("is parsed and drawn apart from the answers that are sent", () => {
    expect(b.items[1]?.typing).toBe(true);
    expect(b.items[0]?.typing).toBeUndefined();
    const html = renderToStaticMarkup(<QuickReplies b={b} />);
    expect(html).toContain("Другая (напишу)");
    expect(html.match(/border-dashed/g)?.length).toBe(1);
  });
});

describe("option ids (spec 013 T013)", () => {
  it("a chip with an id sends the id with its text; one without sends the text only", () => {
    const sent: unknown[] = [];
    useChat.getState().newChat();
    useChat.setState({ pending: null, transport: null });
    useChat.getState().setTransport({
      send: (m: unknown) => (sent.push(m), true),
      close: () => undefined,
      reconnect: () => undefined,
    });
    useChat.getState().send("E 200", "q:car#1:ENGINE:0");
    useChat.setState({ pending: null });
    useChat.getState().send("какой-то текст");
    expect(sent[0]).toMatchObject({ type: "user_message", text: "E 200", option_id: "q:car#1:ENGINE:0" });
    expect(sent[1]).not.toHaveProperty("option_id");
  });

  it("the id is kept when the block is parsed", () => {
    const b = QuickRepliesBlockSchema.parse({
      type: "quick_replies",
      items: [{ id: "condition:NEW", label: "Новые", text: "Новые" }],
    });
    expect(b.items[0]?.id).toBe("condition:NEW");
  });
});
