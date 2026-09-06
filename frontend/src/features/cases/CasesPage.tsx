// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CasesPage - the "Cases" hub.
//
// At /cases it lists every discovered case as a card (title, description, step
// count, time and any progress). At /cases/:playbookId it hands off to the
// PlaybookRunner stepper. One component serves both so the route stays a single
// lazy chunk.
//
// The PRIMARY organizing axis is company type: the "I work as..." selector at
// the top narrows the whole list to the cases actually built for that kind of
// work (general contractor, subcontractor, cost consultant, designer,
// developer/client, project manager, BIM consultant, owner/operator). The
// discipline chips from categories.ts stay as a secondary filter, and a plain
// text search narrows further still. A project picker lets a user pin the
// cases relevant to one of their real projects and, once pinned, show only
// that shortlist - a lightweight, local (no backend) "playbook library for
// this job".

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Route,
  ArrowRight,
  Clock,
  Hexagon,
  ListChecks,
  Layers,
  Search,
  Pin,
  PinOff,
  Briefcase,
  FolderKanban,
  UserRound,
  Flag,
  Globe,
  Loader2,
  FilePlus2,
  PenLine,
  Shuffle,
  Pencil,
  X,
  SlidersHorizontal,
  ChevronDown,
  type LucideProps,
} from "lucide-react";
import {
  Badge,
  Button,
  CountryFlag,
  CountryFlagBackdrop,
  EmptyState,
} from "@/shared/ui";
import { fmtList } from "@/shared/lib/formatters";
import { useNearViewport } from "@/shared/hooks/useNearViewport";
import { useActiveProjectId } from "@/shared/hooks/useActiveProjectId";
import { useProjectContextStore } from "@/stores/useProjectContextStore";
import { projectsApi } from "@/features/projects/api";
import { useAuthStore } from "@/stores/useAuthStore";
import { PartnerPackApplyDialog } from "@/features/modules/PartnerPackApplyDialog";
import { PLAYBOOKS, getPlaybook } from "./playbooks";
import { caseIdFromPlaybookId } from "./api";
import { useAuthoredCases } from "./useCustomCases";
import { PlaybookRunner } from "./PlaybookRunner";
import { MarketPackPanel } from "./MarketPackPanel";
import {
  CasePackStrip,
  useMarketPackOffers,
  type CasePackOffer,
} from "./CasePackStrip";
import { useCasesStore } from "./useCasesStore";
import { completedCount } from "./progress";
import {
  CATEGORY_META,
  CATEGORY_BY_ID,
  tintFor,
  NEUTRAL_TINT,
} from "./categories";
import {
  COMPANY_TYPE_META,
  COMPANY_TYPE_BY_ID,
  tintForCompany,
} from "./companyTypes";
import { ROLE_META, ROLE_BY_ID, rolesForPlaybook, tintForRole } from "./roles";
import { modulesForPlaybook } from "./playbookModules";
import { RoleAvatar } from "./RoleAvatar";
import { RoleArt } from "./RoleArt";
import { CaseArt } from "./CaseArt";
import { Hive } from "./ModuleHive";

import { HEX_PORTRAIT_ASPECT, HEX_PORTRAIT_CLIP } from "@/shared/lib/honeycomb";
import { CompanyArt } from "./CompanyArt";
import { dealCaseFaces, type CaseFace } from "./caseFaces";
import { CaseFacePhoto } from "./CaseFacePhoto";
import {
  STAGE_META,
  STAGE_BY_ID,
  stageForPlaybook,
  buildCaseNumbers,
  type StageMeta,
} from "./stages";

/**
 * How many cards render in the first paint, and how many each scroll step then
 * appends. The Cases hub ships ~85 cards, each with a line-art illustration, so
 * rendering them all at once is the slow part; a small first window plus an
 * IntersectionObserver that reveals the next batch keeps the page instant while
 * still letting search and filters run over the whole catalogue.
 */
const CARD_BATCH_SIZE = 12;
import { iconFor } from "./icons";
import type {
  Playbook,
  CompanyType,
  ProfessionalRole,
  LifecycleStage,
} from "./types";

import { regionDisplayName } from "./regions";
import { homeMarketFirst, homeMarketForLanguage } from "./homeMarket";

