/** Spec 010 T044/T045: admin schemas, the fetch layer and the problem badges (no browser needed). */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOKEN_KEY, adminApi, getToken } from "./api";
import { FixBadge, fixTarget, frequency } from "./badges";
import { ProblemDetailView } from "./ProblemCard";
import { ProblemRow } from "./Problems";
import { ProblemDetailSchema, ProblemListSchema } from "./schemas";
import { useAdmin } from "./store";

/** The example of GET /problems in contracts/admin-api.md. */
const LIST = [
  {
    id: "…",
    rank: 1,
    title: "Rephrased comparison requests in Russian",
    component: "dialogue",
    status: "open",
    impact: 23.0,
    failing_turns_7d: 9,
    chats_7d: 4,
    example_chat: "20b5b7f9…",
    fix: {
      kind: "config",
      config_file: "questions.yaml",
      config_key: "ASK_BUDGET.ru",
      suggested_value: "…",
      direction: null,
      files: [],
    },
  },
];

const DETAIL = {
  ...LIST[0],
  key: "dialogue/not_understood/compare/ru",
  count_total: 14,
  count_7d: 9,
  first_seen: "2026-10-20T10:00:00Z",
  last_seen: "2026-11-04T10:00:00Z",
  examples: [{ chat: "20b5b7f9", turn: "t1", quote: "<b>сравни</b> **их**", url: null, claim: null }],
  diagnosis: {
    summary: "Rephrased comparisons are not recognised.",
    likely_cause: "The budget question template lacks the Russian variant.",
    fix: LIST[0]!.fix,
    verify: "Ask 'сравни их' in a new chat.",
  },
  status_history: [{ at: "2026-11-01T00:00:00Z", status: "acknowledged", author: "owner" }],
  copy_text: "## Task\nFix it.",
};

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("admin schemas parse the contract examples", () => {
  it("GET /problems", () => {
    const [p] = ProblemListSchema.parse(LIST);
    expect(p).toMatchObject({ rank: 1, failing_turns_7d: 9, chats_7d: 4 });
    expect(p!.fix).toMatchObject({ kind: "config", config_file: "questions.yaml", config_key: "ASK_BUDGET.ru" });
  });

  it("an undiagnosed problem has fix null", () => {
    const [p] = ProblemListSchema.parse([{ ...LIST[0], fix: null }]);
    expect(p!.fix).toBeNull();
  });

  it("GET /problems/{id}: examples and history field names are normalised", () => {
    const d = ProblemDetailSchema.parse(DETAIL);
    expect(d.examples[0]).toMatchObject({ chat_id: "20b5b7f9", turn_id: "t1" });
    expect(d.history[0]).toMatchObject({ status: "acknowledged" });
    expect(d.diagnosis?.fix?.kind).toBe("config");
    expect(d.copy_text).toContain("Fix it.");
  });

  it("rejects an unknown fix kind", () => {
    expect(() => ProblemListSchema.parse([{ ...LIST[0], fix: { kind: "magic" } }])).toThrow();
  });
});

describe("admin fetch layer", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useAdmin.setState({ needToken: false, problems: null, error: null, openId: null, detail: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the token as a bearer header", async () => {
    sessionStorage.setItem(TOKEN_KEY, "s3cret");
    fetchMock.mockResolvedValue(json(200, LIST));
    const items = await adminApi.problems();
    expect(items).toHaveLength(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/problems");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer s3cret");
  });

  it("sends no Authorization header without a token (loopback)", async () => {
    fetchMock.mockResolvedValue(json(200, []));
    await adminApi.problems();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("a 403 clears the token and asks for a new one", async () => {
    sessionStorage.setItem(TOKEN_KEY, "stale");
    fetchMock.mockResolvedValue(json(403, { detail: "forbidden" }));
    await useAdmin.getState().loadProblems();
    expect(getToken()).toBeNull();
    expect(useAdmin.getState().needToken).toBe(true);
    expect(useAdmin.getState().error).toBeNull();
  });

  it("submitting a token stores it and reloads", async () => {
    useAdmin.setState({ needToken: true });
    fetchMock.mockResolvedValue(json(200, LIST));
    await useAdmin.getState().submitToken(" fresh ");
    expect(getToken()).toBe("fresh");
    expect(useAdmin.getState().needToken).toBe(false);
    expect(useAdmin.getState().problems).toHaveLength(1);
  });

  it("PATCH sends the status and commit ref", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    fetchMock.mockResolvedValue(json(200, DETAIL));
    useAdmin.setState({ openId: "…" });
    expect(await useAdmin.getState().setStatus("…", { status: "fixed", fixed_ref: "abc123" })).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/problems/%E2%80%A6");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ status: "fixed", fixed_ref: "abc123" });
  });

  it("other errors show the server's detail", async () => {
    fetchMock.mockResolvedValue(json(500, { detail: "db down" }));
    await useAdmin.getState().loadProblems();
    expect(useAdmin.getState().error).toBe("db down");
    expect(useAdmin.getState().needToken).toBe(false);
  });
});

describe("fix badges and rows", () => {
  it("config shows file: key", () => {
    const [p] = ProblemListSchema.parse(LIST);
    const html = renderToStaticMarkup(<FixBadge fix={p!.fix} />);
    expect(html).toContain(">config<");
    expect(html).toContain("questions.yaml: ASK_BUDGET.ru");
  });

  it("code shows the first file", () => {
    const [p] = ProblemListSchema.parse([
      { ...LIST[0], fix: { kind: "code", files: ["app/dialogue.py", "app/x.py"], direction: "handle it" } },
    ]);
    const html = renderToStaticMarkup(<FixBadge fix={p!.fix} />);
    expect(html).toContain(">code<");
    expect(html).toContain("app/dialogue.py +1");
    expect(fixTarget(p!.fix!)).toBe("app/dialogue.py +1");
  });

  it("no fix reads not diagnosed", () => {
    expect(renderToStaticMarkup(<FixBadge fix={null} />)).toContain("not diagnosed");
  });

  it("a row shows rank, frequency and the example chat", () => {
    const [p] = ProblemListSchema.parse(LIST);
    const html = renderToStaticMarkup(<ProblemRow p={p!} onOpen={() => undefined} />);
    expect(html).toContain(frequency(9, 4));
    expect(frequency(9, 4)).toBe("9 in 7 days · 4 chats");
    expect(frequency(1, 1)).toBe("1 in 7 days · 1 chat");
    expect(html).toContain("impact 23<");
    expect(html).toContain("20b5b7f9");
  });

  it("the card renders quotes as plain text, never HTML or markdown", () => {
    const d = ProblemDetailSchema.parse(DETAIL);
    const html = renderToStaticMarkup(<ProblemDetailView detail={d} />);
    expect(html).toContain("&lt;b&gt;сравни&lt;/b&gt; **их**");
    expect(html).not.toContain("<b>сравни</b>");
    expect(html).toContain("ASK_BUDGET.ru");
    expect(html).toContain("Copy for Claude Code");
    expect(html).toContain("Status history");
  });
});
