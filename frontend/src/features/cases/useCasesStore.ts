// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - progress store.
//
// A thin zustand store over the pure helpers in ./progress. It owns the
// per-run progress map plus the per-case sample-project selection, and persists
// both to localStorage so a half-finished case (and the project you were
// learning it on) survive reloads and a hop into a module and back. All real
// logic lives in ./progress (pure, tested); this layer only reads/writes and
// persists.
//
// It also owns two small pieces of view state for the Cases hub itself (not
// per-run progress): the "I work as..." company type the user picked, and
// which cases they pinned to which real project. The filters are plain
// localStorage, same pattern as the progress map above. The pins are not: they
// live on the server under `/v1/cases/pins/`, because the set of cases someone
// curated for a job belongs to their account and not to one browser. What is
// in localStorage under `oe_cases_pins` is a mirror of that list, kept so the
// hub has something to show before the first read lands and after one fails.

import { create } from 'zustand';
import type { CaseCategory, CompanyType, PlaybookProgress, ProfessionalRole } from './types';
import type { PinResponse, PinSource } from './api';
import { authoredPlaybookId, caseIdFromPlaybookId, fetchCasePins, pinCase, unpinCase } from './api';
import {
  clampStepIndex,
  emptyProgress,
  runKey,
  toggleStep as toggleStepProgress,
} from './progress';

const RUNS_KEY = 'oe_cases_progress';
const SELECTED_KEY = 'oe_cases_selected';
const COMPANY_TYPE_KEY = 'oe_cases_company_type';
const ROLE_KEY = 'oe_cases_role';
const PINS_KEY = 'oe_cases_pins';
const PINS_MIGRATED_KEY = 'oe_cases_pins_migrated';
const CATEGORY_KEY = 'oe_cases_categories';
const FINDER_KEY = 'oe_cases_finder_open';
const REGION_KEY = 'oe_cases_region';

// There was a sixth key here, `oe_cases_pin_project`, holding "which real
// project is the Cases hub pinning to". Nothing outside this store ever wrote
// it, so the hub read "No project selected" while the top-bar switcher held a
// project (issue #413). The hub now reads the app-wide active project from
// `useProjectContextStore`; the pin map below stays keyed by project id.

/** Stable, frozen fallback used by selectors for a run that has no progress
 *  yet. Frozen so an accidental mutation throws instead of corrupting shared
 *  state; the pure helpers never mutate, they return new objects. */
export const EMPTY_PROGRESS: PlaybookProgress = Object.freeze(emptyProgress());

type RunMap = Record<string, PlaybookProgress>;
type SelectedMap = Record<string, string>;

