import { describe, expect, it } from "vitest";
import { useChat } from "../store/chat";
import { en } from "./en";
import { es } from "./es";
import { UI_LANG, translate, uiLang } from "./index";
import { ru } from "./ru";

describe("spec 004 FR-024 interface language", () => {
  it("has every key in every language", () => {
    for (const d of [ru, es]) expect(Object.keys(d).sort()).toEqual(Object.keys(en).sort());
  });

  it("fills variables", () => {
    expect(translate("ru", "panel.values", { n: 12 })).toBe("12 значений");
    expect(translate("es", "retention.after", { n: 5 })).toBe("a 5 años");
  });

  it("still records the conversation language and a manual choice (for when translation is re-enabled)", () => {
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

describe("spec 010 FR-042 English interface", () => {
  it("pins the interface to English whatever the conversation or the manual choice", () => {
    expect(UI_LANG).toBe("en");
    expect(uiLang("ru", "es")).toBe("en");
    expect(uiLang(null, "ru")).toBe("en");
    expect(uiLang(null, null)).toBe("en");
  });

  it("keeps the assistant reply untouched: a Russian reply stays Russian, store texts stay English", () => {
    useChat.getState().newChat();
    const { handleRaw } = useChat.getState();
    handleRaw({
      type: "assistant_message", seq: 1, turn_id: "t1", message_id: "m2", created_at: "2026-11-05T10:00:00Z",
      text: "Отчёт по машинам", blocks: [], language: "ru",
    });
    handleRaw({ type: "turn_cancelled", seq: 2, turn_id: "t2" });
    const msgs = useChat.getState().messages;
    expect(msgs[0]).toMatchObject({ role: "assistant", text: "Отчёт по машинам" });
    expect(msgs[1]).toMatchObject({ role: "error", text: "Stopped." });
  });
});
