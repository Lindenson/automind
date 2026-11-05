/** Spec 010 T044: state of the admin page (zustand). */
import { create } from "zustand";
import { ForbiddenError, adminApi, setToken, type SourceAction } from "./api";
import type { Change, ProblemDetail, ProblemItem, SourceDetail, SourceList, StatusPatch } from "./schemas";

export type AdminTab = "problems" | "sources";

interface AdminState {
  tab: AdminTab;
  /** The server refused the token: show the token prompt. */
  needToken: boolean;
  problems: ProblemItem[] | null;
  loading: boolean;
  error: string | null;
  openId: string | null;
  detail: ProblemDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  saving: boolean;

  /** Sources screen (US7, FR-028). */
  area: string;
  sources: SourceList | null;
  sourcesLoading: boolean;
  sourcesError: string | null;
  changes: Change[] | null;
  changesError: string | null;
  /** The refusal text of the last revert, by change id. */
  revertErrors: Record<string, string>;
  reverting: string | null;
  openDomain: string | null;
  sourceDetail: SourceDetail | null;
  sourceLoading: boolean;
  sourceError: string | null;
  sourceSaving: boolean;

  setTab: (tab: AdminTab) => void;
  submitToken: (token: string) => Promise<void>;
  loadProblems: () => Promise<void>;
  openProblem: (id: string) => Promise<void>;
  closeProblem: () => void;
  setStatus: (id: string, patch: StatusPatch) => Promise<boolean>;

  setArea: (area: string) => Promise<void>;
  loadSources: () => Promise<void>;
  openSource: (domain: string) => Promise<void>;
  closeSource: () => void;
  sourceAction: (domain: string, action: SourceAction) => Promise<boolean>;
  revertChange: (id: string) => Promise<boolean>;
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export const useAdmin = create<AdminState>((set, get) => {
  /** A 403 anywhere switches to the token prompt; other errors come back as text. */
  const fail = (e: unknown): string | null => {
    if (e instanceof ForbiddenError) {
      set({ needToken: true, openId: null, detail: null, openDomain: null, sourceDetail: null });
      return null;
    }
    return message(e);
  };

  return {
    tab: "problems",
    needToken: false,
    problems: null,
    loading: false,
    error: null,
    openId: null,
    detail: null,
    detailLoading: false,
    detailError: null,
    saving: false,

    area: "specs",
    sources: null,
    sourcesLoading: false,
    sourcesError: null,
    changes: null,
    changesError: null,
    revertErrors: {},
    reverting: null,
    openDomain: null,
    sourceDetail: null,
    sourceLoading: false,
    sourceError: null,
    sourceSaving: false,

    setTab: (tab) => set({ tab }),

    submitToken: async (token) => {
      setToken(token.trim());
      set({ needToken: false, error: null, sourcesError: null });
      await (get().tab === "sources" ? get().loadSources() : get().loadProblems());
    },

    setArea: async (area) => {
      set({ area, sources: null, changes: null, revertErrors: {} });
      await get().loadSources();
    },

    loadSources: async () => {
      const area = get().area;
      set({ sourcesLoading: true, sourcesError: null, changesError: null });
      const [list, changes] = await Promise.allSettled([adminApi.sources(area), adminApi.changes(area, 30)]);
      if (get().area !== area) return; // the owner switched area meanwhile
      const next: Partial<AdminState> = { sourcesLoading: false };
      if (list.status === "fulfilled") next.sources = list.value;
      else next.sourcesError = fail(list.reason);
      if (changes.status === "fulfilled") next.changes = changes.value;
      else next.changesError = fail(changes.reason);
      set(next);
    },

    openSource: async (domain) => {
      set({ openDomain: domain, sourceDetail: null, sourceLoading: true, sourceError: null });
      try {
        const sourceDetail = await adminApi.source(domain);
        if (get().openDomain === domain) set({ sourceDetail, sourceLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().openDomain === domain) set({ sourceLoading: false, sourceError: err });
      }
    },

    closeSource: () => set({ openDomain: null, sourceDetail: null, sourceError: null, sourceLoading: false }),

    sourceAction: async (domain, action) => {
      set({ sourceSaving: true, sourceError: null });
      try {
        await adminApi.sourceAction(domain, action);
        set({ sourceSaving: false });
        const detail = await adminApi.source(domain).catch(() => null);
        if (detail && get().openDomain === domain) set({ sourceDetail: detail });
        void get().loadSources();
        return true;
      } catch (e) {
        set({ sourceSaving: false, sourceError: fail(e) });
        return false;
      }
    },

    revertChange: async (id) => {
      const rest = { ...get().revertErrors };
      delete rest[id];
      set({ reverting: id, revertErrors: rest });
      try {
        await adminApi.revert(id);
        set({ reverting: null });
        void get().loadSources();
        const domain = get().openDomain;
        if (domain) {
          const detail = await adminApi.source(domain).catch(() => null);
          if (detail && get().openDomain === domain) set({ sourceDetail: detail });
        }
        return true;
      } catch (e) {
        const err = fail(e);
        set((s) => ({ reverting: null, revertErrors: err ? { ...s.revertErrors, [id]: err } : s.revertErrors }));
        return false;
      }
    },

    loadProblems: async () => {
      set({ loading: true, error: null });
      try {
        const problems = await adminApi.problems();
        set({ problems, loading: false });
      } catch (e) {
        set({ loading: false, error: fail(e) });
      }
    },

    openProblem: async (id) => {
      set({ openId: id, detail: null, detailLoading: true, detailError: null });
      try {
        const detail = await adminApi.problem(id);
        if (get().openId === id) set({ detail, detailLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().openId === id) set({ detailLoading: false, detailError: err });
      }
    },

    closeProblem: () => set({ openId: null, detail: null, detailError: null, detailLoading: false }),

    setStatus: async (id, patch) => {
      set({ saving: true, detailError: null });
      try {
        await adminApi.setStatus(id, patch);
        set({ saving: false });
        const detail = await adminApi.problem(id).catch(() => null);
        if (detail && get().openId === id) set({ detail });
        void get().loadProblems();
        return true;
      } catch (e) {
        set({ saving: false, detailError: fail(e) });
        return false;
      }
    },
  };
});
