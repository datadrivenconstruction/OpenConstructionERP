// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "Start here" paths on the cases hub, and the cases written for the
// project-management modules and for cost control.
//
// A path is a short ordered list of cases for one goal. These tests hold the
// data (every id a shipped case), the hub behaviour (an addressable, ordered
// list with the place in the path on each card), and the cases behind the
// paths: every project-management module screen is walked by a case, and a
// case that walks a project-only screen sends a reader without a project to
// the project list rather than to a path that names no screen.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import React from "react";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";
import { PLAYBOOKS } from "./playbooks";
import { CASE_TRACKS, TRACK_BY_ID, orderByTrack, trackFromParam } from "./tracks";
import { resolveStepRoute } from "./progress";

/* The harness below is the one casesMarketDeepLink.test.tsx uses: real
   routing hooks, a stable `t`, and settled queries with no projects. */

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

// Every test here mounts the whole hub, two hundred and more cards, and the
// chip test re-renders it twice over. On a saturated CPU one mount alone
// can outlast the 15s default, so the file gets the room a lighter file
// does not need.
vi.setConfig({ testTimeout: 240_000 });

/* ── Helpers ──────────────────────────────────────────────────────────── */

function AddressProbe() {
  const location = useLocation();
  return <output data-testid="address">{location.pathname + location.search}</output>;
}

function renderHubAt(address: string): () => string {
  render(
    <MemoryRouter initialEntries={[address]}>
      <CasesPage />
      <AddressProbe />
    </MemoryRouter>,
  );
  return () => screen.getByTestId("address").textContent ?? "";
}

beforeEach(() => {
  localStorage.clear();
  const store = useCasesStore.getState();
  store.setRegion("all");
  store.clearFilters();
});

const SHIPPED = new Set(PLAYBOOKS.map((pb) => pb.id));

/* ── The paths are data, and the data has to point at real cases ──────── */

describe("case paths", () => {
  it("name only shipped cases, each once, in paths with distinct ids", () => {
    expect(CASE_TRACKS.length).toBeGreaterThanOrEqual(5);
    expect(new Set(CASE_TRACKS.map((t) => t.id)).size).toBe(CASE_TRACKS.length);
    for (const track of CASE_TRACKS) {
      expect(track.caseIds.length, `${track.id} is too short to be a path`).toBeGreaterThanOrEqual(3);
      expect(new Set(track.caseIds).size, `${track.id} repeats a case`).toBe(track.caseIds.length);
      for (const id of track.caseIds) {
        expect(SHIPPED.has(id), `${track.id} names "${id}", which no case file ships`).toBe(true);
      }
    }
  });

  it("orders a list by the path and drops what the list does not hold", () => {
    const track = TRACK_BY_ID["cost-control"]!;
    const shuffled = [...PLAYBOOKS].reverse();
    expect(orderByTrack(shuffled, track).map((pb) => pb.id)).toEqual(track.caseIds);
    const without = shuffled.filter((pb) => pb.id !== track.caseIds[0]);
    expect(orderByTrack(without, track).map((pb) => pb.id)).toEqual(track.caseIds.slice(1));
  });

  it("reads a path from the address and ignores one it does not know", () => {
    expect(trackFromParam("cost-control")?.id).toBe("cost-control");
    expect(trackFromParam(" Client-Project ")?.id).toBe("client-project");
    expect(trackFromParam("nope")).toBeNull();
    expect(trackFromParam(null)).toBeNull();
  });
});

/* ── The project-management modules each have a case that walks them ──── */

