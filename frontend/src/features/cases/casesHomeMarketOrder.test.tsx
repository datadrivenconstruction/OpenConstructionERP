// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The catalogue leads with the reader's own market - checked on the rendered
// hub, not on the helper.
//
// `homeMarket.test.ts` proves the two pure functions. That proof survives
// somebody deleting the call to them from `CasesList`, which is the whole
// failure this file exists to catch: a green unit suite over a function the
// page no longer uses reads exactly like a working feature.
//
// Every case is asserted present as well as ordered. The design is an
// ORDERING and not a filter, and a filter would pass an ordering assertion
// that only looked at the front of the list.
//
// Run:  npx vitest run src/features/cases/casesHomeMarketOrder.test.tsx

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { PLAYBOOKS } from "./playbooks";
import { buildCaseNumbers } from "./stages";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

/* ── The UI language under test, flipped per case ─────────────────────────
   Hoisted so the `react-i18next` factory can close over it, and read through
   a getter so a value set inside a test is the one the next render sees. */

const uiLanguage = vi.hoisted(() => ({ current: "en" }));

/* ── Stable `t` (same rationale as casesCardNavigation.test.tsx: the shared
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
    i18n: {
      get language() {
        return uiLanguage.current;
      },
      changeLanguage: vi.fn(),
    },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

/* `@/app/i18n` is deliberately NOT mocked here. The mapping under test reads
   the country each language declares in the real `SUPPORTED_LANGUAGES`, and a
   stub registry would let this file stay green while the shipped one said
   something else. */

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

/* ── Router: the hub reads params and navigates; neither is asserted here ─ */

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

/* ── Helpers ──────────────────────────────────────────────────────────── */

const numbers = buildCaseNumbers(PLAYBOOKS);
const catalogueOrder = [...PLAYBOOKS].sort(
  (a, b) => (numbers.get(a.id) ?? 0) - (numbers.get(b.id) ?? 0),
);

/** The case cards in the order they sit in the document. `role="button"` is
 *  written in exactly one place in CasesPage.tsx - the card root - so this
 *  selector cannot drift onto some other control. */
function renderCards(language: string): HTMLElement[] {
  uiLanguage.current = language;
  const { container } = render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
  return Array.from(container.querySelectorAll<HTMLElement>('[role="button"]'));
}

/** The text of each card, in document order. Read positionally rather than
 *  searched by title: a `findIndex` on "the first card whose text contains
 *  this title" answers with the wrong card the day one title is a substring of
 *  another, and it would do it quietly. */
const textsOf = (cards: HTMLElement[]): string[] =>
  cards.map((card) => card.textContent ?? "");

/** True when some card in `texts` prints this case's title. */
const shows = (texts: string[], titleDefault: string): boolean =>
  texts.some((text) => text.includes(titleDefault));

beforeEach(() => {
  localStorage.clear();
  // The store reads its persisted filters once, when the module is evaluated,
  // so a market pick has to be made through the store rather than by writing
  // the key. Clearing through it keeps each test starting from a wide
  // catalogue.
  useCasesStore.getState().clearFilters();
  uiLanguage.current = "en";
});

describe("catalogue order follows the reader's language", () => {
  it("renders one card per case, so ordering assertions are about the whole library", () => {
    // The window (CARD_BATCH_SIZE) opens to the full list without an
    // IntersectionObserver, which JSDOM does not provide. If that ever stops
    // being true every assertion below silently narrows to the first batch.
    const cards = renderCards("en");
    expect(cards).toHaveLength(PLAYBOOKS.length);
  });

  it("leaves the catalogue in its own order for plain English", () => {
    // Plain `en` declares no country: a reader who has said only that they
    // read English has not said whose procurement they work under, and the
    // registry stopped guessing Britain for them. The same shape as the
    // Japanese case below, for the product's default language.
    const texts = textsOf(renderCards("en"));
    catalogueOrder.slice(0, 24).forEach((pb, i) => {
      expect(texts[i]?.includes(pb.titleDefault), `${pb.id} at ${i}`).toBe(true);
    });
  });

  it("puts the British cases first for a reader of English (UK), and keeps the rest", () => {
    const texts = textsOf(renderCards("en-GB"));
    const british = PLAYBOOKS.filter((pb) => pb.region === "GB");
    expect(british.length).toBeGreaterThan(0);

    const front = texts.slice(0, british.length);
    for (const pb of british) expect(shows(front, pb.titleDefault), pb.id).toBe(true);

    // Nothing was filtered away to achieve that: the 140 universal cases and
    // the five other markets are all still on the page, behind the front.
    for (const pb of PLAYBOOKS) expect(shows(texts, pb.titleDefault), pb.id).toBe(true);
    const german = PLAYBOOKS.find((pb) => pb.region === "DE")!;
    expect(shows(front, german.titleDefault)).toBe(false);
  });

  it("puts the German cases first for a German reader", () => {
    // The control that has to come out the other way. Same catalogue, same
    // page, one changed language: if the front of the list does not move, the
    // page is not reading the language at all and the English case above
    // proved nothing.
    const texts = textsOf(renderCards("de"));
    const german = PLAYBOOKS.filter((pb) => pb.region === "DE");
    expect(german.length).toBeGreaterThan(0);

    const front = texts.slice(0, german.length);
    for (const pb of german) expect(shows(front, pb.titleDefault), pb.id).toBe(true);

    const british = PLAYBOOKS.find((pb) => pb.region === "GB")!;
    expect(shows(front, british.titleDefault)).toBe(false);
    expect(shows(texts, british.titleDefault)).toBe(true);
  });

  it("leaves the catalogue in its own order for a language that names no market", () => {
    // Japanese declares JP, the catalogue has no Japanese cases, and the
    // honest answer is the order the hub already had: lifecycle stage, then
    // the case's `order`, then id. There is no popularity signal to rank by.
    const texts = textsOf(renderCards("ja"));
    catalogueOrder.slice(0, 24).forEach((pb, i) => {
      expect(texts[i]?.includes(pb.titleDefault), `${pb.id} at ${i}`).toBe(true);
    });
  });

  it("does not touch the stored market pick", () => {
    // The default is an ordering and writes nothing, so a reader who picked a
    // market keeps it and a reader who picked none is not handed one behind
    // their back. `oe_cases_region` is the key the hub persists.
    renderCards("de");
    expect(localStorage.getItem("oe_cases_region")).toBeNull();
    expect(useCasesStore.getState().region).toBe("all");
  });

  it("honours a market the reader picked themselves over their language", () => {
    useCasesStore.getState().setRegion("ES");
    const cards = renderCards("de");
    const spanish = PLAYBOOKS.filter((pb) => pb.region === "ES");
    expect(spanish.length).toBeGreaterThan(0);
    expect(cards).toHaveLength(spanish.length);
    expect(localStorage.getItem("oe_cases_region")).toBe("ES");
  });
});
