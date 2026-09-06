// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The catalogue card says WHO a case is for and WHERE it goes.
//
// The hub used to spend `companyTypes` entirely on the "I work as..." filter:
// the field decided which cards survived and then said nothing on the card it
// had just selected. Modules were in the same position - `modulesForPlaybook`
// drew the honeycomb on the case page and on the public case pages, and the
// catalogue, which is where a reader decides whether to open a case at all,
// named neither. This suite pins both facts onto the card.
//
// The case page then states in full what the card had room to count, and each
// company it names is a button back to the catalogue narrowed to that kind of
// firm - the behaviour the public case pages give the same cell. That is a
// button here and deliberately NOT one on the card: the card is a single click
// target and a nested control would steal the click that opens the case, while
// this header has no competing target.
//
// What it does NOT pin is placement. Which line the modules sit on and whether
// the company names ride beside the role avatars are layout decisions and may
// change; that a card carries both facts, in the reader's language, is what a
// future edit must not drop silently. The one exception is the module line's
// `title`: the run is clipped and the title is how a sighted reader with a
// mouse gets the part that was cut, so it is pinned on purpose.
//
// The module names are the one part with a trap under it. `types.ts` documents
// at length why `moduleLabel` and `moduleLabelKey` can disagree and why reading
// the label raw looks correct to an English reviewer and reads wrong in the
// other forty-two languages. The card resolves a module the way the honeycomb
// does - key first, the label only as its fallback - and THIS SUITE CANNOT SEE
// THAT. The `t` mocked below answers with the inline default whenever one is
// passed, so a card reading the key and a card reading the label raw print the
// identical string here. That every module ref carries a key is pinned in
// moduleHive.test.tsx; the assertions below compare the card against
// `modulesForPlaybook` so it cannot invent a spelling of its own, which is a
// narrower claim and the only one the harness can actually make.
//
// Run:  npx vitest run src/features/cases/casesCardFacts.test.tsx

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { PLAYBOOKS } from "./playbooks";
import { COMPANY_TYPE_BY_ID } from "./companyTypes";
import { modulesForPlaybook } from "./playbookModules";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

/* ── The same harness casesCardNavigation.test.tsx uses: a stable `t` (the
   shared setup mock mints a fresh one per call and the hub's render-time
   window guard then re-renders forever), react-query and the api layer
   stubbed so the hub's only fetch resolves, and a router that does not
   navigate. ──────────────────────────────────────────────────────────────── */

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
  initialLocaleReady: null,
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

/** The route params the page reads. Mutable, because `CasesPage` is both the
 *  catalogue and the case page - it hands off to the runner when the route
 *  carries a `playbookId` - and a module-scoped mock cannot be re-declared per
 *  describe. Left empty for the catalogue block below and filled in for the
 *  case-page one. */
const routeState = vi.hoisted(() => ({ params: {} as { playbookId?: string } }));

/** One navigate spy for the whole file, not a fresh one per `useNavigate()`
 *  call: the company chip's assertion is about where a click sends you, and a
 *  mock that mints a new function on every render records nothing. */
const nav = vi.hoisted(() => ({ spy: vi.fn() }));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => nav.spy,
    useParams: () => routeState.params,
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** How many of each the card draws before it stops and counts the remainder.
 *  Mirrored from `CaseCard`; a change there is meant to fail here. */
const MODULE_CAP = 3;
const COMPANY_CAP = 2;

/** The case under the lens.
 *
 *  It used to be `PLAYBOOKS[0]`, and that was a defect. `PLAYBOOKS` is built
 *  by `import.meta.glob` over ./data and sorted by `order` then `id`, so which
 *  case sits at index 0 changes the moment anyone drops a file with a lower
 *  order - which is exactly what several authors adding cases in parallel do
 *  all day. The suite then tested a different case on every run, and the
 *  overflow assertions below only mean anything on a case that actually
 *  overflows: a case with three modules has no remainder to count, so the
 *  interesting half of the card went unchecked without saying so.
 *
 *  So the fixture is chosen by the property the assertions need rather than by
 *  position, and the file refuses to run at all if the catalogue stops
 *  containing such a case. Loudly, not by skipping - a suite that quietly
 *  tests nothing is the thing this comment exists to prevent. */
const target =
  PLAYBOOKS.find(
    (pb) =>
      modulesForPlaybook(pb).length > MODULE_CAP &&
      pb.companyTypes.length > COMPANY_CAP,
  ) ??
  (() => {
    throw new Error(
      `No case in the catalogue has both more than ${MODULE_CAP} modules and ` +
        `more than ${COMPANY_CAP} company types, so the card's overflow ` +
        `counts cannot be tested. Searched ${PLAYBOOKS.length} cases.`,
    );
  })();

/** The modules it walks through, and the company types it names, as the words
 *  the card is expected to print. Under the mocked `t` above a key resolves to
 *  its own inline default, so these are the same strings the component builds
 *  - which is the point: the card must print what `modulesForPlaybook` and
 *  `COMPANY_TYPE_BY_ID` hand it, not a spelling of its own. */