export function CasesPage() {
  const { playbookId } = useParams<{ playbookId?: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Authored cases are rows on the server, so the runner can only resolve one
  // once they have arrived. Fetched here, above the detail branch, because a
  // hook cannot sit below a return.
  const { playbooks: authoredPlaybooks, isLoading: authoredLoading } =
    useAuthoredCases();

  // Detail mode: a specific case is open in the runner.
  if (playbookId) {
    // `getPlaybook` only knows the shipped files, and an authored id
    // (`custom-<uuid>`) is not one of them, so the authored list answers first
    // and the bundle answers for everything else.
    const playbook =
      authoredPlaybooks.find((pb) => pb.id === playbookId) ??
      getPlaybook(playbookId);
    if (!playbook) {
      // An id is only genuinely unknown once the authored list has loaded, so
      // "not found" never flashes over a case that is still on its way. Only an
      // authored-looking id waits: a file slug the bundle does not carry is
      // already answered, and making it wait for a fetch would be a regression.
      if (authoredLoading && caseIdFromPlaybookId(playbookId) !== null) {
        return (
          <div
            className="flex items-center justify-center py-16 animate-fade-in"
            role="status"
          >
            <Loader2
              size={22}
              className="animate-spin text-content-tertiary"
              aria-hidden="true"
            />
            <span className="sr-only">
              {t("cases.loading_case", { defaultValue: "Loading case..." })}
            </span>
          </div>
        );
      }
      return (
        <div className="py-8 animate-fade-in">
          <EmptyState
            icon={<Route size={28} />}
            title={t("cases.not_found_title", {
              defaultValue: "Case not found",
            })}
            description={t("cases.not_found_body", {
              defaultValue:
                "This case does not exist or was removed. Browse the full list instead.",
            })}
            action={{
              label: t("cases.back_to_list", { defaultValue: "All cases" }),
              onClick: () => navigate("/cases"),
            }}
          />
        </div>
      );
    }
    return <PlaybookRunner playbook={playbook} />;
  }

  // List mode.
  return <CasesList />;
}

function CasesList() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const runs = useCasesStore((s) => s.runs);
  // Each of the three "who/what" filters holds a list, not one id: a user can
  // be a contractor and a consultant, or run both estimating and planning
  // cases, and the hub has to show all of it. OR inside a filter, AND between
  // filters - the ordinary faceted-search rule, so adding a role never widens
  // the result.
  const companyTypes = useCasesStore((s) => s.companyTypes);
  const toggleCompanyType = useCasesStore((s) => s.toggleCompanyType);
  const roles = useCasesStore((s) => s.roles);
  const toggleRole = useCasesStore((s) => s.toggleRole);
  const activeCategories = useCasesStore((s) => s.categories);
  const toggleCategory = useCasesStore((s) => s.toggleCategory);
  const setCompanyTypes = useCasesStore((s) => s.setCompanyTypes);
  const setRoles = useCasesStore((s) => s.setRoles);
  const setCategories = useCasesStore((s) => s.setCategories);
  const clearFilters = useCasesStore((s) => s.clearFilters);
  const finderOpen = useCasesStore((s) => s.finderOpen);
  const setFinderOpen = useCasesStore((s) => s.setFinderOpen);
  // The project this hub pins cases to is the app-wide active project - the
  // one the top-bar switcher writes. The hub used to keep its own copy in
  // `useCasesStore.pinProjectId` (localStorage `oe_cases_pin_project`), which
  // nothing else ever wrote, so picking a project in the top bar left this
  // picker reading "No project selected" (issue #413). Reading the shared
  // context here removes the second source of truth rather than syncing it.
  const pinProjectId = useActiveProjectId();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const clearActiveProject = useProjectContextStore((s) => s.clearProject);
  const pins = useCasesStore((s) => s.pins);
  const togglePin = useCasesStore((s) => s.togglePin);
  const [query, setQuery] = useState("");
  const [activeStage, setActiveStage] = useState<LifecycleStage | "all">("all");
  // Market filter: narrows to the cases authored for one market's standards
  // (Playbook.region). Held in the store beside company, role and discipline,
  // and persisted like them. It was local state, which meant it silently
  // dropped on every return to the hub while the other three came back - read
  // by a user as the market selector being broken, not as a statement that a
  // market describes only this visit.
  const activeRegion = useCasesStore((s) => s.region);
  const setRegion = useCasesStore((s) => s.setRegion);
  const [showOnlyPinned, setShowOnlyPinned] = useState(false);

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: projectsApi.list,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const sortedProjects = useMemo(
    () => [...(projects ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [projects],
  );
  const pinnedIds = useMemo(
    () => (pinProjectId ? (pins[pinProjectId] ?? []) : []),
    [pinProjectId, pins],
  );

  // Authored cases stand beside the shipped ones from here on. `allPlaybooks`
  // is the catalogue every filter, count, number and card below reads, so a
  // case somebody wrote is narrowed, counted and drawn exactly like one we
  // ship - one list rather than a concatenation repeated at each use. When the
  // fetch fails the shipped list is what is left, which is a shorter list, not
  // a broken screen (see `useAuthoredCases`).
  const { playbooks: authoredPlaybooks } = useAuthoredCases();
  const allPlaybooks = useMemo(
    () =>
      authoredPlaybooks.length > 0
        ? [...PLAYBOOKS, ...authoredPlaybooks]
        : PLAYBOOKS,
    [authoredPlaybooks],
  );

  // The person on each card, dealt over the WHOLE catalogue rather than over
  // the narrowed or windowed list: a case wears its face because of where it
  // sits among the cases for its company type, and clicking a filter must not
  // re-cast the cards that survive it.
  const facesByPlaybook = useMemo(() => dealCaseFaces(allPlaybooks), [allPlaybooks]);

  // Best progress for a card = the furthest a user got on this case across any
  // run (unscoped or scoped to a sample project).
  const bestDoneFor = useMemo(() => {
    return (pb: Playbook): number => {
      let best = 0;
      for (const [k, prog] of Object.entries(runs)) {
        if (k === pb.id || k.startsWith(`${pb.id}::`)) {
          best = Math.max(best, completedCount(prog, pb));
        }
      }
      return best;
    };
  }, [runs]);

  // Resolve every case's professional roles once (explicit or derived) so the
  // role filter and the per-role counts are cheap.
  const rolesByPlaybook = useMemo(() => {
    const m = new Map<string, ProfessionalRole[]>();
    for (const pb of allPlaybooks) m.set(pb.id, rolesForPlaybook(pb));
    return m;
  }, [allPlaybooks]);
  const caseHasRole = useMemo(
    () => (pb: Playbook, r: ProfessionalRole) =>
      rolesByPlaybook.get(pb.id)?.includes(r) ?? false,
    [rolesByPlaybook],
  );

  // Lifecycle stage + a stable case number (1..N, ordered start of project to
  // end) for every case, so the timeline and the numbered cards read in order.
  const stageByPlaybook = useMemo(() => {
    const m = new Map<string, LifecycleStage>();
    for (const pb of allPlaybooks) m.set(pb.id, stageForPlaybook(pb));
    return m;
  }, [allPlaybooks]);
  const caseNumbers = useMemo(
    () => buildCaseNumbers(allPlaybooks),
    [allPlaybooks],
  );
  const inStage = useMemo(
    () => (pb: Playbook) =>
      activeStage === "all" || stageByPlaybook.get(pb.id) === activeStage,
    [activeStage, stageByPlaybook],
  );

  // Three filters narrow the same list: company type, professional role and
  // discipline. Each one is a list of picks and an empty list means "no filter",
  // so a case matches when it satisfies ANY pick in a list (union) and EVERY
  // list that has picks (intersection).
  const inCompany = useCallback(
    (p: Playbook) =>
      companyTypes.length === 0 ||
      p.companyTypes.some((c) => companyTypes.includes(c)),
    [companyTypes],
  );
  const inRole = useCallback(
    (p: Playbook) => roles.length === 0 || roles.some((r) => caseHasRole(p, r)),
    [roles, caseHasRole],
  );
  const inCategory = useCallback(
    (p: Playbook) =>
      activeCategories.length === 0 || activeCategories.includes(p.category),
    [activeCategories],
  );
  // The market row only exists when at least one case carries a region, so a
  // catalogue without market-specific cases keeps exactly the layout it had.
  const regions = useMemo(
    () =>
      [
        ...new Set(
          allPlaybooks
            .map((p) => p.region)
            .filter((r): r is string => Boolean(r)),
        ),
      ].sort(),
    [allPlaybooks],
  );
  const inRegion = useCallback(
    (p: Playbook) => activeRegion === "all" || p.region === activeRegion,
    [activeRegion],
  );
  // The pack that serves each of those markets, resolved once for the whole
  // grid rather than per card: twelve cards mount per batch and every one of
  // them would otherwise run the same match over the same list of packs.
  const packOffers = useMarketPackOffers(regions);
  // Applying a pack is admin-only in the backend (`RequireRole("admin")` on
  // /apply and /full-install-stream), so the card says so rather than offering
  // a button that would come back 403.
  const canInstallPack = useAuthStore((s) => s.userRole) === "admin";
  // ONE dialog for the whole grid. It is the same dialog the Modules page and
  // the case page open - a dry run of what changes, an explicit confirm for
  // the modules it would switch off, then a streamed install with named steps
  // - and a copy of it per card would be twelve mounted previews of nothing.
  const [packToInstall, setPackToInstall] = useState<CasePackOffer | null>(
    null,
  );
  // The market the reader's UI language speaks for, when the catalogue has
  // cases for it. Five of the forty-two languages reach one; the rest reach
  // null, and null is the whole behaviour for them - the catalogue keeps the
  // order it always had.
  //
  // This ORDERS the grid, it does not narrow it: the market stays a shelf, and
  // the reasoning above the shelf still holds, because a language default that
  // preselected a country would hide the 140 universal cases from exactly the
  // readers whose language names a market. Nor does it write anything: the
  // hub's market pick is persisted (`oe_cases_region`), and a stored pick this
  // never touches is a stored pick this can never overwrite.
  const homeMarket = useMemo(
    () => homeMarketForLanguage(i18n.language, regions),
    [i18n.language, regions],
  );

  // Only surface a selector option that actually has a matching case, and scope
  // each option's availability + count by the OTHER two active filters, so a
  // count always describes what clicking it would really show.
  const byCategoryRole = useMemo(
    () =>
      allPlaybooks.filter(
        (p) => inCategory(p) && inRole(p) && inStage(p) && inRegion(p),
      ),
    [allPlaybooks, inCategory, inRole, inStage, inRegion],
  );
  const byCompanyRole = useMemo(
    () =>
      allPlaybooks.filter(
        (p) => inCompany(p) && inRole(p) && inStage(p) && inRegion(p),
      ),
    [allPlaybooks, inCompany, inRole, inStage, inRegion],
  );
  const byCompanyCategory = useMemo(
    () =>
      allPlaybooks.filter(
        (p) => inCompany(p) && inCategory(p) && inStage(p) && inRegion(p),
      ),
    [allPlaybooks, inCompany, inCategory, inStage, inRegion],
  );
  // Stage availability + counts are scoped by the who/discipline filters but
  // NOT by the active stage itself (so every reachable stage stays clickable).
  const byCompanyRoleCategory = useMemo(
    () =>
      allPlaybooks.filter(
        (p) => inCompany(p) && inRole(p) && inCategory(p) && inRegion(p),
      ),
    [allPlaybooks, inCompany, inRole, inCategory, inRegion],
  );
  // Market counts mirror the stage rule: scoped by every other filter, never
  // by the market itself, so a picked market can always be unpicked.
  const byAllButRegion = useMemo(
    () =>
      allPlaybooks.filter(
        (p) => inCompany(p) && inRole(p) && inCategory(p) && inStage(p),
      ),
    [allPlaybooks, inCompany, inRole, inCategory, inStage],
  );
  // An option the user has picked stays in its own row even when the other
  // filters leave it with no matching case. Dropping it would take away the
  // only control that undoes the empty result the user is looking at.
  const availableCompanyTypes = useMemo(() => {
    const present = new Set(byCategoryRole.flatMap((p) => p.companyTypes));
    return COMPANY_TYPE_META.filter(
      (c) => present.has(c.id) || companyTypes.includes(c.id),
    );
  }, [byCategoryRole, companyTypes]);
  const availableCategories = useMemo(() => {
    const present = new Set(byCompanyRole.map((p) => p.category));
    return CATEGORY_META.filter(
      (c) => present.has(c.id) || activeCategories.includes(c.id),
    );
  }, [byCompanyRole, activeCategories]);
  const availableRoles = useMemo(() => {
    const present = new Set(
      byCompanyCategory.flatMap((p) => rolesByPlaybook.get(p.id) ?? []),
    );
    return ROLE_META.filter((r) => present.has(r.id) || roles.includes(r.id));
  }, [byCompanyCategory, rolesByPlaybook, roles]);
  // One entry per active pick, ordered the way the selector rows are ordered
  // on screen, each carrying the control that takes itself off.
  //
  // The market and the stage were both missing from this list, and the cost
  // was larger than a missing chip. This same list gates the summary strip AND
  // the "Reset filters" link, so a market-only pick narrowed 202 cases to 13
  // with nothing on screen naming the market and no control to undo it short
  // of reopening a panel that had folded itself away. Market comes first
  // because its shelf now sits above everything else on the page.
  const activeFilterChips = useMemo(
    () => [
      ...(activeRegion !== "all"
        ? [
            {
              kind: "market" as const,
              id: activeRegion,
              label: regionDisplayName(activeRegion, i18n.language),
              remove: () => setRegion("all"),
            },
          ]
        : []),
      ...(activeStage !== "all"
        ? [
            {
              kind: "stage" as const,
              id: activeStage as string,
              label: t(STAGE_BY_ID[activeStage]?.labelKey ?? "", {
                defaultValue: STAGE_BY_ID[activeStage]?.labelDefault ?? "",
              }),
              remove: () => setActiveStage("all"),
            },
          ]
        : []),
      ...companyTypes.map((id) => ({
        kind: "company" as const,
        id: id as string,
        label: t(COMPANY_TYPE_BY_ID[id]?.labelKey ?? "", {
          defaultValue: COMPANY_TYPE_BY_ID[id]?.labelDefault ?? "",
        }),
        remove: () => toggleCompanyType(id),
      })),
      ...roles.map((id) => ({
        kind: "role" as const,
        id: id as string,
        label: t(ROLE_BY_ID[id]?.labelKey ?? "", {
          defaultValue: ROLE_BY_ID[id]?.labelDefault ?? "",
        }),
        remove: () => toggleRole(id),
      })),
      ...activeCategories.map((id) => ({
        kind: "category" as const,
        id: id as string,
        label: t(CATEGORY_BY_ID[id]?.labelKey ?? "", {
          defaultValue: CATEGORY_BY_ID[id]?.labelDefault ?? "",
        }),
        remove: () => toggleCategory(id),
      })),
    ],
    [
      activeRegion,
      activeStage,
      setRegion,
      i18n.language,
      companyTypes,
      roles,
      activeCategories,
      toggleCompanyType,
      toggleRole,
      toggleCategory,
      t,
    ],
  );

  const availableStages = useMemo(() => {
    const present = new Set(
      byCompanyRoleCategory.map((p) => stageByPlaybook.get(p.id)),
    );
    return STAGE_META.filter((s) => present.has(s.id));
  }, [byCompanyRoleCategory, stageByPlaybook]);

  // Filter by company type, role, category chip, the pinned-for-project
  // shortlist and a plain title/description text search. All narrow the list.
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = allPlaybooks.filter((pb) => {
      if (!inCompany(pb)) return false;
      if (!inRole(pb)) return false;
      if (activeStage !== "all" && stageByPlaybook.get(pb.id) !== activeStage)
        return false;
      if (!inCategory(pb)) return false;
      if (!inRegion(pb)) return false;
      if (showOnlyPinned && !pinnedIds.includes(pb.id)) return false;
      if (!q) return true;
      const haystack =
        `${t(pb.titleKey, { defaultValue: pb.titleDefault })} ${t(pb.descKey, {
          defaultValue: pb.descDefault,
        })}`.toLowerCase();
      return haystack.includes(q);
    });
    // Then order it: the reader's own market in front, the rest of the
    // catalogue behind it in the lifecycle order it always had. Not when the
    // shortlist is showing - that list is the set this reader curated for this
    // job, and re-ordering somebody's own shelf by their language is noise.
    return homeMarketFirst(
      matched,
      showOnlyPinned ? null : homeMarket,
      (pb) => caseNumbers.get(pb.id) ?? 0,
    );
  }, [
    allPlaybooks,
    query,
    activeStage,
    stageByPlaybook,
    inCompany,
    inRole,
    inCategory,
    inRegion,
    showOnlyPinned,
    pinnedIds,
    caseNumbers,
    homeMarket,
    t,
  ]);

  // Progressive rendering: search and every filter above run over the FULL
  // catalogue (`visible`), then we only mount the first window of that result
  // and reveal more as the user scrolls. `visible` gets a fresh reference each
  // time a filter or the search changes, so tracking its identity lets us snap
  // the window back to the first batch on any filter change (same render-time
  // pattern the art tiles use to reset on reuse) - no flash of a deep scroll.
  const [cardLimit, setCardLimit] = useState(CARD_BATCH_SIZE);
  const [lastVisible, setLastVisible] = useState(visible);
  if (lastVisible !== visible) {
    setLastVisible(visible);
    setCardLimit(CARD_BATCH_SIZE);
  }
  const windowed = visible.slice(0, cardLimit);
  const hasMore = cardLimit < visible.length;

  // Reveal the next batch when the sentinel at the end of the list nears the
  // viewport. A generous rootMargin loads the next cards before the user hits
  // the bottom, so scrolling stays smooth. Without IntersectionObserver (older
  // browsers, JSDOM) we reveal everything so nothing is ever stuck hidden; the
  // visible "Show more" button also covers keyboard and no-observer use.
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    if (cardLimit >= visible.length) return;
    if (typeof IntersectionObserver === "undefined") {
      setCardLimit(visible.length);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setCardLimit((n) => Math.min(n + CARD_BATCH_SIZE, visible.length));
        }
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
    // Re-running on `cardLimit` re-checks intersection after each reveal, so if
    // the sentinel is still near the fold the next batch keeps loading (the same
    // chaining the cost-search modal uses). Card shells are cheap; each card
    // still defers its own illustration until it is itself near the fold.
  }, [cardLimit, visible.length]);

  const handlePickCompany = (id: CompanyType) => {
    toggleCompanyType(id);
  };
  const handlePickRole = (id: ProfessionalRole) => {
    toggleRole(id);
  };
  const handlePickStage = (id: LifecycleStage) => {
    setActiveStage(activeStage === id ? "all" : id);
  };

  // The store clears what it owns - company, role, discipline and now the
  // market. The stage is view-local, so it is cleared here. Both "Clear"
  // controls call this: a chip the user can see next to a Clear button that
  // leaves it standing is worse than no Clear button at all.
  const clearAllFilters = useCallback(() => {
    clearFilters();
    setActiveStage("all");
  }, [clearFilters]);

  // A hub of this many cases is easy to bounce off: none of them is wrong, so none of
  // them is obviously the one to open. This opens one at random from whatever
  // the filters currently leave on screen, so it stays inside the discipline
  // and role the reader already chose rather than throwing them anywhere.
  const openRandomCase = useCallback(() => {
    const pool = visible.length > 0 ? visible : allPlaybooks;
    const pick = pool[Math.floor(Math.random() * pool.length)];
    if (pick) navigate(`/cases/${pick.id}`);
  }, [visible, allPlaybooks, navigate]);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl border border-border-light bg-gradient-to-br from-oe-blue/[0.08] via-oe-blue/[0.03] to-transparent p-5">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-oe-blue/10 blur-3xl"
        />
        <div className="relative flex items-start gap-3">
          <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue/15 text-oe-blue ring-1 ring-inset ring-oe-blue/25">
            <Route size={22} strokeWidth={1.9} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight text-content-primary">
                {t("cases.page_title", { defaultValue: "Cases" })}
              </h1>
              {allPlaybooks.length > 0 && (
                <span className="inline-flex items-center rounded-full bg-oe-blue/10 px-2 py-0.5 text-2xs font-semibold text-oe-blue ring-1 ring-inset ring-oe-blue/20">
                  {t("cases.header.count", {
                    defaultValue: "{{count}} guided cases",
                    count: allPlaybooks.length,
                  })}
                </span>
              )}
            </div>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-content-secondary">
              {t("cases.page_subtitle", {
                defaultValue:
                  "Guided, end-to-end playbooks that walk you through several modules in order. Pick a case, optionally choose a sample project to learn on, and follow each step.",
              })}
            </p>
          </div>
          {/* The catalogue is not only ours: a user writes their own case the
              way their firm actually works, and it then lives in this same hub
              beside the shipped ones. That route used to be a small button in
              the corner, which reads as a footnote rather than as half of what
              this page is for.

              Three actions, because they are one decision asked three ways:
              write one starting from ours, write one from nothing, or just
              show me a case. The third exists because a hub of 144 equally
              good things is easy to bounce off. */}
          <div className="flex w-full shrink-0 flex-col gap-2 sm:w-auto">
            <Button
              variant="primary"
              size="lg"
              icon={<PenLine size={16} />}
              onClick={() => navigate("/cases/new")}
              className="w-full justify-center sm:w-auto"
            >
              {t("cases.write_own", { defaultValue: "Write your own case" })}
            </Button>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<FilePlus2 size={13} />}
                onClick={() => navigate("/cases/new?blank=1")}
                className="flex-1 justify-center"
              >
                {t("cases.write_blank", { defaultValue: "From blank" })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Shuffle size={13} />}
                onClick={openRandomCase}
                className="flex-1 justify-center"
              >
                {t("cases.show_me_one", { defaultValue: "Show me one" })}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {allPlaybooks.length > 0 && (
        <>
          {/* ── Market ───────────────────────────────────────────────────────
              The country a case is written for is not one more facet like a
              discipline. A discipline narrows what a case is ABOUT; a market
              decides whether the case is legal where you work. It used to sit
              inside the folding panel below as a row of pill chips identical
              to the discipline chips, two type sizes under the lifecycle cards
              beside it, and it folded itself away entirely for anyone who had
              already picked a persona - so the one axis nobody can substitute
              for was the one hardest to see.

              Country is a SHELF, not the catalogue's spine. Grouping the whole
              list by market was considered and rejected on the count: 140 of
              220 cases carry no region, so a country grouping yields fifteen
              small labelled sections and one bucket holding 64% of the
              catalogue under "everything else". (Counted from ./data; the
              catalogue grows, so re-count before leaning on the figures. The
              denominator read 202 for a while after eighteen cases landed,
              every one of them carrying a market, which is why the numerator
              did not move and the staleness did not show.)
              Those cases are universal on
              purpose (see the `region` doc in ./types.ts), so that bucket is
              the product rather than a backlog to be worked off.

              A market with a single case still gets a card. A shelf that shows
              the big markets and quietly drops the small one is invisible
              exactly to the reader who came looking for it, and it decays: the
              day a second case lands the market appears from nowhere and
              nobody remembers why. ──────────────────────────────────────────*/}
          {regions.length > 0 && (
            <section className="relative overflow-hidden rounded-2xl border border-border-light bg-surface-primary p-3.5">
              {/* The founder's own visual language for "this surface is scoped
                  to a country", already carrying /costs and /catalog.
                  Composition contract: this block owns the `relative`, this is
                  its FIRST child, and there is no `isolate` or z-index on a
                  page root - that traps fixed modals under the sticky header
                  and the symptom appears nowhere near the cause. */}
              <CountryFlagBackdrop
                code={activeRegion !== "all" ? activeRegion : null}
                variant="panel"
              />
              <div className="relative">
                <div className="mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <Globe
                    size={15}
                    className="shrink-0 text-content-tertiary"
                    aria-hidden="true"
                  />
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                    {t("cases.region_selector.heading", {
                      defaultValue: "Market",
                    })}
                  </h2>
                  <span className="text-2xs text-content-tertiary">
                    {t("cases.region_selector.subtitle", {
                      defaultValue:
                        "Cases written for one country's standards, forms and payment law.",
                    })}
                  </span>
                  {activeRegion !== "all" && (
                    <button
                      type="button"
                      onClick={() => setRegion("all")}
                      className="text-2xs font-medium text-oe-blue hover:underline"
                    >
                      {t("cases.region_selector.all", {
                        defaultValue: "All markets",
                      })}
                    </button>
                  )}
                </div>
                <div
                  className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
                  role="group"
                  aria-label={t("cases.region_selector.heading", {
                    defaultValue: "Market",
                  })}
                >
                  {regions.map((r) => {
                    const active = activeRegion === r;
                    const count = byAllButRegion.filter(
                      (p) => p.region === r,
                    ).length;
                    return (
                      <button
                        key={r}
                        type="button"
                        onClick={() => setRegion(active ? "all" : r)}
                        aria-pressed={active}
                        className={clsx(
                          "flex items-center gap-2.5 rounded-xl border p-2.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
                          active
                            ? "border-oe-blue bg-oe-blue/10 text-oe-blue shadow-sm"
                            : "border-border-light bg-surface-primary text-content-primary hover:border-oe-blue/30",
                        )}
                      >
                        <CountryFlag
                          code={r.toLowerCase()}
                          size={44}
                          className="shrink-0 shadow-sm ring-1 ring-inset ring-black/10"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-semibold leading-tight">
                            {regionDisplayName(r, i18n.language)}
                          </span>
                          <span
                            className={clsx(
                              "mt-0.5 block text-2xs tabular-nums",
                              active ? "opacity-80" : "text-content-tertiary",
                            )}
                          >
                            {t("cases.selector.count", {
                              defaultValue: "{{count}} cases",
                              count,
                            })}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

          {/* ── Find your case ───────────────────────────────────────────────
              The three "where am I / who am I" selectors used to be three
              full-width blocks stacked one under another, each with its own
              heading and its own gap, and together they pushed the catalogue
              off the first screen. They are one question asked three ways, so
              they are one panel: the lifecycle across the top because it is
              the ordered map, then company and role side by side because they
              are both "who is asking".

              The panel folds. Someone arriving needs to see that the filters
              exist; someone who has already answered wants the cases. So it
              opens on a first visit, starts folded once anything is picked,
              and the toggle overrides both and is remembered. The summary
              strip below the panel keeps naming every active pick either way,
              so folding never hides what the list is filtered to. */}
          <section className="rounded-2xl border border-border-light bg-surface-primary">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3.5 py-2.5">
              <SlidersHorizontal
                size={15}
                className="shrink-0 text-content-tertiary"
                aria-hidden="true"
              />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t("cases.finder.heading", { defaultValue: "Find your case" })}
              </h2>
              <p className="min-w-0 flex-1 text-2xs leading-relaxed text-content-tertiary">
                {t("cases.hub_howto", {
                  defaultValue:
                    "New here? Pick where you are in the project, the kind of company you work for, and your role, and the list narrows to the cases that matter to you.",
                })}
              </p>
              {activeFilterChips.length > 0 && (
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className="shrink-0 text-2xs font-medium text-oe-blue hover:underline"
                >
                  {t("cases.finder.reset", { defaultValue: "Reset filters" })}
                </button>
              )}
              <button
                type="button"
                onClick={() => setFinderOpen(!finderOpen)}
                aria-expanded={finderOpen}
                aria-controls="cases-finder-body"
                className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border-light px-2.5 py-1 text-2xs font-medium text-content-secondary transition-colors hover:border-oe-blue/30 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                <ChevronDown
                  size={12}
                  aria-hidden="true"
                  className={clsx(
                    "transition-transform motion-reduce:transition-none",
                    finderOpen && "rotate-180",
                  )}
                />
                {finderOpen
                  ? t("cases.finder.hide", { defaultValue: "Hide" })
                  : t("cases.finder.show", { defaultValue: "Change" })}
              </button>
            </div>

            {finderOpen && (
              <div
                id="cases-finder-body"
                className="space-y-3 border-t border-border-light p-3"
              >
                {/* ── Project lifecycle: cases from start to finish ───────── */}
                <div>
                  <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <Flag
                      size={13}
                      className="text-content-tertiary"
                      aria-hidden="true"
                    />
                    <h3 className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
                      {t("cases.stage_selector.heading", {
                        defaultValue: "Project lifecycle",
                      })}
                    </h3>
                    <span className="text-2xs text-content-tertiary">
                      {t("cases.stage_selector.subtitle", {
                        defaultValue:
                          "Cases laid out in the order a project runs, start to finish.",
                      })}
                    </span>
                  </div>
                  {/* Eight stage cards in lifecycle order, each led by a
                      numbered tile so the row reads as the ordered journey
                      rather than as one more set of chips. */}
                  <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-2 dark:bg-white/[0.03]">
              <div
                className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8"
                role="group"
                aria-label={t("cases.stage_selector.heading", {
                  defaultValue: "Project lifecycle",
                })}
              >
                {STAGE_META.map((s) => {
                  const Icon = s.icon;
                  const active = activeStage === s.id;
                  const count = byCompanyRoleCategory.filter(
                    (p) => stageByPlaybook.get(p.id) === s.id,
                  ).length;
                  const disabled =
                    !availableStages.some((a) => a.id === s.id) && !active;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => handlePickStage(s.id)}
                      aria-pressed={active}
                      disabled={disabled}
                      title={t(s.descKey, { defaultValue: s.descDefault })}
                      className={clsx(
                        "group flex items-center gap-2 rounded-xl border p-1.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
                        active
                          ? clsx(s.tint.chip, "shadow-sm")
                          : "border-border-light bg-surface-primary text-content-primary hover:border-oe-blue/30",
                        disabled && "cursor-not-allowed opacity-40",
                      )}
                    >
                      {/* Numbered stage tile - the corner number signals the
                          ordered journey (this is the top-level lifecycle map). */}
                      <span
                        className={clsx(
                          "relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset",
                          s.tint.tile,
                        )}
                      >
                        <Icon size={15} strokeWidth={1.8} aria-hidden="true" />
                        <span
                          className={clsx(
                            "absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold tabular-nums shadow-sm",
                            active
                              ? "bg-white text-current dark:bg-black/40"
                              : "bg-surface-primary text-content-secondary ring-1 ring-inset ring-border-light",
                          )}
                        >
                          {s.num}
                        </span>
                      </span>
                      <span className="min-w-0 flex-1">
                        <span
                          className={clsx(
                            "block text-xs font-semibold leading-tight",
                            !active && "text-content-primary",
                          )}
                        >
                          {t(s.labelKey, { defaultValue: s.labelDefault })}
                        </span>
                        <span
                          className={clsx(
                            "mt-0.5 block text-2xs tabular-nums",
                            active ? "opacity-80" : "text-content-tertiary",
                          )}
                        >
                          {t("cases.selector.count", {
                            defaultValue: "{{count}} cases",
                            count,
                          })}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
                  {activeStage !== "all" && (
                    <button
                      type="button"
                      onClick={() => setActiveStage("all")}
                      className="mt-1.5 text-2xs font-medium text-oe-blue hover:underline"
                    >
                      {t("cases.stage_selector.all", {
                        defaultValue: "All stages",
                      })}
                    </button>
                  )}
                </div>

                {/* Company and role side by side on a wide screen. They answer
                    the same question, "who is asking", and stacking them cost a
                    whole screen of height for no gain. Eight company cards in
                    three columns and twelve role cards in four come out the
                    same three rows deep, so the two columns end level. */}
                <div className="grid gap-x-5 gap-y-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                  {/* ── "I work as..." company-type selector ─────────────── */}
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <Briefcase
                        size={13}
                        className="text-content-tertiary"
                        aria-hidden="true"
                      />
                      <h3 className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
                        {t("cases.company_selector.heading", {
                          defaultValue: "My company",
                        })}
                      </h3>
                      <span className="text-2xs text-content-tertiary">
                        {t("cases.company_selector.subtitle", {
                          defaultValue: "Pick the kind of firm you work for.",
                        })}
                      </span>
                    </div>
            <div
              className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-3"
              role="group"
              aria-label={t("cases.company_selector.heading", {
                defaultValue: "My company",
              })}
            >
              {COMPANY_TYPE_META.map((c) => {
                const Icon = c.icon;
                const active = companyTypes.includes(c.id);
                const count = byCategoryRole.filter((p) =>
                  p.companyTypes.includes(c.id),
                ).length;
                const disabled =
                  !availableCompanyTypes.some((a) => a.id === c.id) && !active;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => handlePickCompany(c.id)}
                    aria-pressed={active}
                    disabled={disabled}
                    className={clsx(
                      "flex items-center gap-2 rounded-xl border p-1.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
                      active
                        ? clsx(c.tint.chip, "shadow-sm")
                        : "border-border-light bg-surface-primary text-content-primary hover:border-oe-blue/30",
                      disabled && "cursor-not-allowed opacity-40",
                    )}
                  >
                    <CompanyArt
                      id={c.id}
                      fallbackIcon={Icon}
                      fallbackClass={c.tint.text}
                      tileClass={c.tint.tile}
                      withKindBadge
                      className="h-9 w-9 shrink-0"
                      title={t(c.labelKey, { defaultValue: c.labelDefault })}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-semibold leading-tight">
                        {t(c.labelKey, { defaultValue: c.labelDefault })}
                      </span>
                      <span className="mt-0.5 block text-2xs tabular-nums text-content-tertiary">
                        {t("cases.selector.count", {
                          defaultValue: "{{count}} cases",
                          count,
                        })}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
                    {companyTypes.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setCompanyTypes([])}
                        className="mt-1.5 text-2xs font-medium text-oe-blue hover:underline"
                      >
                        {t("cases.company_selector.all", {
                          defaultValue: "All company types",
                        })}
                      </button>
                    )}
                  </div>

                  {/* ── "Your role" avatar selector ──────────────────────── */}
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <UserRound
                        size={13}
                        className="text-content-tertiary"
                        aria-hidden="true"
                      />
                      <h3 className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
                        {t("cases.role_selector.heading", {
                          defaultValue: "Your role",
                        })}
                      </h3>
                      <span className="text-2xs text-content-tertiary">
                        {t("cases.role_selector.subtitle", {
                          defaultValue:
                            "Pick what you do day to day for a tighter list.",
                        })}
                      </span>
                    </div>
            <div
              className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4"
              role="group"
              aria-label={t("cases.role_selector.heading", {
                defaultValue: "Your role",
              })}
            >
              {ROLE_META.map((r) => {
                const active = roles.includes(r.id);
                const count = byCompanyCategory.filter((p) =>
                  caseHasRole(p, r.id),
                ).length;
                const disabled =
                  !availableRoles.some((a) => a.id === r.id) && !active;
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => handlePickRole(r.id)}
                    aria-pressed={active}
                    disabled={disabled}
                    className={clsx(
                      "flex items-center gap-2 rounded-xl border p-1.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
                      active
                        ? clsx(r.tint.chip, "shadow-sm")
                        : "border-border-light bg-surface-primary text-content-primary hover:border-oe-blue/30",
                      disabled && "cursor-not-allowed opacity-40",
                    )}
                  >
                    <RoleArt
                      role={r.id}
                      withKindBadge
                      className="h-9 w-9 shrink-0"
                      title={t(r.labelKey, { defaultValue: r.labelDefault })}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-semibold leading-tight">
                        {t(r.labelKey, { defaultValue: r.labelDefault })}
                      </span>
                      <span className="mt-0.5 block text-2xs tabular-nums text-content-tertiary">
                        {t("cases.selector.count", {
                          defaultValue: "{{count}} cases",
                          count,
                        })}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
                    {roles.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setRoles([])}
                        className="mt-1.5 text-2xs font-medium text-oe-blue hover:underline"
                      >
                        {t("cases.role_selector.all", {
                          defaultValue: "All roles",
                        })}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* ── Project pin bar ───────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-border-light bg-surface-secondary/40 px-3 py-2">
            <FolderKanban
              size={15}
              className="shrink-0 text-content-tertiary"
              aria-hidden="true"
            />
            <label htmlFor="cases-pin-project" className="sr-only">
              {t("cases.project_pin.picker_label", { defaultValue: "Project" })}
            </label>
            <select
              id="cases-pin-project"
              value={pinProjectId}
              onChange={(e) => {
                const nextId = e.target.value;
                const next = sortedProjects.find((p) => p.id === nextId);
                // Same control, same store as the top-bar switcher: picking a
                // project here moves the whole app onto it instead of holding
                // a second, silently diverging selection.
                if (nextId && next) setActiveProject(nextId, next.name);
                else clearActiveProject();
                if (!nextId) setShowOnlyPinned(false);
              }}
              className="h-8 rounded-lg border border-border-light bg-surface-primary px-2.5 text-xs text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <option value="">
                {t("cases.project_pin.picker_none", {
                  defaultValue: "No project selected",
                })}
              </option>
              {sortedProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setShowOnlyPinned((v) => !v)}
              disabled={!pinProjectId}
              aria-pressed={showOnlyPinned}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
                showOnlyPinned
                  ? "border-oe-blue/40 bg-oe-blue/10 text-oe-blue"
                  : "border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/30 hover:text-content-primary",
              )}
            >
              <Pin size={12} aria-hidden="true" />
              {/* The number beside this label is `pinnedIds.length` - the
                  user's own pin list for this project, held in localStorage.
                  It is not a count of cases the project has, so the old
                  "Cases for this project" read as "this project has no
                  cases" on every fresh project (issue #414). The label now
                  names what the number is. New key rather than new text
                  under the old one: 29 locales still carry the previous
                  sentence, and changing only the English would leave them
                  translating the claim we just removed. */}
              {t("cases.project_pin.show_pinned_only", {
                defaultValue: "Pinned to this project",
              })}
              {pinProjectId && (
                <span className="tabular-nums opacity-70">
                  {pinnedIds.length}
                </span>
              )}
            </button>
            {!pinProjectId && (
              <span className="text-2xs text-content-tertiary">
                {t("cases.project_pin.pick_project_first", {
                  defaultValue: "Pick a project above to pin cases to it.",
                })}
              </span>
            )}
            {/* A project is chosen but nothing is pinned to it yet. The same
                sentence the empty result already uses is shown here, before
                the click rather than after it, so a zero on the button is
                explained where it appears. */}
            {pinProjectId && pinnedIds.length === 0 && (
              <span className="text-2xs text-content-tertiary">
                {t("cases.project_pin.empty_body", {
                  defaultValue:
                    "Pin a case to this project from its card, and it will show up here.",
                })}
              </span>
            )}
          </div>

          {/* ── Secondary filter: search + discipline chips ────────────────
              One row, not two stacked blocks. Search never folds away with the
              panel above: typing a word is the fastest route to a case and it
              has to stay reachable whatever the filters are doing. */}
          <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
            <div className="relative w-full shrink-0 sm:w-64">
              <Search
                size={15}
                className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary"
                aria-hidden="true"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("cases.search_placeholder", {
                  defaultValue: "Search cases...",
                })}
                aria-label={t("cases.search_placeholder", {
                  defaultValue: "Search cases...",
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary py-2 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/50 focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              <span className="mr-0.5 inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
                <Layers
                  size={13}
                  className="text-content-tertiary"
                  aria-hidden="true"
                />
                {t("cases.filter.discipline_label", {
                  defaultValue: "Discipline",
                })}
              </span>
                <CategoryChip
                  active={activeCategories.length === 0}
                  onClick={() => setCategories([])}
                  label={t("cases.cat.all", { defaultValue: "All" })}
                  count={byCompanyRole.length}
                  icon={Layers}
                  activeClass={NEUTRAL_TINT.chip}
                />
                {availableCategories.map((c) => {
                  const count = byCompanyRole.filter(
                    (p) => p.category === c.id,
                  ).length;
                  return (
                    <CategoryChip
                      key={c.id}
                      active={activeCategories.includes(c.id)}
                      onClick={() => toggleCategory(c.id)}
                      label={t(c.labelKey, { defaultValue: c.labelDefault })}
                      count={count}
                      icon={c.icon}
                      activeClass={c.tint.chip}
                    />
                  );
                })}
            </div>
          </div>
        </>
      )}

      {/* ── Personalized summary strip: what the list is tuned to now ─────
          Every pick gets its own removable chip. A sentence would have to name
          one selection and hide the rest, and this strip is the only place
          that answers "what is filtering my list right now" - so it lists all
          of them, and each chip is the control that takes itself off. */}
      {activeFilterChips.length > 0 && (
        <div
          className={clsx(
            "flex flex-wrap items-center gap-3 rounded-xl border p-3",
            roles[0]
              ? tintForRole(roles[0]).chip
              : companyTypes[0]
                ? tintForCompany(companyTypes[0]).chip
                : NEUTRAL_TINT.chip,
          )}
        >
          <div className="flex shrink-0 items-center gap-1">
            {roles.slice(0, 3).map((r) => (
              <RoleArt
                key={r}
                role={r}
                withKindBadge
                className="h-14 w-14"
                title={t(ROLE_BY_ID[r]?.labelKey ?? "", {
                  defaultValue: ROLE_BY_ID[r]?.labelDefault ?? "",
                })}
              />
            ))}
            {roles.length === 0 &&
              companyTypes.slice(0, 3).map((c) => (
                <CompanyArt
                  key={c}
                  id={c}
                  fallbackIcon={COMPANY_TYPE_BY_ID[c]?.icon ?? Briefcase}
                  fallbackClass={tintForCompany(c).text}
                  tileClass={tintForCompany(c).tile}
                  withKindBadge
                  className="h-14 w-14"
                  title={t(COMPANY_TYPE_BY_ID[c]?.labelKey ?? "", {
                    defaultValue: COMPANY_TYPE_BY_ID[c]?.labelDefault ?? "",
                  })}
                />
              ))}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">
              {t("cases.persona.count", {
                defaultValue: "{{count}} cases for you",
                count: visible.length,
              })}
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {activeFilterChips.map((chip) => (
                <button
                  key={`${chip.kind}:${chip.id}`}
                  type="button"
                  onClick={chip.remove}
                  aria-label={t("cases.persona.remove", {
                    defaultValue: "Remove filter {{name}}",
                    name: chip.label,
                  })}
                  className="inline-flex items-center gap-1 rounded-full border border-current bg-white/40 px-2 py-0.5 text-2xs font-medium transition-colors hover:bg-white/70 dark:bg-black/10 dark:hover:bg-black/20"
                >
                  {chip.label}
                  <X size={11} aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            onClick={clearAllFilters}
            className="shrink-0 rounded-lg border border-current px-2.5 py-1 text-2xs font-semibold transition-colors hover:bg-white/30 dark:hover:bg-black/10"
          >
            {t("cases.persona.clear", { defaultValue: "Clear" })}
          </button>
        </div>
      )}

      {/* ── Market hero: the picked market gets a surface, not a highlight ──
          NOT a featured strip beside the grid. `activeRegion` has already
          narrowed `visible`, so this band labels the list that follows and no
          case is ever rendered twice. Keep it that way: a strip alongside a
          full grid draws the same card in two places, which breaks the
          catalogue suites' `getAllByText(...)[0]` lookup and the single-pin
          assertion, and it does that silently - both suites stay green until
          the day they do not. ────────────────────────────────────────────── */}
      {activeRegion !== "all" && (
        <section className="relative overflow-hidden rounded-2xl border border-border-light bg-surface-primary p-5">
          <CountryFlagBackdrop code={activeRegion} variant="panel" />
          <div className="relative flex flex-wrap items-start gap-4">
            <CountryFlag
              code={activeRegion.toLowerCase()}
              size={72}
              className="shrink-0 shadow-md ring-1 ring-inset ring-black/10"
            />
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold tracking-tight text-content-primary">
                {regionDisplayName(activeRegion, i18n.language)}
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-content-secondary">
                {t("cases.region_hero.body", {
                  defaultValue:
                    "These cases follow this market's own standards, forms and payment rules, so the numbers and the paperwork match what a client there expects.",
                })}
              </p>
              <span className="mt-1.5 inline-block text-2xs font-medium tabular-nums text-content-tertiary">
                {t("cases.selector.count", {
                  defaultValue: "{{count}} cases",
                  count: visible.length,
                })}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setRegion("all")}
              className="shrink-0 rounded-lg border border-border-light px-2.5 py-1 text-2xs font-semibold text-content-secondary transition-colors hover:border-oe-blue/30 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              {t("cases.region_selector.all", { defaultValue: "All markets" })}
            </button>
          </div>
          {/* The pack that carries the standards the band above just promised.
              The cards below each carry a one-line version of the same offer,
              and this is the full one: what the pack sets, in which currency,
              against which reference standards. It belongs on the market band
              rather than only on the cards because the pack is a property of
              the MARKET - thirteen German cases need one German pack between
              them, not thirteen. Where the market has no pack in this build,
              the panel says so here once instead of thirteen cards each saying
              nothing: the German and Canadian packs are in the source tree and
              in no wheel, and no pack declares ES at all. "On disk" was the
              wrong test and reading it as one is how the German market came to
              show no install control anywhere. */}
          <MarketPackPanel region={activeRegion} className="relative mt-4" />
        </section>
      )}

      {/* ── Cards ───────────────────────────────────────────────────────── */}
      {allPlaybooks.length === 0 ? (
        <EmptyState
          icon={<Route size={28} />}
          title={t("cases.empty_title", { defaultValue: "No cases yet" })}
          description={t("cases.empty_body", {
            defaultValue:
              "Guided playbooks will appear here as they are added.",
          })}
        />
      ) : showOnlyPinned && visible.length === 0 ? (
        <EmptyState
          icon={<Pin size={28} />}
          title={t("cases.project_pin.empty_title", {
            defaultValue: "No cases pinned yet",
          })}
          description={t("cases.project_pin.empty_body", {
            defaultValue:
              "Pin a case to this project from its card, and it will show up here.",
          })}
        />
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<Search size={28} />}
          title={t("cases.no_matches_title", {
            defaultValue: "No matching cases",
          })}
          description={t("cases.no_matches_body", {
            defaultValue: "Try a different search or category.",
          })}
        />
      ) : (
        <>
          <div
            className={clsx(
              "grid grid-cols-2 gap-2.5 sm:grid-cols-3",
              // A market band above the grid is a promise that these cases are
              // worth a closer look, and eight columns underneath it reads as
              // the same dense list with a banner stuck on top. The largest
              // market holds 13 cases, so five across still fills the row.
              // Unfiltered, the density is exactly what it always was.
              activeRegion === "all"
                ? "md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8"
                : "md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5",
            )}
          >
            {windowed.map((pb) => {
              const stageId = stageByPlaybook.get(pb.id);
              // A shipped case is a source file with nothing an editor could
              // open; only an authored one is a row somebody may rewrite.
              const authored = caseIdFromPlaybookId(pb.id) !== null;
              return (
                <CaseCard
                  key={pb.id}
                  pb={pb}
                  authored={authored}
                  num={caseNumbers.get(pb.id)}
                  totalCases={caseNumbers.size}
                  stage={stageId ? STAGE_BY_ID[stageId] : undefined}
                  roles={rolesByPlaybook.get(pb.id) ?? []}
                  face={facesByPlaybook.get(pb.id) ?? null}
                  done={bestDoneFor(pb)}
                  pack={(pb.region && packOffers.get(pb.region)) || null}
                  canInstallPack={canInstallPack}
                  onActivatePack={setPackToInstall}
                  pinProjectId={pinProjectId}
                  pinned={pinProjectId ? pinnedIds.includes(pb.id) : false}
                  onOpen={() => navigate(`/cases/${pb.id}`)}
                  onTogglePin={() => togglePin(pinProjectId, pb.id)}
                  onEdit={
                    authored
                      ? () => navigate(`/cases/${pb.id}/edit`)
                      : undefined
                  }
                />
              );
            })}
          </div>
          {/* Reveal sentinel: as it nears the viewport the next batch mounts.
              The button is the accessible / no-observer fallback and lets a
              keyboard user load more without scrolling. */}
          {hasMore && (
            <div
              ref={sentinelRef}
              className="flex flex-col items-center gap-2 pt-1"
            >
              <button
                type="button"
                onClick={() =>
                  setCardLimit((n) =>
                    Math.min(n + CARD_BATCH_SIZE, visible.length),
                  )
                }
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-4 py-2 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue/30 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                {t("cases.show_more", { defaultValue: "Show more cases" })}
              </button>
              <span className="text-2xs tabular-nums text-content-tertiary">
                {t("cases.showing_count", {
                  defaultValue: "Showing {{shown}} of {{total}}",
                  shown: windowed.length,
                  total: visible.length,
                })}
              </span>
            </div>
          )}
        </>
      )}

      {/* The grid's one install dialog, opened by whichever card was pressed.
          Mounted outside the grid so it survives the card scrolling out from
          under it: the batches window, and a dialog owned by a card would be
          unmounted mid-install by the reveal sentinel. */}
      <PartnerPackApplyDialog
        open={packToInstall !== null}
        onClose={() => setPackToInstall(null)}
        slug={packToInstall?.slug ?? ""}
        partnerName={packToInstall?.name ?? ""}
      />
    </div>
  );
}

interface CaseCardProps {
  pb: Playbook;
  /** Whether this case was written by a user rather than shipped with the
   *  product. Only marks the card; what may be DONE with it is `onEdit`. */
  authored: boolean;
  /** 1-based lifecycle number, or undefined if this case has none. */
  num: number | undefined;
  /** Total number of numbered cases, for the "Case X of N" tooltip. */
  totalCases: number;
  /** Resolved lifecycle-stage metadata, or undefined. */
  stage: StageMeta | undefined;
  /** Professional roles that run this case (already resolved). */
  roles: ProfessionalRole[];
  /** Photograph of the person this case is written for, dealt by `dealCaseFaces`
   *  over the whole catalogue, or null for a case whose company types have no
   *  cast - those cards keep the illustration alone. Carries its own pooled
   *  fallback, so a market whose portrait has not been bought yet falls back
   *  on this card alone. */
  face: CaseFace | null;
  /** Furthest step reached across any run of this case. */
  done: number;
  /** The regional pack this case's market needs, already resolved and named,
   *  or null when the case names no market or the market has no pack on disk.
   *  Resolved by the list so the card knows whether a strip will render before
   *  it renders one - the hover panel's foot padding depends on the answer. */
  pack: CasePackOffer | null;
  /** Whether this reader may apply a pack at all (admin). */
  canInstallPack: boolean;
  /** Opens the grid's install dialog on this card's pack. */
  onActivatePack: (pack: CasePackOffer) => void;
  /** The project the pin picker is scoped to ('' = none, hides the pin). */
  pinProjectId: string;
  /** Whether this case is pinned to `pinProjectId`. */
  pinned: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  /** Opens this case in the editor. Passed only when it can be rewritten, so
   *  a shipped case never offers an edit it cannot honour. */
  onEdit?: () => void;
}

/**
 * A single case card. Owns a near-viewport check so its heavy line-art
 * illustration - and the inline-SVG role avatars - only mount once the card is
 * scrolled close to the fold; until then same-sized placeholders hold the space
 * so nothing shifts. Styling, links and keyboard behaviour match the grid
 * exactly; only the illustration is deferred.
 */
function CaseCard({
  pb,
  authored,
  num,
  totalCases,
  stage,
  roles,
  face,
  done,
  pack,
  canInstallPack,
  onActivatePack,
  pinProjectId,
  pinned,
  onOpen,
  onTogglePin,
  onEdit,
}: CaseCardProps) {
  const { t, i18n } = useTranslation();
  const { ref, near } = useNearViewport<HTMLDivElement>("400px");
  const Icon = iconFor(pb.icon);
  const tint = tintFor(pb.category);
  const total = pb.steps.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const started = done > 0;
  const complete = total > 0 && done === total;
  const StageIcon = stage?.icon;
  const shownRoles = roles.slice(0, 3);

  // The span of the case: the modules its steps walk through, in the order it
  // reaches them. Resolved exactly the way the honeycomb on the case page
  // resolves it - the key decides the word and `moduleLabel` is only its
  // English fallback. Reading the label raw is the trap `types.ts` documents
  // at length: a stale label reads correct in English and wrong in the other
  // forty-two languages, and nothing on the screen can show the difference.
  const moduleNames = modulesForPlaybook(pb).map((m) =>
    m.labelKey ? t(m.labelKey, { defaultValue: m.label }) : m.label,
  );
  const shownModules = moduleNames.slice(0, 3);
  const moreModules = moduleNames.length - shownModules.length;
  const modulesSentence = t("cases.card.modules", {
    defaultValue: "Modules: {{list}}",
    list: fmtList(moduleNames),
  });

  // Who the case is written for. Every shipped case but one names at least one
  // company type; the one that names none simply says nothing here rather than
  // drawing an empty cell.
  const companyNames = pb.companyTypes.map((id) =>
    t(COMPANY_TYPE_BY_ID[id]?.labelKey ?? "", {
      defaultValue: COMPANY_TYPE_BY_ID[id]?.labelDefault ?? id,
    }),
  );
  const shownCompanies = companyNames.slice(0, 2);
  const moreCompanies = companyNames.length - shownCompanies.length;
  const companySentence = t("cases.card.company", {
    defaultValue: "Written for: {{list}}",
    list: fmtList(companyNames),
  });

  // The same company types as a comb, for the picture rather than the sentence.
  // Every cell keeps the colour and the glyph that kind of company wears in the
  // filter rail and on the case page, so the reader who has met them once reads
  // this band without being told again. No case names more than four, measured
  // over all shipped playbooks, so the band never has to truncate and there is
  // no overflow rule to get wrong.
  const companyCells = pb.companyTypes.map((id, i) => ({
    id,
    label: companyNames[i] ?? id,
    icon: COMPANY_TYPE_BY_ID[id]?.icon ?? Briefcase,
    tint: tintForCompany(id),
  }));

  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={clsx(
        "group relative isolate flex h-full cursor-pointer flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary text-left",
        "shadow-xs transition duration-200 hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md",
        "motion-reduce:transition-none motion-reduce:hover:translate-y-0",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
      )}
    >
      {/* Very faint full-card wash in the discipline hue, layered under the
          content (via -z-10 inside the card's isolate) so cards are easy to tell
          apart without the colour ever fighting the text. */}
      <span
        aria-hidden="true"
        className={clsx(
          "pointer-events-none absolute inset-0 -z-10",
          tint.softBg,
        )}
      />
      {/* Soft left rail tints the card by discipline (positioned so it never
          fights the card border). */}
      <span
        aria-hidden="true"
        className={clsx(
          "absolute inset-y-0 left-0 border-l-[3px]",
          tint.accent,
        )}
      />
      {/* Illustration banner: the picture carries the card, on an always-light
          tile so the slate linework reads in both themes. The tile keeps its
          16/9 size whether the art or a placeholder sits inside, so gating the
          art on `near` never shifts the layout.

          A case that has a face keeps the whole diagram and wears the person
          as a hex over one corner of it. Banding the two side by side cost the
          diagram nearly 40% of its width, and the diagram is what says what the
          case does; the hex is the same cell the marketing site uses on the
          cards these cases came from, so the person still arrives first without
          taking the meaning with them. The photograph is decorative (alt="");
          the role it stands for is named in the card text below, so nothing is
          said only in a picture. Both layers are absolutely positioned inside
          the tile the layout has already reserved, so neither can shift
          anything, and both mount on `near` so a card off screen costs
          nothing. */}
      <div className="relative aspect-[16/9] w-full shrink-0 overflow-hidden border-b border-border-light bg-gradient-to-b from-white to-slate-50 ring-1 ring-inset ring-slate-900/[0.04]">
        {!near ? (
          <div className="h-full w-full" aria-hidden="true" />
        ) : (
          <>
            {/* Nudged off the inline-start edge so the specialist's hexagon below
                sits beside the drawing rather than on top of it. */}
            <CaseArt
              id={pb.id}
              category={pb.category}
              fallbackIcon={Icon}
              fallbackClass={tint.text}
              className={face ? 'ps-[13%]' : undefined}
            />
            {face && (
              <div className="pointer-events-none absolute bottom-2 start-2 w-[34%] max-w-[6.5rem]">
                {/* The rim is the wrapper's own background showing through a
                    3px inset, because a border cannot survive a clip-path. */}
                <div
                  className="bg-white/90 p-[3px] shadow-md shadow-slate-900/15"
                  style={{ aspectRatio: HEX_PORTRAIT_ASPECT, clipPath: HEX_PORTRAIT_CLIP }}
                >
                  <CaseFacePhoto
                    face={face}
                    width={340}
                    height={480}
                    className="h-full w-full object-cover object-[50%_18%]"
                    style={{ clipPath: HEX_PORTRAIT_CLIP }}
                  />
                </div>
              </div>
            )}
            {/* The kinds of company this case is written for, drawn at the
                opposite corner from the person so the two never collide: the
                specialist reads from the start edge, the companies from the
                end edge, and the diagram keeps the middle.

                Decorative, and inert on purpose. The names are already stated
                in words in the panel below, and `aria-hidden` here keeps the
                card from saying them twice; `pointer-events-none` matches the
                portrait and the footer overlay, because every pixel of this
                card is one click target and a hexagon that swallowed a click
                would be a defect, not a feature. Glyph only: at this size a
                name would be set smaller than anything else on the card and
                would read as noise. */}
            {companyCells.length > 0 && (
              <div
                aria-hidden="true"
                className="pointer-events-none absolute bottom-1 end-2 drop-shadow-sm"
              >
                <Hive
                  cells={companyCells}
                  label={companySentence}
                  cellWidth={34}
                  rows={1}
                  iconOnly
                />
              </div>
            )}
          </>
        )}
        {(num != null || authored || pb.region) && (
          <div className="absolute left-3 top-3 flex items-center gap-1.5">
            {num != null && (
              <span
                className="inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md bg-slate-900/85 px-1.5 text-2xs font-bold tabular-nums text-white shadow-sm ring-1 ring-inset ring-white/15"
                title={t("cases.card.number", {
                  defaultValue: "Case {{num}} of {{total}}",
                  num,
                  total: totalCases,
                })}
              >
                {num}
              </span>
            )}
            {/* Says at a glance that this case was written in the user's own
                organisation rather than shipped with the product. Not "yours":
                the hub also lists cases a colleague shared, and those are as
                little the reader's own work as the shipped ones. */}
            {authored && (
              <Badge variant="blue" size="sm">
                {t("cases.card.custom_badge", { defaultValue: "Custom" })}
              </Badge>
            )}
            {/* Market flag: says at rest that this case is written for one
                market's standards. The full market name is the tooltip and
                the accessible name; the picture alone never carries it. */}
            {pb.region && (
              <span
                className="inline-flex h-6 items-center gap-1 rounded-md bg-white/90 px-1.5 text-2xs font-semibold text-slate-900 shadow-sm ring-1 ring-inset ring-slate-900/10"
                title={regionDisplayName(pb.region, i18n.language)}
                aria-label={regionDisplayName(pb.region, i18n.language)}
              >
                <CountryFlag
                  code={pb.region.toLowerCase()}
                  size={18}
                  className="ring-1 ring-inset ring-black/10"
                />
                {pb.region}
              </span>
            )}
          </div>
        )}
        <div className="absolute right-3 top-3 flex items-center gap-1.5">
          {complete ? (
            <Badge variant="success" size="sm">
              {t("cases.card.done_badge", { defaultValue: "Done" })}
            </Badge>
          ) : started ? (
            <span
              className="h-2.5 w-2.5 rounded-full bg-oe-blue shadow-sm ring-2 ring-white"
              title={t("cases.card.in_progress", {
                defaultValue: "In progress",
              })}
              aria-label={t("cases.card.in_progress", {
                defaultValue: "In progress",
              })}
            />
          ) : null}
          {/* Rewrite this case. Sits beside the pin and borrows its treatment,
              including the z-20 that keeps it above the hover panel: a user
              reads that panel to decide the case needs changing, so the
              control they then reach for cannot be the one it just covered. */}
          {onEdit && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              title={t("cases.card.edit", { defaultValue: "Edit this case" })}
              aria-label={t("cases.card.edit", {
                defaultValue: "Edit this case",
              })}
              className={clsx(
                "relative z-20 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
                "border-border-light bg-surface-primary/90 text-content-tertiary",
                "group-hover:border-white/35 group-hover:bg-white/15 group-hover:text-white",
                "group-focus-visible:border-white/35 group-focus-visible:bg-white/15 group-focus-visible:text-white",
                "hover:border-white/60 hover:bg-white/30 hover:text-white",
              )}
            >
              <Pencil size={13} />
            </button>
          )}
          {/* Pin this case to the active project. It has to stay legible while
              the card is hovered: the hover panel below covers the whole card
              at z-10, and a user reads that panel to decide whether this case
              belongs on their job, so the control they then reach for cannot
              be the one the panel just swallowed. It sat under the panel and
              stayed clickable (the panel takes no pointer events), which is
              worse than missing - an invisible target you have to know is
              there. z-20 keeps it on top, and the unpinned chip borrows the
              panel's light-on-dark treatment for as long as the panel is up.
              Never opacity-gated on hover, so touch and keyboard reach it the
              same way the mouse does. */}
          {pinProjectId && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onTogglePin();
              }}
              aria-pressed={pinned}
              title={
                pinned
                  ? t("cases.project_pin.unpin", {
                      defaultValue: "Unpin from project",
                    })
                  : t("cases.project_pin.pin", {
                      defaultValue: "Pin to project",
                    })
              }
              aria-label={
                pinned
                  ? t("cases.project_pin.unpin", {
                      defaultValue: "Unpin from project",
                    })
                  : t("cases.project_pin.pin", {
                      defaultValue: "Pin to project",
                    })
              }
              className={clsx(
                "relative z-20 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
                pinned
                  ? // Solid, not a 10% tint: the same chip has to read on the
                    // light banner at rest and on the near-black hover panel,
                    // and a tint that faint survives neither.
                    "border-oe-blue bg-oe-blue text-white shadow-sm"
                  : clsx(
                      "border-border-light bg-surface-primary/90 text-content-tertiary",
                      // Same hover/focus pair that raises the panel, so the
                      // chip and the panel can never disagree about which one
                      // is showing.
                      "group-hover:border-white/35 group-hover:bg-white/15 group-hover:text-white",
                      "group-focus-visible:border-white/35 group-focus-visible:bg-white/15 group-focus-visible:text-white",
                      // Pointing at the pin always means pointing at the card,
                      // so this only ever brightens the treatment above.
                      "hover:border-white/60 hover:bg-white/30 hover:text-white",
                    ),
              )}
            >
              {pinned ? <Pin size={13} /> : <PinOff size={13} />}
            </button>
          )}
        </div>
      </div>

      {/* Resting content: illustration + a tight title keep the grid dense; the
          fuller story surfaces in the hover overlay below. */}
      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <h3 className="line-clamp-2 text-xs font-semibold leading-snug text-content-primary">
          {t(pb.titleKey, { defaultValue: pb.titleDefault })}
        </h3>

        {/* Where the case goes. The other resting facts say how long it is;
            this one says which parts of the platform it crosses, which is the
            question the catalogue could not answer without opening a case. It
            earns its line at rest rather than in the hover panel because the
            panel is exactly as tall as the card and already full, while a card
            that grows a line simply grows - and the same line lifts the panel
            by its own height. */}
        {shownModules.length > 0 && (
          <p
            className="flex items-center gap-1 text-2xs text-content-tertiary"
            title={modulesSentence}
          >
            {/* Clipped for the grid, whole for a reader: the visible run is
                cut to keep the cards dense, so the full list rides along in
                the accessible tree instead of being cut with it. */}
            <span className="sr-only">{modulesSentence}</span>
            <Hexagon size={11} aria-hidden="true" className="shrink-0" />
            <span aria-hidden="true" className="min-w-0 truncate">
              {shownModules.join(" · ")}
            </span>
            {moreModules > 0 && (
              <span aria-hidden="true" className="shrink-0 font-medium">
                +{moreModules}
              </span>
            )}
          </p>
        )}

        {/* Progress bar (only once started) */}
        {started && (
          <div className="mt-3">
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={done}
              aria-valuetext={t("cases.steps_progress", {
                defaultValue: "{{done}} of {{total}} steps",
                done,
                total,
              })}
              aria-label={t("cases.progress_label", {
                defaultValue: "Case progress",
              })}
            >
              <div
                className="h-full rounded-full bg-oe-blue transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Resting meta: steps and time (or live progress) on one tight line. */}
        <div className="mt-auto flex items-center justify-between gap-1 text-2xs text-content-tertiary">
          <span className="inline-flex items-center gap-1">
            <ListChecks size={11} aria-hidden="true" />
            {t("cases.card.steps", {
              defaultValue: "{{count}} steps",
              count: total,
            })}
          </span>
          {started ? (
            <span className="font-semibold tabular-nums text-oe-blue">{pct}%</span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <Clock size={11} aria-hidden="true" />
              {t("cases.card.minutes_short", {
                defaultValue: "{{count}} min",
                count: pb.estMinutes,
              })}
            </span>
          )}
        </div>
      </div>

      {/* What this case's market needs installed, and the one press that starts
          it. Only for a case whose market has a pack on disk; the rest of the
          catalogue keeps exactly the card it had. Above the hover panel, like
          the pin and the edit control, because a reader decides they want the
          market's standards by reading that panel. */}
      <CasePackStrip
        pack={pack}
        canInstall={canInstallPack}
        onActivate={onActivatePack}
      />

      {/* Hover / focus reveal: the fuller story surfaces over the whole card so
          the dense resting grid still explains itself at a glance. The panel is
          pointer-events-none so the card stays a single click target. */}
      <div
        className={clsx(
          "pointer-events-none absolute inset-0 z-10 flex flex-col gap-2 bg-gradient-to-t from-slate-950/95 via-slate-950/90 to-slate-950/80 p-3 opacity-0 backdrop-blur-[1px] transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none",
          // The pack strip lies over the panel's foot. Without this the line
          // the panel ends on - the one that says "Open" - is the line the
          // strip covers.
          pack && "pb-10",
        )}
      >
        <h4 className="line-clamp-2 text-xs font-semibold leading-snug text-white">
          {t(pb.titleKey, { defaultValue: pb.titleDefault })}
        </h4>
        <p className="line-clamp-4 text-2xs leading-relaxed text-white/80">
          {t(pb.descKey, { defaultValue: pb.descDefault })}
        </p>
        <div className="mt-auto flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {stage && StageIcon && (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-medium text-white ring-1 ring-inset ring-white/20">
                <StageIcon size={10} strokeWidth={2} aria-hidden="true" />
                {t(stage.shortKey, { defaultValue: stage.shortDefault })}
              </span>
            )}
            <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-medium text-white ring-1 ring-inset ring-white/20">
              <Clock size={10} aria-hidden="true" />
              {t("cases.card.minutes_short", {
                defaultValue: "{{count}} min",
                count: pb.estMinutes,
              })}
            </span>
            {pb.region && (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-medium text-white ring-1 ring-inset ring-white/20">
                <CountryFlag
                  code={pb.region.toLowerCase()}
                  size={15}
                />
                {regionDisplayName(pb.region, i18n.language)}
              </span>
            )}
          </div>
          {/* Who this case is for: the kind of firm, named, beside the people
              inside it who run it. One row rather than two, because the panel
              is exactly as tall as the card and a row added below would be
              clipped by the card's own overflow rather than shown. The company
              names are DISPLAY - the public pages make theirs a link into the
              filtered list, and a link in here would take the click the whole
              card is meant to catch. */}
          {(roles.length > 0 || shownCompanies.length > 0) && (
            <div className="flex items-center gap-2">
              {roles.length > 0 && (
                <div
                  className="flex shrink-0 items-center -space-x-1.5"
                  aria-label={fmtList(
                    roles.map((id) =>
                      t(ROLE_BY_ID[id]?.labelKey ?? "", {
                        defaultValue: ROLE_BY_ID[id]?.labelDefault ?? id,
                      }),
                    ),
                  )}
                >
                  {shownRoles.map((id) =>
                    near ? (
                      <RoleAvatar
                        key={id}
                        role={id}
                        className="h-5 w-5 rounded-full ring-2 ring-slate-950"
                        title={t(ROLE_BY_ID[id]?.labelKey ?? "", {
                          defaultValue: ROLE_BY_ID[id]?.labelDefault ?? id,
                        })}
                      />
                    ) : null,
                  )}
                  {roles.length > 3 && (
                    <span className="ml-2 text-[10px] font-medium text-white/70">
                      +{roles.length - 3}
                    </span>
                  )}
                </div>
              )}
              {shownCompanies.length > 0 && (
                <p className="flex min-w-0 items-center gap-1 text-[10px] font-medium text-white/70">
                  {/* Same split as the module line: the run is clipped to the
                      width the panel has, the whole list is read out.

                      TEXT, NOT CONTROLS - and deliberately not consistent with
                      the case page, where the same company names ARE buttons
                      that narrow the catalogue. The asymmetry is the point.
                      This whole card is one click target: the overlay is
                      pointer-events-none so that a click anywhere on it opens
                      the case, and a button or link here would swallow that
                      click for the reader who aimed at the card and hit a word.
                      The case page header has no competing target, so it can
                      afford the control. Making the two surfaces match would
                      break the card, not tidy it. casesCardFacts.test.tsx
                      asserts zero <a> and zero <button> inside the card. */}
                  <span className="sr-only">{companySentence}</span>
                  <span aria-hidden="true" className="min-w-0 truncate">
                    {shownCompanies.join(" · ")}
                  </span>
                  {moreCompanies > 0 && (
                    <span aria-hidden="true" className="shrink-0">
                      +{moreCompanies}
                    </span>
                  )}
                </p>
              )}
            </div>
          )}
          <span className="inline-flex items-center gap-1 text-2xs font-semibold text-white">
            {started
              ? t("cases.card.continue", { defaultValue: "Continue" })
              : t("cases.card.open", { defaultValue: "Open" })}
            <ArrowRight size={12} aria-hidden="true" />
          </span>
        </div>
      </div>
    </div>
  );
}

/** A single discipline filter chip with an icon, label and case count. */
function CategoryChip({
  active,
  onClick,
  label,
  count,
  icon: Icon,
  activeClass,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  icon: ComponentType<LucideProps>;
  /** Soft tint classes applied when the chip is the active filter. */
  activeClass: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? activeClass
          : "border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/30 hover:text-content-primary",
      )}
    >
      <Icon size={13} strokeWidth={2} aria-hidden="true" />
      {label}
      <span
        className={clsx(
          "ml-0.5 tabular-nums",
          active ? "opacity-70" : "text-content-tertiary",
        )}
      >
        {count}
      </span>
    </button>
  );
}
