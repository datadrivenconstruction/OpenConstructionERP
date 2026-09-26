// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The catalogue card IS the way into a case - the showcase dramaturgy is
// "catalogue -> card -> steps", so a card that does not open its case makes
// the whole hub a dead end. A frame-by-frame QA pass reported exactly that
// ("clicking a card on /cases does not open the case"); on the current code
// the wiring is present and correct, and this suite pins every part of it so
// the report can never become true silently:
//
//   - pointer: clicking anywhere on the card (its title included - children
//     bubble to the card) navigates to /cases/:playbookId;
//   - keyboard: the card is focusable (tabIndex=0, role=button), Enter and
//     Space both navigate, and a visible focus affordance is declared;
//   - containment: keys pressed on an INNER interactive control must not
//     also fire the card, or the per-card pin/edit buttons double-navigate.
//
// Run:  npx vitest run src/features/cases/casesCardNavigation.test.tsx

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { PLAYBOOKS } from "./playbooks";
import { CasesPage } from "./CasesPage";
import { FEATURED_ARTICLE_COVER, FEATURED_ARTICLE_URL } from "./FeaturedArticle";

/* ── Stable `t` (same rationale as casesProjectContext.test.tsx: the shared
   setup mock mints a fresh `t` per call, and CasesList's render-time window
   guard then re-renders forever) ─────────────────────────────────────────── */

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

/* ── Mock @/app/i18n to prevent i18next initialization side-effects ───── */

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
  initialLocaleReady: null,
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: "en",
    changeLanguage: vi.fn(),
  },
}));

/* ── Mock react-query - the hub's only fetch is the project list ───────── */

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

/* ── Mock @/shared/lib/api to prevent real network calls ──────────────── */

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

/* ── Router: one stable navigate spy, unlike the shared setup mock which
   mints a fresh fn per call and so can never be asserted against ────────── */

const navigateSpy = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

// Every test here mounts the whole hub, two hundred and more cards. On a
// saturated CPU one mount alone can outlast the 15s default, so the file
// gets the room a lighter file does not need.
vi.setConfig({ testTimeout: 60_000 });

/* ── Helpers ──────────────────────────────────────────────────────────── */

const target = PLAYBOOKS[0]!;

/** Renders the hub and returns the card of the target playbook plus its
 *  visible title node. The title also appears in the card's hover panel, so
 *  the first hit is taken; both live inside the same card root. */
function renderAndFindCard(): { card: HTMLElement; title: HTMLElement } {
  render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
  const title = screen.getAllByText(target.titleDefault)[0]!;
  const card = title.closest<HTMLElement>('[role="button"]');
  if (!card) throw new Error("Case card root (role=button) not found");
  return { card, title };
}

beforeEach(() => {
  localStorage.clear();
  navigateSpy.mockClear();
});

describe("featured article", () => {
  it("opens the Cases page, linking out to the article in a new tab", () => {
    render(
      <MemoryRouter initialEntries={["/cases"]}>
        <CasesPage />
      </MemoryRouter>,
    );
    const link = screen.getByTestId("cases-featured-article");
    expect(link.getAttribute("href")).toBe(FEATURED_ARTICLE_URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.textContent).toContain("Uberization of Construction");
    expect(link.textContent).toContain("Read the article");
  });

  it("draws its own panel when the cover cannot load", () => {
    render(
      <MemoryRouter initialEntries={["/cases"]}>
        <CasesPage />
      </MemoryRouter>,
    );
    const link = screen.getByTestId("cases-featured-article");
    const cover = link.querySelector("img")!;
    expect(cover.getAttribute("src")).toBe(FEATURED_ARTICLE_COVER);
    fireEvent.error(cover);
    expect(link.querySelector("img")).toBeNull();
  });
});

describe("catalogue card - opening a case", () => {
  it("is a focusable button with a visible focus affordance", () => {
    const { card } = renderAndFindCard();
    expect(card.getAttribute("role")).toBe("button");
    expect(card.getAttribute("tabindex")).toBe("0");
    // The affordance the keyboard user sees; without it the card is operable
    // but undiscoverable.
    expect(card.className).toMatch(/focus-visible:ring/);
  });

  it("click on the card (via its title, bubbling) opens the case route", () => {
    const { title } = renderAndFindCard();
    fireEvent.click(title);
    expect(navigateSpy).toHaveBeenCalledWith(`/cases/${target.id}`);
  });

  it("Enter on the focused card opens the case route", () => {
    const { card } = renderAndFindCard();
    fireEvent.keyDown(card, { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledWith(`/cases/${target.id}`);
  });

  it("Space on the focused card opens the case route", () => {
    const { card } = renderAndFindCard();
    fireEvent.keyDown(card, { key: " " });
    expect(navigateSpy).toHaveBeenCalledWith(`/cases/${target.id}`);
  });

  it("keys pressed on an inner element do not fire the card as well", () => {
    // The guard that keeps Enter on the pin/edit buttons from ALSO opening
    // the case. A keydown whose target is a child must be the child's alone.
    const { title } = renderAndFindCard();
    fireEvent.keyDown(title, { key: "Enter" });
    expect(navigateSpy).not.toHaveBeenCalled();
  });
});
