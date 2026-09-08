// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The market shelf of the hub, walked the way four readers walked it in a
// browser: a German site manager, a Mexican estimator, an Indian quantity
// surveyor and an English reader with no pack applied. Each defect below was
// measured on the released build before it was fixed, and each test here was
// red on that build:
//
//   - the shelf was sorted by ISO code, so a German UI read Australien,
//     Brasilien, Kanada, China, Deutschland, with nothing marking the fifth
//     tile as the reader's own market;
//   - typing "Deutschland" into the search found nothing, because only titles
//     and descriptions were searched and no title names its country;
//   - a tile said how many cases a market had and nothing about its pack, so
//     "is the pack for my market on" took a click and a scroll to answer;
//   - the header row could not wrap, so on a phone the actions column took the
//     whole width and the title fell into a sliver, one word per line;
//   - long German labels (Generalunternehmer) could not break and were drawn
//     under the next tile;
//   - eight card columns at 1280 wide, with the sidebar open, were 112px cards
//     with every title clamped mid-word.
//
// The last three are layout, which JSDOM does not compute, so they are
// asserted as the class contract that produces the layout. That is weaker than
// a browser measurement and it is what a unit suite can hold; the browser walk
// is recorded beside the change.
//
// Run:  TZ=UTC npx vitest run src/features/cases/casesMarketShelf.test.tsx --pool=threads

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { PLAYBOOKS } from "./playbooks";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

/* ── The UI language under test, flipped per case (see casesHomeMarketOrder) ── */

const uiLanguage = vi.hoisted(() => ({ current: "en" }));

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

/* ── The pack list, controlled per test ─────────────────────────────────── */

const packMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  useInstalledPacks: vi.fn(),
  partnerLogoUrl: vi.fn(() => "/api/v1/partner-pack/logo"),
}));
vi.mock("@/shared/hooks/usePartnerPack", () => packMock);

// The apply dialog is the modules feature's and drags its API along; nothing
// here opens it.
vi.mock("@/features/modules/PartnerPackApplyDialog", () => ({
  PartnerPackApplyDialog: () => null,
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

/* ── Fixtures ───────────────────────────────────────────────────────────── */

function packOf(slug: string, country: string, name: string) {
  return {
    slug,
    partner_name: name,
    type: "country",
    description: `Pre-configured for ${country}: standards, tax and currency`,
    default_locale: "en-US",
    default_currency: "EUR",
    default_tax_template: "de_vat_19",
    pack_version: "0.2.0",
    validation_rule_packs: ["din276"],
    validation_rule_sets: [],
    metadata: { country },
    branding: { primary_color: "#123456", accent_color: null },
  };
}

/** Two of the packs the released wheel carries. Germany is deliberately not
 *  among them: no build a user installs has a German pack, and the tile has to
 *  say so. */
const INSTALLED = [packOf("uk-jct", "GB", "UK JCT"), packOf("india-cpwd", "IN", "India CPWD")];

function packsAnswered(activeSlug: string | null = null) {
  packMock.useInstalledPacks.mockReturnValue({
    isLoading: false,
    data: { active_slug: activeSlug, installed: INSTALLED },
  });
}

function packsInFlight() {
  packMock.useInstalledPacks.mockReturnValue({ isLoading: true, data: undefined });
}

/** Cases per market, read from the shipped catalogue so the suite tracks the
 *  data rather than a copy of it. */
const COUNTS = new Map<string, number>();
for (const pb of PLAYBOOKS) {
  if (pb.region) COUNTS.set(pb.region, (COUNTS.get(pb.region) ?? 0) + 1);
}

function renderHub(language: string) {
  uiLanguage.current = language;
  return render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
}

const tiles = () => screen.getAllByTestId("market-tile");
const marketOf = (tile: HTMLElement) => tile.getAttribute("data-market") ?? "";

/** The case cards, in document order. `role="button"` is written in exactly
 *  one place in CasesPage.tsx, the card root; the shelf tiles are real
 *  buttons and carry no role attribute. */
const cards = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>('[role="button"]'));

beforeEach(() => {
  cleanup();
  localStorage.clear();
  useCasesStore.getState().clearFilters();
  uiLanguage.current = "en";
  packMock.useInstalledPacks.mockReset();
  packsAnswered();
});

describe("market shelf order", () => {
  it("leads with the reader's own market, marks it, and keeps every other market", () => {
    renderHub("de");
    const shelf = tiles();
    expect(marketOf(shelf[0]!)).toBe("DE");
    expect(shelf[0]!.getAttribute("data-home")).toBe("true");
    expect(shelf[0]!.textContent).toContain("Your market");
    // One home market, not one per language the reader might also speak.
    expect(shelf.filter((t) => t.hasAttribute("data-home"))).toHaveLength(1);
    // Nothing dropped: a market with one case is still a tile.
    expect(new Set(shelf.map(marketOf))).toEqual(new Set(COUNTS.keys()));
    // Behind the home market the rest run by size, so the eight one-case
    // markets sit at the end rather than sprinkled through by ISO code.
    const rest = shelf.slice(1).map((t) => COUNTS.get(marketOf(t)) ?? 0);
    expect(rest).toEqual([...rest].sort((a, b) => b - a));
  });

  it("runs the whole shelf by size and marks nothing for a language that names no market", () => {
    // Japanese declares Japan, the catalogue has no Japanese cases, and a
    // badge saying "your market" on the largest market would be a claim about
    // the reader that nothing supports.
    renderHub("ja");
    const shelf = tiles();
    expect(shelf.some((t) => t.hasAttribute("data-home"))).toBe(false);
    const counts = shelf.map((t) => COUNTS.get(marketOf(t)) ?? 0);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
  });

  it("does not reshuffle the shelf when a company filter changes the counts", () => {
    // The tile order is ranked by the whole catalogue; the number on the tile
    // is the filtered one. A shelf that re-sorted itself under the reader's
    // cursor on every filter click would be the same tiles in a new place.
    renderHub("de");
    const before = tiles().map(marketOf);
    const company = screen.getByRole("group", { name: "My company" });
    fireEvent.click(within(company).getAllByRole("button")[0]!);
    expect(tiles().map(marketOf)).toEqual(before);
  });
});

describe("search by country", () => {
  it("finds a market's cases by the country's name in the reader's language", () => {
    const { container } = renderHub("de");
    const german = PLAYBOOKS.filter((pb) => pb.region === "DE");
    expect(german.length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Deutschland" } });
    const found = cards(container);
    expect(found).toHaveLength(german.length);
    const titles = new Set(german.map((pb) => pb.titleDefault));
    for (const card of found) {
      expect(titles.has(card.querySelector("h3")?.textContent ?? "")).toBe(true);
    }
  });

  it("finds the same cases by the English name and by the ISO code", () => {
    // A German reader may well type the English word, and a search that only
    // spoke the UI language would answer them with "No matching cases".
    const { container } = renderHub("de");
    const german = PLAYBOOKS.filter((pb) => pb.region === "DE").length;
    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "germany" } });
    expect(cards(container)).toHaveLength(german);
    fireEvent.change(box, { target: { value: "Japan" } });
    // The control: a country with no cases finds none, so the market terms
    // are matched and not merely appended to every card.
    expect(cards(container)).toHaveLength(0);
  });
});

