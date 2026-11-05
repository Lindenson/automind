/** Where the chat view scrolls after an update (spec 010 US10 "Answer starts at the top", audit F4). */
import type { UiMessage } from "../store/chat";

export type ScrollTarget = { kind: "message"; id: string } | { kind: "bottom" };

/**
 * A newly arrived assistant answer is shown from its start (the verdict), not from its end (the sources).
 * Everything else (a status line, the user's own message, a history load) keeps the view at the bottom.
 */
export function scrollTarget(prevCount: number, messages: UiMessage[]): ScrollTarget {
  const last = messages[messages.length - 1];
  if (messages.length === prevCount + 1 && last?.role === "assistant")
    return { kind: "message", id: last.message_id };
  return { kind: "bottom" };
}

/** The DOM id of a message, so the view can scroll to it. */
export const messageDomId = (id: string) => `msg-${id}`;
