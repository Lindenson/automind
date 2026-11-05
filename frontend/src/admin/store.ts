/** Spec 010 T044: state of the admin page (zustand); spec 011 T116 adds Parsers, Changes and Accuracy. */
import { create } from "zustand";
import {
  ForbiddenError,
  adminApi,
  setToken,
  type ChangeAction,
  type JournalFilter,
  type ParserAction,
  type SourceAction,
} from "./api";
import type {
  Accuracy,
  Change,
  EngineStatus,
  JournalChange,
  JournalChangeDetail,
  ParserDetail,
  ParserItem,
  ProblemDetail,
  ProblemItem,
  SourceDetail,
  SourceList,
  StatusPatch,
  ValueDetail,
  WrongValue,
} from "./schemas";

export type AdminTab = "problems" | "sources" | "parsers" | "changes" | "accuracy";

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

  /** Engine status strip in the header (spec 011 T116). */
  engine: EngineStatus | null;
  loadEngine: () => Promise<void>;

  /** Parsers screen (T117). */
  parsers: ParserItem[] | null;
  parsersLoading: boolean;
  parsersError: string | null;
  openReader: string | null;
  parserDetail: ParserDetail | null;
  parserLoading: boolean;
  parserError: string | null;
  parserSaving: boolean;
  loadParsers: () => Promise<void>;
  openParser: (reader: string) => Promise<void>;
  closeParser: () => void;
  parserAction: (reader: string, action: ParserAction) => Promise<boolean>;
  rollbackParser: (reader: string, to: string) => Promise<boolean>;

  /** Changes screen (T118). */
  journal: JournalChange[] | null;
  journalFilter: JournalFilter;
  journalLoading: boolean;
  journalError: string | null;
  openChangeId: string | null;
  changeDetail: JournalChangeDetail | null;
  changeLoading: boolean;
  changeError: string | null;
  changeSaving: boolean;
  loadJournal: () => Promise<void>;
  setJournalFilter: (filter: JournalFilter) => Promise<void>;
  openChange: (id: string) => Promise<void>;
  closeChange: () => void;
  changeAction: (id: string, action: ChangeAction) => Promise<boolean>;
  forbidSimilar: (id: string, days: number | null) => Promise<boolean>;

  /** Accuracy drill-down (T119): KPI → component (click 1) → value (click 2) → page and quote (click 3). */
  accuracy: Accuracy | null;
  accuracyLoading: boolean;
  accuracyError: string | null;
  component: string | null;
  wrongValues: WrongValue[] | null;
  claimId: string | null;
  valueDetail: ValueDetail | null;
  pageText: string | null;
  drillLoading: boolean;
  drillError: string | null;
  loadAccuracy: () => Promise<void>;
  openComponent: (component: string) => Promise<void>;
  openValue: (claimId: string) => Promise<void>;
  drillBack: () => void;
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export const useAdmin = create<AdminState>((set, get) => {
  /** A 403 anywhere switches to the token prompt; other errors come back as text. */
  const fail = (e: unknown): string | null => {
    if (e instanceof ForbiddenError) {
      set({
        needToken: true,
        openId: null,
        detail: null,
        openDomain: null,
        sourceDetail: null,
        openReader: null,
        parserDetail: null,
        openChangeId: null,
        changeDetail: null,
      });
      return null;
    }
    return message(e);
  };

  /** An owner action on a parser: refresh its card and the list; a refusal shows on the card. */
  const ownerStep = async (reader: string, call: () => Promise<void>): Promise<boolean> => {
    set({ parserSaving: true, parserError: null });
    try {
      await call();
      set({ parserSaving: false });
      const detail = await adminApi.parser(reader).catch(() => null);
      if (detail && get().openReader === reader) set({ parserDetail: detail });
      void get().loadParsers();
      return true;
    } catch (e) {
      set({ parserSaving: false, parserError: fail(e) });
      return false;
    }
  };

  /** An owner action on a journalled change: refresh its card, the journal and the strip. */
  const changeStep = async (id: string, call: () => Promise<void>): Promise<boolean> => {
    set({ changeSaving: true, changeError: null });
    try {
      await call();
      set({ changeSaving: false });
      const detail = await adminApi.journalChange(id).catch(() => null);
      if (detail && get().openChangeId === id) set({ changeDetail: detail });
      void get().loadJournal();
      void get().loadEngine();
      return true;
    } catch (e) {
      set({ changeSaving: false, changeError: fail(e) });
      return false;
    }
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
      set({ needToken: false, error: null, sourcesError: null, parsersError: null, journalError: null, accuracyError: null });
      const load = {
        problems: get().loadProblems,
        sources: get().loadSources,
        parsers: get().loadParsers,
        changes: get().loadJournal,
        accuracy: get().loadAccuracy,
      }[get().tab];
      await Promise.all([load(), get().loadEngine()]);
    },

    engine: null,
    loadEngine: async () => {
      try {
        set({ engine: await adminApi.engine() });
      } catch (e) {
        if (e instanceof ForbiddenError) fail(e); // the strip is optional: other errors leave it empty
      }
    },

    parsers: null,
    parsersLoading: false,
    parsersError: null,
    openReader: null,
    parserDetail: null,
    parserLoading: false,
    parserError: null,
    parserSaving: false,

    loadParsers: async () => {
      set({ parsersLoading: true, parsersError: null });
      try {
        set({ parsers: await adminApi.parsers(), parsersLoading: false });
      } catch (e) {
        set({ parsersLoading: false, parsersError: fail(e) });
      }
    },

    openParser: async (reader) => {
      set({ openReader: reader, parserDetail: null, parserLoading: true, parserError: null });
      try {
        const parserDetail = await adminApi.parser(reader);
        if (get().openReader === reader) set({ parserDetail, parserLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().openReader === reader) set({ parserLoading: false, parserError: err });
      }
    },

    closeParser: () => set({ openReader: null, parserDetail: null, parserError: null, parserLoading: false }),

    parserAction: async (reader, action) => ownerStep(reader, () => adminApi.parserAction(reader, action)),
    rollbackParser: async (reader, to) => ownerStep(reader, () => adminApi.rollbackParser(reader, to)),

    journal: null,
    journalFilter: {},
    journalLoading: false,
    journalError: null,
    openChangeId: null,
    changeDetail: null,
    changeLoading: false,
    changeError: null,
    changeSaving: false,

    loadJournal: async () => {
      const filter = get().journalFilter;
      set({ journalLoading: true, journalError: null });
      try {
        const journal = await adminApi.journal(filter);
        if (get().journalFilter === filter) set({ journal, journalLoading: false });
      } catch (e) {
        set({ journalLoading: false, journalError: fail(e) });
      }
    },

    setJournalFilter: async (filter) => {
      set({ journalFilter: filter });
      await get().loadJournal();
    },

    openChange: async (id) => {
      set({ openChangeId: id, changeDetail: null, changeLoading: true, changeError: null });
      try {
        const changeDetail = await adminApi.journalChange(id);
        if (get().openChangeId === id) set({ changeDetail, changeLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().openChangeId === id) set({ changeLoading: false, changeError: err });
      }
    },

    closeChange: () => set({ openChangeId: null, changeDetail: null, changeError: null, changeLoading: false }),

    changeAction: async (id, action) => changeStep(id, () => adminApi.changeAction(id, action)),
    forbidSimilar: async (id, days) => changeStep(id, () => adminApi.forbidSimilar(id, days)),

    accuracy: null,
    accuracyLoading: false,
    accuracyError: null,
    component: null,
    wrongValues: null,
    claimId: null,
    valueDetail: null,
    pageText: null,
    drillLoading: false,
    drillError: null,

    loadAccuracy: async () => {
      set({ accuracyLoading: true, accuracyError: null });
      try {
        set({ accuracy: await adminApi.accuracy(30), accuracyLoading: false });
      } catch (e) {
        set({ accuracyLoading: false, accuracyError: fail(e) });
      }
    },

    openComponent: async (component) => {
      set({ component, wrongValues: null, claimId: null, valueDetail: null, pageText: null, drillLoading: true, drillError: null });
      try {
        const wrongValues = await adminApi.wrongValues(component, 30);
        if (get().component === component) set({ wrongValues, drillLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().component === component) set({ drillLoading: false, drillError: err });
      }
    },

    openValue: async (claimId) => {
      set({ claimId, valueDetail: null, pageText: null, drillLoading: true, drillError: null });
      try {
        const valueDetail = await adminApi.value(claimId);
        if (get().claimId !== claimId) return;
        set({ valueDetail });
        const sid = valueDetail.snapshot?.id;
        const pageText = sid ? await adminApi.snapshotText(sid, valueDetail.quote).catch(() => null) : null;
        if (get().claimId === claimId) set({ pageText, drillLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().claimId === claimId) set({ drillLoading: false, drillError: err });
      }
    },

    drillBack: () => {
      if (get().claimId) set({ claimId: null, valueDetail: null, pageText: null, drillError: null });
      else set({ component: null, wrongValues: null, drillError: null });
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