describe("pack state on the tile", () => {
  it("tells apart a pack switched off, a pack in use and no pack at all", () => {
    renderHub("en");
    const byMarket = new Map(tiles().map((t) => [marketOf(t), t]));
    const gb = byMarket.get("GB")!;
    expect(gb.getAttribute("data-pack-state")).toBe("install");
    expect(gb.textContent).toContain("Needs UK JCT");
    // No German pack ships in any build, and thirteen German cards saying
    // nothing about it is how a reader concluded the install was broken.
    const de = byMarket.get("DE")!;
    expect(de.getAttribute("data-pack-state")).toBe("none");
    expect(de.textContent).toContain("No regional pack");

    cleanup();
    packsAnswered("uk-jct");
    renderHub("en");
    const applied = tiles().find((t) => marketOf(t) === "GB")!;
    expect(applied.getAttribute("data-pack-state")).toBe("installed");
    expect(applied.textContent).toContain("UK JCT");
    expect(applied.textContent).toContain("Active");
    expect(applied.textContent).not.toContain("Needs");
  });

  it("claims nothing about packs before the list has answered", () => {
    // "No regional pack" on every tile for as long as the request takes, then
    // a flip, would be a shelf that changes its mind in front of the reader.
    packsInFlight();
    renderHub("en");
    expect(tiles().some((t) => t.hasAttribute("data-pack-state"))).toBe(false);
  });
});

describe("layout contract", () => {
  it("lets the header wrap below sm, where its action column is full width", () => {
    renderHub("en");
    const row = screen.getByRole("heading", { level: 1 }).closest("div.relative");
    expect(row).not.toBeNull();
    expect(row!.classList.contains("flex-wrap")).toBe(true);
    expect(row!.classList.contains("sm:flex-nowrap")).toBe(true);
  });

  it("lets a long one-word label break inside its tile", () => {
    renderHub("en");
    const company = screen.getByRole("group", { name: "My company" });
    const label = within(company).getByText("General contractor");
    expect(label.classList.contains("break-words")).toBe(true);
    const role = screen.getByRole("group", { name: "Your role" });
    expect(within(role).getByText("Estimator").classList.contains("break-words")).toBe(true);
  });

  it("draws six card columns at xl and keeps eight for 2xl", () => {
    const { container } = renderHub("en");
    const grid = cards(container)[0]!.parentElement!;
    expect(grid.classList.contains("xl:grid-cols-6")).toBe(true);
    expect(grid.classList.contains("2xl:grid-cols-8")).toBe(true);
    expect(grid.classList.contains("xl:grid-cols-8")).toBe(false);
  });
});