const moduleNames = modulesForPlaybook(target).map((m) => m.label);
const companyNames = target.companyTypes.map(
  (id) => COMPANY_TYPE_BY_ID[id]!.labelDefault,
);

/** The card root, mounted once. Every assertion here reads static content, so
 *  a mount per test would buy nothing but four more renders of a 202-card hub -
 *  measured at 132s against 22s.
 *
 *  The tree is DETACHED from `document` after the first test: Testing Library
 *  registers its own `afterEach(cleanup)` when it is imported, and nothing in
 *  this file can hold that off. The rendered subtree survives it intact - text,
 *  attributes, structure - so it is queried in place with `within(card)`, and
 *  `toBeInTheDocument` is deliberately not used: it would be asserting that
 *  cleanup had not run, which is a fact about the harness rather than about the
 *  card. `getByText` still throws when the node is missing, which is the
 *  assertion that matters here. */
let card: HTMLElement;

beforeAll(() => {
  localStorage.clear();
  render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
  // The title appears twice inside one card (resting and hover panel), so the
  // first hit is taken and its card root walked up to.
  const title = screen.getAllByText(target.titleDefault)[0]!;
  const root = title.closest<HTMLElement>('[role="button"]');
  if (!root) throw new Error("Case card root (role=button) not found");
  card = root;
});

describe("the catalogue card names the case's audience and its span", () => {
  it("is testing a case that has both facts to state", () => {
    // A card that says nothing because its case declares nothing would pass
    // every assertion below, so the fixture is checked before it is trusted.
    expect(companyNames.length).toBeGreaterThan(0);
    expect(moduleNames.length).toBeGreaterThan(0);
  });

  it("lists every module the case walks through, whole, in the accessible tree", () => {
    // Whole list, not the visible run: the drawn line is clipped to keep the
    // grid dense, and the clipping must not take the information with it.
    expect(card.textContent).toContain(`Modules: ${moduleNames.join(", ")}`);
  });

  it("prints exactly the names modulesForPlaybook resolves", () => {
    // Not a check that the card reads the KEY rather than the raw label -
    // under the mocked `t` those two produce the identical string and this
    // suite cannot tell them apart. That every module ref carries a key at all
    // is pinned in moduleHive.test.tsx; what is pinned here is narrower and
    // still worth having: the card invents no third spelling of a module name.
    for (const name of moduleNames) {
      expect(card.textContent).toContain(name);
    }
  });

  it("draws the first few module names and counts the rest", () => {
    // The VISIBLE run, not the sentence above it. A card that kept only the
    // accessible copy would satisfy every textContent assertion here and show
    // a sighted reader nothing at all.
    //
    // Scoped to the module line rather than searched across the whole card.
    // The role avatars carry a remainder of the same shape, `+N`, and the two
    // numbers can legitimately be equal, so a card-wide query for the count is
    // ambiguous on some cases and not on others - a difference that depends on
    // which case the catalogue happens to hand over. Inside the line there is
    // exactly one of each, so the singular queries below are unambiguous by
    // construction and no longer care which case this is.
    //
    // The handle is the line's `title`, which is deliberate and not incidental
    // placement: the run is clipped, and the title is the only way a sighted
    // reader with a mouse gets the part that was cut.
    const line = within(card).getByTitle(`Modules: ${moduleNames.join(", ")}`);
    expect(within(line).getByText(moduleNames.slice(0, MODULE_CAP).join(" · ")))
      .toBeTruthy();
    expect(
      within(line).getByText(`+${moduleNames.length - MODULE_CAP}`),
    ).toBeTruthy();
  });

  it("names the kinds of firm the case is written for", () => {
    // The whole list first, as one sentence, for a reader who is not looking
    // at the truncation.
    const sentence = within(card).getByText(
      `Written for: ${companyNames.join(", ")}`,
    );
    // Then the visible run beside the role avatars, scoped to the line that
    // sentence belongs to for the same reason the module line is scoped: the
    // avatars carry a `+N` of their own and the two counts can coincide.
    const line = sentence.parentElement;
    if (!line) throw new Error("The company sentence has no line to sit on");
    expect(
      within(line).getByText(companyNames.slice(0, COMPANY_CAP).join(" · ")),
    ).toBeTruthy();
    expect(
      within(line).getByText(`+${companyNames.length - COMPANY_CAP}`),
    ).toBeTruthy();
  });

  it("keeps the card a single click target - no link or button was added", () => {
    // The pin, the edit control and the regional-pack strip are the only
    // nested buttons a card may carry, and none of the three is mounted here:
    // no pin project, a shipped case, and no pack list because nothing in this
    // file answers `/partner-pack/installed`. Each of them stops the click it
    // catches (see casePackStrip.test.tsx for the strip's own proof). What is
    // banned outright is a link into the filtered list - which is what the
    // public case pages put on their company cell - because a link steals the
    // click the whole card exists to catch and gives nothing back.
    expect(card.querySelectorAll("a")).toHaveLength(0);
    expect(card.querySelectorAll("button")).toHaveLength(0);
  });
});