describe("cases for the project-management modules", () => {
  // The screens of the eleven-area module set, each of which exists only
  // inside a project. A module without a case is a module nobody is shown
  // how to use, so every one of them is named here.
  const MODULE_ROUTES = [
    "/projects/:projectId/governance",
    "/projects/:projectId/commitments",
    "/projects/:projectId/delivery",
    "/projects/:projectId/permits",
    "/projects/:projectId/plant-register",
    "/projects/:projectId/procurement-concept",
    "/projects/:projectId/design",
    "/projects/:projectId/stakeholders",
    "/projects/:projectId/quality-concept",
    "/projects/:projectId/staffing",
    "/projects/:projectId/site-logistics",
  ];

  it("walks every module screen from at least one case", () => {
    const walked = new Set(
      PLAYBOOKS.flatMap((pb) => pb.steps.map((s) => s.to.split("?")[0])),
    );
    for (const route of MODULE_ROUTES) {
      expect(walked.has(route), `no case steps into ${route}`).toBe(true);
    }
  });

  it("marks every case that steps into a project-only screen as needing a project", () => {
    // Without the flag the runner strips the prefix, and `/permits` is no
    // screen while `/governance` is a different one.
    const projectOnly = new Set(MODULE_ROUTES.filter((r) => !r.endsWith("/site-logistics")));
    for (const pb of PLAYBOOKS) {
      const needs = pb.steps.some((s) => projectOnly.has(s.to.split("?")[0]!));
      if (needs) {
        expect(pb.requiresProject, `${pb.id} steps into a project-only screen`).toBe(true);
      }
    }
  });

  it("sends a reader without a project to the project list, never to a stripped path", () => {
    for (const pb of PLAYBOOKS.filter((p) => p.requiresProject)) {
      for (const step of pb.steps) {
        if (!step.to.includes(":projectId")) continue;
        expect(resolveStepRoute(step.to, null, true)).toBe("/projects");
        expect(resolveStepRoute(step.to, "p1", true)).toBe(step.to.replace(":projectId", "p1"));
      }
    }
    // Cases without the flag keep stripping, exactly as before.
    expect(resolveStepRoute("/projects/:projectId/boq", null)).toBe("/boq");
  });

  it("points the cost control cases at the cost control screen", () => {
    const track = TRACK_BY_ID["cost-control"]!;
    const own = track.caseIds.slice(0, 5).map((id) => PLAYBOOKS.find((pb) => pb.id === id)!);
    for (const pb of own) {
      expect(pb.steps.some((s) => s.to === "/cost-control"), `${pb.id} never opens /cost-control`).toBe(true);
    }
  });
});

/* ── The hub: a path is a short, ordered, addressable list ──────────────── */

describe("the cases hub start-here paths", () => {
  it("offers every path as a tile", () => {
    renderHubAt("/cases");
    const tiles = screen.getAllByTestId("case-track").map((el) => el.getAttribute("data-track"));
    expect(tiles).toEqual(CASE_TRACKS.map((t) => t.id));
  });

  it("an address naming a path lists exactly its cases, numbered in its order", () => {
    renderHubAt("/cases?track=cost-control");
    const track = TRACK_BY_ID["cost-control"]!;

    expect(screen.getByTestId("case-track-hero")).toBeTruthy();
    const badges = screen.getAllByTestId("case-path-position");
    expect(badges.map((b) => b.textContent)).toEqual(track.caseIds.map((_, i) => String(i + 1)));
    const first = PLAYBOOKS.find((pb) => pb.id === track.caseIds[0])!;
    expect(badges[0]!.closest('[role="button"]')?.textContent).toContain(first.titleDefault);
  });

  it("a tile click writes the path into the address, and a second click leaves it", () => {
    const address = renderHubAt("/cases");
    const tile = () =>
      screen.getAllByTestId("case-track").find((el) => el.getAttribute("data-track") === "client-project")!;

    act(() => fireEvent.click(tile()));
    expect(address()).toBe("/cases?track=client-project");
    expect(tile().getAttribute("aria-pressed")).toBe("true");

    act(() => fireEvent.click(tile()));
    expect(address()).toBe("/cases");
    expect(screen.queryByTestId("case-track-hero")).toBeNull();
  });

  it("picking a path clears a market left over from an earlier visit", () => {
    useCasesStore.getState().setRegion("DE");
    const address = renderHubAt("/cases?market=DE");
    const tile = screen.getAllByTestId("case-track").find((el) => el.getAttribute("data-track") === "cost-control")!;

    act(() => fireEvent.click(tile));

    expect(useCasesStore.getState().region).toBe("all");
    expect(address()).toBe("/cases?track=cost-control");
    expect(screen.getAllByTestId("case-path-position").length).toBe(
      TRACK_BY_ID["cost-control"]!.caseIds.length,
    );
  });
});
