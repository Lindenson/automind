import { describe, expect, it, vi } from "vitest";
import { deleteChats } from "./chats";

describe("deleteChats", () => {
  it("posts the ids once and returns the deleted ones", async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify({ deleted: ["a"], counts: {} }), { status: 200 }));
    expect(await deleteChats(["a", "b"], fetchFn as unknown as typeof fetch)).toEqual(["a"]);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const init = (fetchFn.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body))).toEqual({ ids: ["a", "b"] });
  });

  it("does nothing for an empty selection and throws on server errors", async () => {
    const fetchFn = vi.fn(async () => new Response("{}", { status: 500 }));
    expect(await deleteChats([], fetchFn as unknown as typeof fetch)).toEqual([]);
    await expect(deleteChats(["x"], fetchFn as unknown as typeof fetch)).rejects.toThrow();
  });
});