describe("the case page says in full what the card had room to count", () => {
  /** The whole case page, mounted once, on the same detached-tree terms as the
   *  card above. Nothing else in this tree renders the runner, so without this
   *  block the case page's half of the change is checked by the compiler and by
   *  reading, and by nothing that runs. */
  let page: HTMLElement;

  beforeAll(() => {
    routeState.params = { playbookId: target.id };
    const { container } = render(
      <MemoryRouter initialEntries={[`/cases/${target.id}`]}>
        <CasesPage />
      </MemoryRouter>,
    );
    // The page's own root, not the container Testing Library made for it.
    // Cleanup unmounts into that container and leaves it EMPTY, while the tree
    // it detached survives whole - so a container held across tests reads as a
    // page that rendered nothing, and a node inside the tree reads correctly.
    const root = container.firstElementChild;
    if (!(root instanceof HTMLElement)) {
      throw new Error("Case page rendered nothing");
    }
    page = root;
  });

  it("names every kind of firm the case declares, not only the first two", () => {
    // The card shows two and counts the rest because a catalogue column is
    // narrow; the header is not, so nothing here may be a remainder.
    for (const name of companyNames) {
      expect(
        within(page).getAllByText(name).length,
        `the case page never names "${name}"`,
      ).toBeGreaterThan(0);
    }
  });

  it("still draws the module honeycomb it already had", () => {
    // The company chips landed in the header meta row, one row above the case
    // title; the comb is further down the page and must be untouched by that.
    expect(page.textContent).toContain("Modules this case walks through");
    for (const name of moduleNames) {
      expect(within(page).getAllByText(name).length).toBeGreaterThan(0);
    }
  });
});

describe("the company chip on the case page goes back to a narrowed catalogue", () => {
  /* These mount per test rather than sharing one tree. The two blocks above
     read static markup and can work on a detached tree; a click cannot. React
     unmounts the root at Testing Library's cleanup, and a handler on an
     unmounted root does not fire - the click would land on nothing and the
     assertion would fail for a reason that has nothing to do with the chip.
     One case page is a cheap render; the 202-card hub above is not, which is
     why only this block pays for it. */

  const renderPage = () => {
    routeState.params = { playbookId: target.id };
    const { container } = render(
      <MemoryRouter initialEntries={[`/cases/${target.id}`]}>
        <CasesPage />
      </MemoryRouter>,
    );
    const root = container.firstElementChild;
    if (!(root instanceof HTMLElement)) {
      throw new Error("Case page rendered nothing");
    }
    return root;
  };

  beforeEach(() => {
    nav.spy.mockClear();
    useCasesStore.setState({ companyTypes: [] });
  });

  it("is a real button, typed and focusable, not a div with a handler", () => {
    const page = renderPage();
    for (const name of companyNames) {
      const chip = within(page).getByRole("button", {
        name: `Show cases for ${name}`,
      });
      // `type` matters: an untyped button inside a form submits it.
      expect(chip.getAttribute("type")).toBe("button");
      // A focus ring the keyboard can see. Without it the chip is reachable
      // by tab and invisible once reached, which is worse than not being
      // reachable at all.
      expect(chip.className).toContain("focus-visible:ring");
    }
  });

  it("says what the click does, not just the name of the firm", () => {
    // Eight chips in a row that each announce only "General contractor" tell a
    // screen reader eight nouns and no verbs. The visible text stays the bare
    // name - the header is read by eye too - and the accessible name carries
    // the action.
    const page = renderPage();
    for (const name of companyNames) {
      const chip = within(page).getByRole("button", {
        name: `Show cases for ${name}`,
      });
      expect(chip.textContent).toContain(name);
      expect(chip.textContent).not.toContain("Show cases for");
    }
  });

  it("narrows the catalogue to that one kind of firm and goes there", () => {
    const page = renderPage();
    const chip = within(page).getByRole("button", {
      name: `Show cases for ${companyNames[0]}`,
    });
    fireEvent.click(chip);
    // The selection travels in the store, which is where the hub reads it
    // from. Exactly this company, not added to whatever was already picked:
    // the chip states one answer to "is this me?", not an extra one.
    expect(useCasesStore.getState().companyTypes).toEqual([
      target.companyTypes[0],
    ]);
    expect(nav.spy).toHaveBeenCalledWith("/cases");
  });

  it("leaves the reader's other filters alone", () => {
    // Only the company axis is replaced. Clearing the role, discipline or
    // market someone picked would be the chip deciding more than it was
    // clicked for; the hub's no-matches state is what handles an empty result.
    useCasesStore.setState({ roles: ["estimator"], categories: ["tendering"] });
    const page = renderPage();
    fireEvent.click(
      within(page).getByRole("button", {
        name: `Show cases for ${companyNames[0]}`,
      }),
    );
    expect(useCasesStore.getState().roles).toEqual(["estimator"]);
    expect(useCasesStore.getState().categories).toEqual(["tendering"]);
    useCasesStore.setState({ roles: [], categories: [] });
  });
});