function readRuns(): RunMap {
  try {
    const raw = localStorage.getItem(RUNS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: RunMap = {};
    for (const [k, value] of Object.entries(parsed as Record<string, unknown>)) {
      const v = value as Partial<PlaybookProgress> | null;
      if (v && Array.isArray(v.completedStepIds)) {
        out[k] = {
          completedStepIds: v.completedStepIds.filter(
            (id): id is string => typeof id === 'string',
          ),
          currentStepIndex: typeof v.currentStepIndex === 'number' ? v.currentStepIndex : 0,
        };
      }
    }
    return out;
  } catch {
    return {};
  }
}

function readSelected(): SelectedMap {
  try {
    const raw = localStorage.getItem(SELECTED_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: SelectedMap = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'string') out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

function persistRuns(runs: RunMap) {
  try {
    localStorage.setItem(RUNS_KEY, JSON.stringify(runs));
  } catch {
    /* localStorage unavailable (private mode / quota) - non-fatal. */
  }
}

function persistSelected(selected: SelectedMap) {
  try {
    localStorage.setItem(SELECTED_KEY, JSON.stringify(selected));
  } catch {
    /* non-fatal */
  }
}

const VALID_COMPANY_TYPES: readonly CompanyType[] = [
  'general-contractor',
  'subcontractor',
  'cost-consultant',
  'designer',
  'developer-client',
  'project-manager',
  'bim-consultant',
  'owner-operator',
];

/** Read a persisted filter selection as a list of valid ids.
 *
 *  Both filters held a single id before they became multi-select, and that
 *  value was written bare, not as JSON. A legacy entry therefore has to be
 *  read as a one-item selection: parsing it as JSON throws, and treating the
 *  throw as "nothing selected" would silently clear the filter of everyone who
 *  had already picked something. Unknown ids are dropped rather than trusted,
 *  so a renamed id cannot filter the list down to nothing with no way back. */
function readIdList<T extends string>(key: string, valid: readonly T[]): T[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const isValid = (v: unknown): v is T =>
      typeof v === 'string' && (valid as readonly string[]).includes(v);
    if (raw.startsWith('[')) {
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? [...new Set(parsed.filter(isValid))] : [];
    }
    return isValid(raw) ? [raw] : [];
  } catch {
    return [];
  }
}

function persistIdList(key: string, value: readonly string[]) {
  try {
    if (value.length) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch {
    /* non-fatal */
  }
}

/** Whether the filter panel is expanded, remembered across visits.
 *
 *  No stored answer is not the same as "closed". Someone arriving for the
 *  first time has to see the filters to know they exist, while someone who
 *  already picked a company and a role has answered the question and wants the
 *  catalogue instead. So the fallback is computed from whether anything is
 *  selected, and an explicit choice always wins over it. */
function readFinderOpen(fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(FINDER_KEY);
    if (raw === '1') return true;
    if (raw === '0') return false;
    return fallback;
  } catch {
    return fallback;
  }
}

function persistFinderOpen(open: boolean) {
  try {
    localStorage.setItem(FINDER_KEY, open ? '1' : '0');
  } catch {
    /* non-fatal */
  }
}

/** The market filter, remembered across visits.
 *
 *  Three of the hub's four narrowing axes persist. The fourth not persisting
 *  was never read as "a market describes only this visit", it read as the
 *  market selector being broken: you picked Germany, came back, and the
 *  catalogue was wide again with nothing on screen to say why.
 *
 *  Validated by SHAPE rather than against the catalogue. This store
 *  deliberately does not import PLAYBOOKS, and a market whose cases have all
 *  been renamed still has to come back so its chip can be clicked off - the
 *  same rule the hub's selectors follow when a pick has no matching case.
 *  Anything that is not two capitals reads as no filter at all. */
function readRegion(): string {
  try {
    const raw = localStorage.getItem(REGION_KEY);
    return raw && /^[A-Z]{2}$/.test(raw) ? raw : 'all';
  } catch {
    return 'all';
  }
}

function persistRegion(region: string) {
  try {
    if (region && region !== 'all') localStorage.setItem(REGION_KEY, region);
    else localStorage.removeItem(REGION_KEY);
  } catch {
    /* non-fatal */
  }
}

/** Add or remove one id, preserving the order the user picked them in. */
function toggleId<T extends string>(list: readonly T[], id: T): T[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

/** Whitelist a persisted role id must be in to survive a reload. Hand-kept
 *  rather than derived from `ROLE_META`, which would pull lucide-react into
 *  this store's chunk; `cases.test.ts` pins it against `ROLE_META` instead,
 *  because a role missing here loses the user's pick silently on reload. */
export const VALID_ROLES: readonly ProfessionalRole[] = [
  'estimator',
  'quantity-surveyor',
  'site-manager',
  'project-manager',
  'bim-coordinator',
  'procurement-buyer',
  'planner',
  'hse-officer',
  'design-lead',
  'document-controller',
  'commercial-manager',
  'accountant',
  'contract-administrator',
  'finance-manager',
  'foreman',
];

const VALID_CATEGORIES: readonly CaseCategory[] = [
  'estimating',
  'tendering',
  'planning',
  'bim',
  'site',
  'quality',
  'commercial',
  'handover',
];

/** Playbook ids pinned per real project id (NOT a sample-project scope like
 *  `selected` above - this is the user's own "cases I use on this job" list).
 *  The server holds the real list; this shape is the mirror of it and the
 *  shape the hub renders. */
type PinsMap = Record<string, string[]>;

function readPins(): PinsMap {
  try {
    const raw = localStorage.getItem(PINS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: PinsMap = {};
    for (const [projectId, ids] of Object.entries(parsed as Record<string, unknown>)) {
      if (Array.isArray(ids)) {
        out[projectId] = ids.filter((id): id is string => typeof id === 'string');
      }
    }
    return out;
  } catch {
    return {};
  }
}

function persistPins(pins: PinsMap) {
  try {
    localStorage.setItem(PINS_KEY, JSON.stringify(pins));
  } catch {
    /* non-fatal */
  }
}

/** Projects whose localStorage pins have already been handed to the server.
 *
 *  Per browser, because that is where the thing being migrated lives: a second
 *  device with its own `oe_cases_pins` has its own upload to do. */
function readMigratedProjects(): Set<string> {
  try {
    const raw = localStorage.getItem(PINS_MIGRATED_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((id): id is string => typeof id === 'string'));
  } catch {
    return new Set();
  }
}

function markProjectMigrated(projectId: string) {
  try {
    const migrated = readMigratedProjects();
    if (migrated.has(projectId)) return;
    migrated.add(projectId);
    localStorage.setItem(PINS_MIGRATED_KEY, JSON.stringify([...migrated]));
  } catch {
    /* non-fatal: without the marker the upload runs again, and the pin
       endpoint is idempotent, so a lost marker costs a request and nothing
       else. */
  }
}

/** The pins that still exist only in this browser, in the order they were
 *  pinned. Empty once the project has been migrated, so the upload runs once.
 *
 *  The rule the hub was specified against is "the server has nothing for this
 *  project and localStorage has something". This is that rule with the partial
 *  case spelled out: an upload that failed halfway leaves the server holding
 *  SOME of the list, and the literal rule would then read a non-empty server
 *  answer as "already migrated" and drop the remainder on the floor. */
function pinsOwedToServer(projectId: string, serverIds: readonly string[]): string[] {
  if (readMigratedProjects().has(projectId)) return [];
  const local = readPins()[projectId] ?? [];
  return local.filter((id) => !serverIds.includes(id));
}

/** `sort_order` is bounded 0..999 by `PinRequest` in the module's schemas.py.
 *  A 1000th pin is not worth a rejected request, so the tail all shares the
 *  last place rather than failing to save. */
const MAX_SORT_ORDER = 999;

const clampSortOrder = (index: number): number =>
  Math.min(Math.max(index, 0), MAX_SORT_ORDER);

/** Which id space a playbook id belongs to, in the form the pin API wants.
 *  A shipped playbook is a source file and pins under its slug; an authored
 *  case is a database row and pins under its UUID. `caseIdFromPlaybookId` is
 *  the only supported way to tell the two apart. */
function pinTarget(playbookId: string): { case_source: PinSource; case_id: string } {
  const caseId = caseIdFromPlaybookId(playbookId);
  return caseId
    ? { case_source: 'custom', case_id: caseId }
    : { case_source: 'builtin', case_id: playbookId };
}

/** The inverse: the playbook id a stored pin points at. */
function playbookIdFromPin(pin: PinResponse): string {
  return pin.case_source === 'custom' ? authoredPlaybookId(pin.case_id) : pin.case_id;
}

/** Reads in flight, so a hub that re-renders mid-request does not start a
 *  second read of the same project and let the two answers race. */
const pinLoadsInFlight = new Set<string>();

/** Writes in flight, counted per project. A read that resolves while one is
 *  running is stale by construction - the server composed its answer before it
 *  knew about the pin the user just clicked - so that answer is dropped rather
 *  than painted over the optimistic list. Losing the pin you just made is the
 *  exact failure the optimistic update exists to prevent. */
const pinWritesInFlight = new Map<string, number>();

function beginPinWrite(projectId: string) {
  pinWritesInFlight.set(projectId, (pinWritesInFlight.get(projectId) ?? 0) + 1);
}

function endPinWrite(projectId: string) {
  const left = (pinWritesInFlight.get(projectId) ?? 1) - 1;
  if (left > 0) pinWritesInFlight.set(projectId, left);
  else pinWritesInFlight.delete(projectId);
}

/** Write one project's pin list into the store, and by default into the
 *  localStorage mirror as well. Pass `mirror = false` when the list on screen
 *  is not one the server has confirmed - overwriting the mirror with an
 *  unconfirmed list is how the copy we still need gets lost. */
function setPinsForProject(projectId: string, ids: string[], mirror = true) {
  const pins = { ...useCasesStore.getState().pins, [projectId]: ids };
  if (mirror) persistPins(pins);
  useCasesStore.setState({ pins });
}

/** Hand a list of playbook ids to the server in order, continuing the
 *  `sort_order` sequence after the rows already stored. Sequential and not
 *  parallel: the order is the point, and a burst of parallel writes on a small
 *  box is how you earn a 429. Returns false if any one of them did not land. */
async function uploadPins(
  projectId: string,
  playbookIds: readonly string[],
  startIndex: number,
): Promise<boolean> {
  for (const [offset, playbookId] of playbookIds.entries()) {
    try {
      await pinCase({
        project_id: projectId,
        ...pinTarget(playbookId),
        sort_order: clampSortOrder(startIndex + offset),
      });
    } catch {
      return false;
    }
  }
  return true;
}

/** Undo one optimistic toggle, unless the user has already toggled it back.
 *
 *  Restoring a snapshot of the whole list would be wrong: two clicks on two
 *  different cases overlap, and the slower failure would then put back a list
 *  that predates the faster success. Only the one case this call was about is
 *  touched, and only while the state still shows what this call wrote.
 *  A re-pinned case lands at the end; the server's order wins on the next
 *  read. */
function rollbackPin(projectId: string, playbookId: string, pinned: boolean) {
  const current = useCasesStore.getState().pins[projectId] ?? [];
  if (current.includes(playbookId) !== pinned) return;
  const reverted = pinned
    ? current.filter((id) => id !== playbookId)
    : [...current, playbookId];
  setPinsForProject(projectId, reverted);
}

/** Send one pin or unpin, and roll the optimistic change back if it did not
 *  land. Not awaited by `togglePin`, which stays synchronous and void: no
 *  caller has to hold a promise, and none can leave an unhandled rejection. */
async function syncPin(projectId: string, playbookId: string, pinned: boolean): Promise<void> {
  const target = pinTarget(playbookId);
  beginPinWrite(projectId);
  try {
    if (pinned) {
      const index = (useCasesStore.getState().pins[projectId] ?? []).indexOf(playbookId);
      // The response row is deliberately not read. Offline, `apiPost` queues
      // the mutation for replay and resolves with undefined instead of a row,
      // so anything that reached into the result would throw on exactly the
      // path the queue exists to survive.
      await pinCase({
        project_id: projectId,
        ...target,
        sort_order: clampSortOrder(index),
      });
    } else {
      await unpinCase(projectId, target.case_source, target.case_id);
    }
    useCasesStore.setState({ pinsError: false });
  } catch {
    rollbackPin(projectId, playbookId, pinned);
    useCasesStore.setState({ pinsError: true });
  } finally {
    endPinWrite(projectId);
  }
}

interface CasesState {
  /** Progress per run key (playbookId or `playbookId::projectId`). */
  runs: RunMap;
  /** Sample project chosen per playbook id (empty / absent = none). */
  selected: SelectedMap;
  /** The "I work as..." company types picked on the Cases hub (empty = show
   *  every case, no company filter applied). Persists across visits.
   *
   *  The three filter lists below follow the ordinary faceted-search rule: OR
   *  inside one list, AND between lists. Someone who is both a contractor and
   *  a consultant wants the union of the two, but adding a role to that should
   *  narrow the result, not widen it. */
  companyTypes: CompanyType[];
  /** The "Your role" professional roles picked on the Cases hub (empty = no
   *  role filter). Independent of `companyTypes`; both narrow the list. */
  roles: ProfessionalRole[];
  /** The discipline chips picked on the Cases hub (empty = every discipline).
   *  Held here rather than in the page so it survives a visit to a case and
   *  back, which is how the other two filters already behaved. */
  categories: CaseCategory[];
  /** Playbook ids pinned per real project id, as last read from the server (or
   *  out of the mirror, before the first read). The project the hub is pinning
   *  TO is not held here - it is the app-wide active project from
   *  `useProjectContextStore`. */
  pins: PinsMap;
  /** True while a `loadPins` read is in flight for any project. */
  pinsLoading: boolean;
  /** True when the last pin call did not reach the server, so the list on
   *  screen is this browser's copy rather than the account's. Not an error to
   *  raise at the user by itself: the pins still work locally, and the hub can
   *  say so quietly. Cleared by the next call that succeeds. */
  pinsError: boolean;
  /** Whether the hub's "find your case" panel is expanded. Open on a first
   *  visit so the filters are discoverable, closed once something is picked so
   *  the catalogue starts near the top of the page, and an explicit toggle
   *  overrides both and is remembered. */
  finderOpen: boolean;
  /** The market the hub is narrowed to, or 'all' for every market. Persisted
   *  like the company, role and discipline filters: it narrows the catalogue
   *  the same way they do, so it has to survive a visit the same way. */
  region: string;
  /** Toggle a step's done flag for a run. */
  toggleStepDone: (playbookId: string, projectId: string | null, stepId: string) => void;
  /** Move the runner's focus to a step index (clamped to the step count). */
  setCurrentStep: (
    playbookId: string,
    projectId: string | null,
    index: number,
    total: number,
  ) => void;
  /** Clear all progress for a run. */
  reset: (playbookId: string, projectId?: string | null) => void;
  /** Set (or clear, with '') the sample project for a playbook. */
  setSelectedProject: (playbookId: string, projectId: string) => void;
  /** Replace the whole "I work as..." filter (pass [] to clear it). */
  setCompanyTypes: (companyTypes: CompanyType[]) => void;
  /** Replace the whole "Your role" filter (pass [] to clear it). */
  setRoles: (roles: ProfessionalRole[]) => void;
  /** Replace the whole discipline filter (pass [] to clear it). */
  setCategories: (categories: CaseCategory[]) => void;
  /** Add or remove one company type from the "I work as..." filter. */
  toggleCompanyType: (companyType: CompanyType) => void;
  /** Add or remove one role from the "Your role" filter. */
  toggleRole: (role: ProfessionalRole) => void;
  /** Add or remove one discipline from the category filter. */
  toggleCategory: (category: CaseCategory) => void;
  /** Narrow the hub to one market, or 'all' to drop the filter. */
  setRegion: (region: string) => void;
  /** Drop every company, role, discipline and market filter in one go. */
  clearFilters: () => void;
  /** Expand or collapse the hub's filter panel, remembering the choice. */
  setFinderOpen: (open: boolean) => void;
  /** Read a project's pins from the server, run the one-time upload of what
   *  this browser had in localStorage if it is still owed, and refresh the
   *  mirror. Never rejects: a failure leaves the local list on screen and
   *  raises `pinsError`. Safe to call on every visit to the hub. */
  loadPins: (projectId: string) => Promise<void>;
  /** Pin or unpin a case for a project (no-op with an empty projectId).
   *  Optimistic: the list moves on the click and rolls back if the write
   *  fails. */
  togglePin: (projectId: string, playbookId: string) => void;
  /** True when the case is pinned to the given project. */
  isPinned: (projectId: string, playbookId: string) => boolean;
}

// Read once, before the store is built: the initial state of the filter panel
// depends on whether any of these came back with something in them.
const initialCompanyTypes = readIdList(COMPANY_TYPE_KEY, VALID_COMPANY_TYPES);
const initialRoles = readIdList(ROLE_KEY, VALID_ROLES);
const initialCategories = readIdList(CATEGORY_KEY, VALID_CATEGORIES);
const initialRegion = readRegion();

export const useCasesStore = create<CasesState>((set, get) => ({
  runs: readRuns(),
  selected: readSelected(),
  companyTypes: initialCompanyTypes,
  roles: initialRoles,
  categories: initialCategories,
  region: initialRegion,
  pins: readPins(),
  pinsLoading: false,
  pinsError: false,
  // The market is deliberately NOT counted here. It lives on its own shelf
  // above the "find your case" panel rather than inside it, so folding that
  // panel because of a pick made outside it would hide the three selectors
  // that ARE inside it, for a reason the user cannot see.
  finderOpen: readFinderOpen(
    initialCompanyTypes.length + initialRoles.length + initialCategories.length === 0,
  ),

  toggleStepDone: (playbookId, projectId, stepId) => {
    const key = runKey(playbookId, projectId);
    const current = get().runs[key] ?? emptyProgress();
    const next = toggleStepProgress(current, stepId);
    const runs = { ...get().runs, [key]: next };
    persistRuns(runs);
    set({ runs });
  },

  setCurrentStep: (playbookId, projectId, index, total) => {
    const key = runKey(playbookId, projectId);
    const current = get().runs[key] ?? emptyProgress();
    const clamped = clampStepIndex(index, total);
    if (get().runs[key] && current.currentStepIndex === clamped) return;
    const runs = { ...get().runs, [key]: { ...current, currentStepIndex: clamped } };
    persistRuns(runs);
    set({ runs });
  },

  reset: (playbookId, projectId) => {
    const key = runKey(playbookId, projectId);
    if (!(key in get().runs)) return;
    const runs = { ...get().runs };
    delete runs[key];
    persistRuns(runs);
    set({ runs });
  },

  setSelectedProject: (playbookId, projectId) => {
    const selected = { ...get().selected };
    if (projectId) selected[playbookId] = projectId;
    else delete selected[playbookId];
    persistSelected(selected);
    set({ selected });
  },

  setCompanyTypes: (companyTypes) => {
    persistIdList(COMPANY_TYPE_KEY, companyTypes);
    set({ companyTypes });
  },

  setRoles: (roles) => {
    persistIdList(ROLE_KEY, roles);
    set({ roles });
  },

  setCategories: (categories) => {
    persistIdList(CATEGORY_KEY, categories);
    set({ categories });
  },

  toggleCompanyType: (companyType) => {
    const companyTypes = toggleId(get().companyTypes, companyType);
    persistIdList(COMPANY_TYPE_KEY, companyTypes);
    set({ companyTypes });
  },

  toggleRole: (role) => {
    const roles = toggleId(get().roles, role);
    persistIdList(ROLE_KEY, roles);
    set({ roles });
  },

  toggleCategory: (category) => {
    const categories = toggleId(get().categories, category);
    persistIdList(CATEGORY_KEY, categories);
    set({ categories });
  },

  setRegion: (region) => {
    persistRegion(region);
    set({ region });
  },

  clearFilters: () => {
    persistIdList(COMPANY_TYPE_KEY, []);
    persistIdList(ROLE_KEY, []);
    persistIdList(CATEGORY_KEY, []);
    persistRegion('all');
    set({ companyTypes: [], roles: [], categories: [], region: 'all' });
  },

  setFinderOpen: (open) => {
    persistFinderOpen(open);
    set({ finderOpen: open });
  },

  loadPins: async (projectId) => {
    if (!projectId) return;
    if (pinLoadsInFlight.has(projectId)) return;
    pinLoadsInFlight.add(projectId);
    set({ pinsLoading: true });
    try {
      const rows = await fetchCasePins(projectId);
      // A pin was clicked while this read was on the wire, so the answer that
      // just arrived predates it. Drop it; the write keeps the local list
      // right and the next read reconciles.
      if (pinWritesInFlight.has(projectId)) return;
      const serverIds = (rows ?? []).map(playbookIdFromPin);
      const owed = pinsOwedToServer(projectId, serverIds);
      if (owed.length === 0) {
        // Either this browser had nothing of its own to hand over, or it has
        // already handed it over. Both settle the question for this project,
        // so the marker goes down and the upload never runs again here.
        markProjectMigrated(projectId);
        setPinsForProject(projectId, serverIds);
        set({ pinsError: false });
        return;
      }
      const uploaded = await uploadPins(projectId, owed, serverIds.length);
      if (!uploaded) {
        // Show everything known about - the server's rows plus the ones still
        // only here - but leave `oe_cases_pins` alone and do not mark the
        // project migrated. The upload is the only thing that would have moved
        // this data off this browser, so until it lands, localStorage is the
        // only copy of it that exists and overwriting it would destroy the
        // list the user curated.
        setPinsForProject(projectId, [...serverIds, ...owed], false);
        set({ pinsError: true });
        return;
      }
      markProjectMigrated(projectId);
      setPinsForProject(projectId, [...serverIds, ...owed]);
      set({ pinsError: false });
    } catch {
      // Server unreachable, no access to the project, or offline with nothing
      // cached. The mirror stays on screen - an empty strip would read as "you
      // pinned nothing", which is a different and untrue statement - and the
      // flag says the list may be stale.
      set({ pinsError: true });
    } finally {
      pinLoadsInFlight.delete(projectId);
      set({ pinsLoading: pinLoadsInFlight.size > 0 });
    }
  },

  togglePin: (projectId, playbookId) => {
    if (!projectId) return;
    const current = get().pins[projectId] ?? [];
    const pinned = !current.includes(playbookId);
    const nextForProject = pinned
      ? [...current, playbookId]
      : current.filter((id) => id !== playbookId);
    // Optimistic, then the request. A pin that waits for a round trip reads as
    // a control that did not work, and the user clicks it a second time.
    setPinsForProject(projectId, nextForProject);
    void syncPin(projectId, playbookId, pinned);
  },

  isPinned: (projectId, playbookId) => {
    if (!projectId) return false;
    return (get().pins[projectId] ?? []).includes(playbookId);
  },
}));
