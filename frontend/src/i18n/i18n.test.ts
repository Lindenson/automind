import { describe, expect, it } from "vitest";
import { useChat } from "../store/chat";
import { en } from "./en";
import { es } from "./es";
import { translate } from "./index";
import { ru } from "./ru";

describe("spec 004 FR-024 interface language", () => {
  it("has every key in every language", () => {
    for (const d of [ru, es]) expect(Object.keys(d).sort()).toEqual(Object.keys(en).sort());
  });

  it("fills variables", () => {
    expect(translate("ru", "panel.values", { n: 12 })).toBe("12 значений");
    expect(translate("es", "retention.after", { n: 5 })).toBe("a 5 años");
  });

  it("follows the conversation, and a manual choice wins", () => {
    useChat.getState().newChat();
    useChat.getState().setLang(null);
    useChat.getState().handleRaw({
      type: "assistant_message", seq: 1, turn_id: "t1", message_id: "m1", created_at: "2026-11-03T10:00:00Z",
      text: "Отчёт", blocks: [], language: "ru",
    });
    expect(useChat.getState().convoLang).toBe("ru");
    useChat.getState().setLang("es");
    expect(useChat.getState().manualLang).toBe("es");
    useChat.getState().setLang(null);
  });
});
