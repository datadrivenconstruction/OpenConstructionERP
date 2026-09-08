// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A case page is addressable down to the step: `/cases/answer-an-rfi?step=raise`.
//
// `/cases/:playbookId` already opened the case, and stopped there: progress
// lives in this browser and the sample project carries an id this install
// minted, so neither can travel in a link. The step id is the one part of a
// run that means the same everywhere, and it is what the address now
// carries. These tests pin the two directions: an address naming a step
// focuses it, and moving between steps moves the address, so the bar is the
// link to the step the sender is looking at. They also pin that the hub's
// market parameter is left alone on a case page.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import React from "react";
import { PLAYBOOKS } from "./playbooks";
import { runKey } from "./progress";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

/* ── Real routing ────────────────────────────────────────────────────────
   The shared setup (src/test/setup.ts) stubs useSearchParams to a permanently
   empty set and useParams to `{}`. This file is about the address, so it puts
   the real hooks back: the page reads and writes the address the MemoryRouter
   below holds, and the probe beside it reads the same one. The factory
   registered last wins, so this replaces the stub for this file only. */

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual };
});

/* ── Stable `t` (see casesProjectContext.test.tsx for why the shared mock's
   per-call `t` makes CasesList re-render without end) ───────────────────── */

vi.mock("react-i18next", () => {
  const stableT = (key: string, opts?: Record<string, unknown>) => {
    if (typeof opts === "object" && opts !== null && "defaultValue" in opts) {
      let template = opts.defaultValue as string;
      if (
        "count" in opts &&
        opts.count !== 1 &&
        typeof opts.defaultValue_other === "string"
      ) {
        template = opts.defaultValue_other;
      }
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        name in opts ? String(opts[name]) : `{{${name}}}`,
      );
    }
    return key;
  };
  const translation = {
    t: stableT,
    i18n: { language: "en", changeLanguage: vi.fn() },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

vi.mock("@/app/i18n", () => ({
  CORE_LANGUAGES: [{ code: "en", name: "English", flag: "gb", country: "gb" }],
  EXTRA_LANGUAGES: [],
  SUPPORTED_LANGUAGES: [
    { code: "en", name: "English", flag: "gb", country: "gb" },
  ],
  getLanguageByCode: () => ({
    code: "en",
    name: "English",
    flag: "gb",
    country: "gb",
  }),
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: "en",
    changeLanguage: vi.fn(),
  },
}));

vi.mock("@tanstack/react-query", () => {
  const settled = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  });
  return {
    useQuery: (opts: { queryKey?: unknown[] }) => {
      const root = String(opts?.queryKey?.[0] ?? "");
      if (root === "projects") return settled([]);
      return { ...settled(undefined), isSuccess: false };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
    }),
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: React.ReactNode }) =>
      children,
  };
});

vi.mock("@/shared/lib/api", () => ({
  API_BASE: "/api",
  getAuthToken: () => "mock-token",
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (err: unknown) => String(err),
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  triggerDownload: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

/* ── Helpers ──────────────────────────────────────────────────────────── */

const CASE_ID = "answer-an-rfi";
const playbook = PLAYBOOKS.find((p) => p.id === CASE_ID);
if (!playbook) throw new Error(`shipped case ${CASE_ID} is missing`);
const stepIds = playbook.steps.map((s) => s.id);
const KEY = runKey(CASE_ID, null);

/** Prints the address the router holds, so a test can read what a reader
 *  would copy out of the bar. Sits beside the page, under the same router. */
function AddressProbe() {
  const location = useLocation();
  return <output data-testid="address">{location.pathname + location.search}</output>;
}

/** Mount the case page at `address` (the real route shape, so `useParams`
 *  resolves the case); returns a reader for the current address. */
function renderCaseAt(address: string): () => string {
  render(
    <MemoryRouter initialEntries={[address]}>
      <Routes>
        <Route path="/cases/:playbookId" element={<CasesPage />} />
      </Routes>
      <AddressProbe />
    </MemoryRouter>,
  );
  return () => screen.getByTestId("address").textContent ?? "";
}

const focusedIndex = () => useCasesStore.getState().runs[KEY]?.currentStepIndex ?? 0;
const stepParam = (address: string) => new URLSearchParams(address.split("?")[1] ?? "").get("step");

beforeEach(() => {
  localStorage.clear();
  useCasesStore.getState().reset(CASE_ID);
  useCasesStore.getState().setSelectedProject(CASE_ID, "");
  useCasesStore.getState().setRegion("all");
  // jsdom lays nothing out, so it has no scrollIntoView; the runner scrolls
  // the focused step into view, and the stub records that it tried.
  Element.prototype.scrollIntoView = vi.fn();
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe("a case page is addressable down to the step", () => {
  it("an address naming a step focuses that step and scrolls to it", () => {
    const target = stepIds[1]!;

    const address = renderCaseAt(`/cases/${CASE_ID}?step=${target}`);

    expect(focusedIndex()).toBe(1);
    expect(stepParam(address())).toBe(target);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("opening a case writes the focused step into the address, so the bar is the link", () => {
    const address = renderCaseAt(`/cases/${CASE_ID}`);

    expect(focusedIndex()).toBe(0);
    expect(stepParam(address())).toBe(stepIds[0]);
  });

  it("moving to another step moves the address", () => {
    const address = renderCaseAt(`/cases/${CASE_ID}`);

    act(() => useCasesStore.getState().setCurrentStep(CASE_ID, null, 2, stepIds.length));

    expect(focusedIndex()).toBe(2);
    expect(stepParam(address())).toBe(stepIds[2]);
  });

  it("a step id the case does not have leaves the focus alone and is rewritten", () => {
    const address = renderCaseAt(`/cases/${CASE_ID}?step=no-such-step`);

    expect(focusedIndex()).toBe(0);
    expect(stepParam(address())).toBe(stepIds[0]);
  });

  it("the hub's market parameter is not the case page's to read or rewrite", () => {
    const address = renderCaseAt(`/cases/${CASE_ID}?market=DE`);

    expect(useCasesStore.getState().region).toBe("all");
    expect(new URLSearchParams(address().split("?")[1] ?? "").get("market")).toBe("DE");
  });
});
