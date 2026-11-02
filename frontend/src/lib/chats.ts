/** Chat deletion client (spec 003 US4): one request for one or many chats; forgets their replay position. */
import { clearLastSeq } from "./transport";

export async function deleteChats(ids: string[], fetchFn: typeof fetch = fetch): Promise<string[]> {
  if (ids.length === 0) return [];
  const r = await fetchFn("/api/v1/chats/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!r.ok) throw new Error(`delete failed: HTTP ${r.status}`);
  const body = (await r.json()) as { deleted?: string[] };
  for (const id of ids) clearLastSeq(id); // already-deleted ids are gone too
  return body.deleted ?? [];
}
