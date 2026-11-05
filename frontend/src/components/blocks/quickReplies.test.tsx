/** Chat 6e001ee0: the version question's "another one (I'll type it)" chip puts the cursor in the composer. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QuickRepliesBlockSchema } from "../../lib/protocol";
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
