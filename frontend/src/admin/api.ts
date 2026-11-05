/** Spec 010 T044: typed fetch layer of the admin page. Every call carries the admin token (FR-025). */
import type { z } from "zod";
import {
  ChangeListSchema,
  ProblemDetailSchema,
  ProblemListSchema,
  SourceDetailSchema,
  SourceListSchema,
  StatusPatchSchema,
  type Change,
  type ProblemDetail,
  type ProblemItem,
  type SourceDetail,
  type SourceList,
  type StatusPatch,
} from "./schemas";

export const TOKEN_KEY = "automind.admin_token";
export const ADMIN_BASE = "/api/v1/admin";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage blocked: the server may still allow loopback without a token */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing stored */
  }
}

/** The server refused the token (403): it is cleared and the page asks for a new one. */
export class ForbiddenError extends Error {
  constructor() {
    super("forbidden");
    this.name = "ForbiddenError";
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Fetch `path` under the admin base with the bearer token; parse the body with `schema` (or ignore it). */
export async function adminFetch<S extends z.ZodTypeAny>(
  path: string,
  schema: S | null,
  init: RequestInit = {},
): Promise<z.infer<S>> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${ADMIN_BASE}${path}`, { ...init, headers, credentials: "same-origin" });
  if (res.status === 403) {
    clearToken();
    throw new ForbiddenError();
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (!schema) return undefined as z.infer<S>;
  return schema.parse(await res.json());
}

export const adminApi = {
  problems: (): Promise<ProblemItem[]> => adminFetch("/problems", ProblemListSchema),
  problem: (id: string): Promise<ProblemDetail> =>
    adminFetch(`/problems/${encodeURIComponent(id)}`, ProblemDetailSchema),
  setStatus: (id: string, patch: StatusPatch): Promise<void> =>
    adminFetch(`/problems/${encodeURIComponent(id)}`, null, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(StatusPatchSchema.parse(patch)),
    }),

  sources: (area: string): Promise<SourceList> =>
    adminFetch(`/sources?area=${encodeURIComponent(area)}`, SourceListSchema),
  changes: (area: string, days = 30): Promise<Change[]> =>
    adminFetch(`/sources/changes?days=${days}&area=${encodeURIComponent(area)}`, ChangeListSchema),
  source: (domain: string): Promise<SourceDetail> =>
    adminFetch(`/sources/${encodeURIComponent(domain)}`, SourceDetailSchema),
  /** Owner actions on a whole source: freeze, unfreeze, block. */
  sourceAction: (domain: string, action: SourceAction): Promise<void> =>
    adminFetch(`/sources/${encodeURIComponent(domain)}/${action}`, null, { method: "POST" }),
  /** Revert a journal entry; a refusal comes back as ApiError(409) with the server's reason. */
  revert: (changeId: string): Promise<void> =>
    adminFetch(`/sources/changes/${encodeURIComponent(changeId)}/revert`, null, { method: "POST" }),
};

export type SourceAction = "freeze" | "unfreeze" | "block";
