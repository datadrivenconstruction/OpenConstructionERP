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
  ListChecks,
  Layers,
  Search,
  Pin,
  PinOff,
  Briefcase,
  FolderKanban,
  UserRound,
  Flag,
  Info,
  type LucideProps,
} from "lucide-react";
import { Badge, EmptyState } from "@/shared/ui";
import { useNearViewport } from "@/shared/hooks/useNearViewport";
import { projectsApi } from "@/features/projects/api";
import { PLAYBOOKS, getPlaybook } from "./playbooks";
import { PlaybookRunner } from "./PlaybookRunner";
import { useCasesStore } from "./useCasesStore";
import { completedCount } from "./progress";
import { CATEGORY_META, tintFor, NEUTRAL_TINT } from "./categories";
import {
  COMPANY_TYPE_META,
  COMPANY_TYPE_BY_ID,
  tintForCompany,
} from "./companyTypes";
import { ROLE_META, ROLE_BY_ID, rolesForPlaybook, tintForRole } from "./roles";
import { RoleAvatar } from "./RoleAvatar";
import { RoleArt } from "./RoleArt";
import { CaseArt } from "./CaseArt";
import { CompanyArt } from "./CompanyArt";
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
  CaseCategory,
  CompanyType,
  ProfessionalRole,
  LifecycleStage,
} from "./types";

export function CasesPage() {
  const { playbookId } = useParams<{ playbookId?: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();

  // Detail mode: a specific case is open in the runner.
  if (playbookId) {
    const playbook = getPlaybook(playbookId);
    if (!playbook) {
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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const runs = useCasesStore((s) => s.runs);
  const companyType = useCasesStore((s) => s.companyType);
  const setCompanyType = useCasesStore((s) => s.setCompanyType);
  const role = useCasesStore((s) => s.role);
  const setRole = useCasesStore((s) => s.setRole);
  const pinProjectId = useCasesStore((s) => s.pinProjectId);
  const setPinProjectId = useCasesStore((s) => s.setPinProjectId);
  const pins = useCasesStore((s) => s.pins);
  const togglePin = useCasesStore((s) => s.togglePin);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<CaseCategory | "all">(
    "all",
  );
  const [activeStage, setActiveStage] = useState<LifecycleStage | "all">("all");
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
    for (const pb of PLAYBOOKS) m.set(pb.id, rolesForPlaybook(pb));
    return m;
  }, []);
  const caseHasRole = useMemo(
    () => (pb: Playbook, r: ProfessionalRole) =>
      rolesByPlaybook.get(pb.id)?.includes(r) ?? false,
    [rolesByPlaybook],
  );

  // Lifecycle stage + a stable case number (1..N, ordered start of project to
  // end) for every case, so the timeline and the numbered cards read in order.
  const stageByPlaybook = useMemo(() => {
    const m = new Map<string, LifecycleStage>();
    for (const pb of PLAYBOOKS) m.set(pb.id, stageForPlaybook(pb));
    return m;
  }, []);
  const caseNumbers = useMemo(() => buildCaseNumbers(PLAYBOOKS), []);
  const inStage = useMemo(
    () => (pb: Playbook) =>
      activeStage === "all" || stageByPlaybook.get(pb.id) === activeStage,
    [activeStage, stageByPlaybook],
  );

  // Three filters narrow the same list: company type, professional role and
  // discipline. Only surface a selector option that actually has a matching
  // case, and scope each option's availability + count by the OTHER two active
  // filters, so a count always describes what clicking it would really show.
  const byCategoryRole = useMemo(
    () =>
      PLAYBOOKS.filter(
        (p) =>
          (activeCategory === "all" || p.category === activeCategory) &&
          (!role || caseHasRole(p, role)) &&
          inStage(p),
      ),
    [activeCategory, role, caseHasRole, inStage],
  );
  const byCompanyRole = useMemo(
    () =>
      PLAYBOOKS.filter(
        (p) =>
          (!companyType || p.companyTypes.includes(companyType)) &&
          (!role || caseHasRole(p, role)) &&
          inStage(p),
      ),
    [companyType, role, caseHasRole, inStage],
  );
  const byCompanyCategory = useMemo(
    () =>
      PLAYBOOKS.filter(
        (p) =>
          (!companyType || p.companyTypes.includes(companyType)) &&
          (activeCategory === "all" || p.category === activeCategory) &&
          inStage(p),
      ),
    [companyType, activeCategory, inStage],
  );
  // Stage availability + counts are scoped by the who/discipline filters but
  // NOT by the active stage itself (so every reachable stage stays clickable).
  const byCompanyRoleCategory = useMemo(
    () =>
      PLAYBOOKS.filter(
        (p) =>
          (!companyType || p.companyTypes.includes(companyType)) &&
          (!role || caseHasRole(p, role)) &&
          (activeCategory === "all" || p.category === activeCategory),
      ),
    [companyType, role, caseHasRole, activeCategory],
  );
  const availableCompanyTypes = useMemo(() => {
    const present = new Set(byCategoryRole.flatMap((p) => p.companyTypes));
    return COMPANY_TYPE_META.filter((c) => present.has(c.id));
  }, [byCategoryRole]);
  const availableCategories = useMemo(() => {
    const present = new Set(byCompanyRole.map((p) => p.category));
    return CATEGORY_META.filter((c) => present.has(c.id));
  }, [byCompanyRole]);
  const availableRoles = useMemo(() => {
    const present = new Set(
      byCompanyCategory.flatMap((p) => rolesByPlaybook.get(p.id) ?? []),
    );
    return ROLE_META.filter((r) => present.has(r.id));
  }, [byCompanyCategory, rolesByPlaybook]);
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
    return PLAYBOOKS.filter((pb) => {
      if (companyType && !pb.companyTypes.includes(companyType)) return false;
      if (role && !caseHasRole(pb, role)) return false;
      if (activeStage !== "all" && stageByPlaybook.get(pb.id) !== activeStage)
        return false;
      if (activeCategory !== "all" && pb.category !== activeCategory)
        return false;
      if (showOnlyPinned && !pinnedIds.includes(pb.id)) return false;
      if (!q) return true;
      const haystack =
        `${t(pb.titleKey, { defaultValue: pb.titleDefault })} ${t(pb.descKey, {
          defaultValue: pb.descDefault,
        })}`.toLowerCase();
      return haystack.includes(q);
    }).sort(
      (a, b) => (caseNumbers.get(a.id) ?? 0) - (caseNumbers.get(b.id) ?? 0),
    );
  }, [
    query,
    activeCategory,
    activeStage,
    stageByPlaybook,
    companyType,
    role,
    caseHasRole,
    showOnlyPinned,
    pinnedIds,
    caseNumbers,
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
    setCompanyType(companyType === id ? null : id);
  };
  const handlePickRole = (id: ProfessionalRole) => {
    setRole(role === id ? null : id);
  };
  const handlePickStage = (id: LifecycleStage) => {
    setActiveStage(activeStage === id ? "all" : id);
  };

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
              {PLAYBOOKS.length > 0 && (
                <span className="inline-flex items-center rounded-full bg-oe-blue/10 px-2 py-0.5 text-2xs font-semibold text-oe-blue ring-1 ring-inset ring-oe-blue/20">
                  {t("cases.header.count", {
                    defaultValue: "{{count}} guided cases",
                    count: PLAYBOOKS.length,
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
        </div>
      </div>

      {PLAYBOOKS.length > 0 && (
        <>
          {/* ── How-to helper: how to use the hub in one line ─────────────── */}
          <div className="flex items-start gap-2 rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-3">
            <Info
              size={15}
              className="mt-px shrink-0 text-content-tertiary"
              aria-hidden="true"
            />
            <p className="text-2xs leading-relaxed text-content-tertiary">
              {t("cases.hub_howto", {
                defaultValue:
                  "New here? Pick where you are in the project, the kind of company you work for, and your role, and the list narrows to the cases that matter to you.",
              })}
            </p>
          </div>

          {/* ── Project lifecycle: cases from start to finish, as stage cards ─ */}
          <div>
            <div className="mb-2.5 flex items-center gap-2">
              <Flag
                size={14}
                className="text-content-tertiary"
                aria-hidden="true"
              />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t("cases.stage_selector.heading", {
                  defaultValue: "Project lifecycle",
                })}
              </h2>
              <span className="text-2xs text-content-tertiary">
                {t("cases.stage_selector.subtitle", {
                  defaultValue:
                    "Cases laid out in the order a project runs, start to finish.",
                })}
              </span>
            </div>
            {/* Eight stage cards in lifecycle order. Compact horizontal cards in
                the "My company" card language, but wrapped in a lifted panel and
                each led by a numbered tile, so this row reads as the higher-level
                project map (the ordered journey, start to finish) that sits above
                the who/role filters below. */}
            <div className="rounded-2xl border border-border-light bg-surface-secondary/40 p-2.5 dark:bg-white/[0.03]">
              <div
                className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8"
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
                        "group flex items-center gap-2.5 rounded-xl border p-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
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
                          "relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset",
                          s.tint.tile,
                        )}
                      >
                        <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
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
                className="mt-2 text-2xs font-medium text-oe-blue hover:underline"
              >
                {t("cases.stage_selector.all", { defaultValue: "All stages" })}
              </button>
            )}
          </div>

          {/* ── Primary filter: "I work as..." company-type selector ─────── */}
          <div>
            <div className="mb-2.5 flex items-center gap-2">
              <Briefcase
                size={14}
                className="text-content-tertiary"
                aria-hidden="true"
              />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t("cases.company_selector.heading", {
                  defaultValue: "My company",
                })}
              </h2>
              <span className="text-2xs text-content-tertiary">
                {t("cases.company_selector.subtitle", {
                  defaultValue: "Pick the kind of firm you work for.",
                })}
              </span>
            </div>
            <div
              className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8"
              role="group"
              aria-label={t("cases.company_selector.heading", {
                defaultValue: "My company",
              })}
            >
              {COMPANY_TYPE_META.map((c) => {
                const Icon = c.icon;
                const active = companyType === c.id;
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
                      "flex items-center gap-2.5 rounded-xl border p-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
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
                      className="h-14 w-14"
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
            {companyType && (
              <button
                type="button"
                onClick={() => setCompanyType(null)}
                className="mt-2 text-2xs font-medium text-oe-blue hover:underline"
              >
                {t("cases.company_selector.all", {
                  defaultValue: "All company types",
                })}
              </button>
            )}
          </div>

          {/* ── Secondary persona filter: "Your role" avatar selector ────── */}
          <div>
            <div className="mb-2.5 flex items-center gap-2">
              <UserRound
                size={14}
                className="text-content-tertiary"
                aria-hidden="true"
              />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t("cases.role_selector.heading", {
                  defaultValue: "Your role",
                })}
              </h2>
              <span className="text-2xs text-content-tertiary">
                {t("cases.role_selector.subtitle", {
                  defaultValue:
                    "Pick what you do day to day for a tighter list.",
                })}
              </span>
            </div>
            <div
              className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6"
              role="group"
              aria-label={t("cases.role_selector.heading", {
                defaultValue: "Your role",
              })}
            >
              {ROLE_META.map((r) => {
                const active = role === r.id;
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
                      "flex items-center gap-2.5 rounded-xl border p-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none",
                      active
                        ? clsx(r.tint.chip, "shadow-sm")
                        : "border-border-light bg-surface-primary text-content-primary hover:border-oe-blue/30",
                      disabled && "cursor-not-allowed opacity-40",
                    )}
                  >
                    <RoleArt
                      role={r.id}
                      withKindBadge
                      className="h-14 w-14 shrink-0"
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
            {role && (
              <button
                type="button"
                onClick={() => setRole(null)}
                className="mt-2 text-2xs font-medium text-oe-blue hover:underline"
              >
                {t("cases.role_selector.all", { defaultValue: "All roles" })}
              </button>
            )}
          </div>

          {/* ── Project pin bar ───────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-border-light bg-surface-secondary/40 p-3">
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
                setPinProjectId(e.target.value);
                if (!e.target.value) setShowOnlyPinned(false);
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
              {t("cases.project_pin.show_pinned", {
                defaultValue: "Cases for this project",
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
          </div>

          {/* ── Secondary filter: search + discipline chips ──────────────── */}
          <div className="space-y-3">
            <div className="relative max-w-md">
              <Search
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
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
                className="w-full rounded-lg border border-border-light bg-surface-primary py-2 pl-9 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/50 focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              />
            </div>
            <div>
              <div className="mb-2.5 flex items-center gap-2">
                <Layers
                  size={14}
                  className="text-content-tertiary"
                  aria-hidden="true"
                />
                <h2 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                  {t("cases.filter.discipline_label", {
                    defaultValue: "Discipline",
                  })}
                </h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <CategoryChip
                  active={activeCategory === "all"}
                  onClick={() => setActiveCategory("all")}
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
                      active={activeCategory === c.id}
                      onClick={() => setActiveCategory(c.id)}
                      label={t(c.labelKey, { defaultValue: c.labelDefault })}
                      count={count}
                      icon={c.icon}
                      activeClass={c.tint.chip}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Personalized summary strip: who the list is tuned to now ────── */}
      {(role || companyType) && (
        <div
          className={clsx(
            "flex flex-wrap items-center gap-3 rounded-xl border p-3",
            role
              ? tintForRole(role).chip
              : tintForCompany(companyType ?? undefined).chip,
          )}
        >
          {role ? (
            <RoleArt
              role={role}
              withKindBadge
              className="h-14 w-14"
              title={t(ROLE_BY_ID[role]?.labelKey ?? "", {
                defaultValue: ROLE_BY_ID[role]?.labelDefault ?? "",
              })}
            />
          ) : (
            companyType && (
              <CompanyArt
                id={companyType}
                fallbackIcon={
                  COMPANY_TYPE_BY_ID[companyType]?.icon ?? Briefcase
                }
                fallbackClass={tintForCompany(companyType).text}
                tileClass={tintForCompany(companyType).tile}
                withKindBadge
                className="h-14 w-14"
                title={t(COMPANY_TYPE_BY_ID[companyType]?.labelKey ?? "", {
                  defaultValue:
                    COMPANY_TYPE_BY_ID[companyType]?.labelDefault ?? "",
                })}
              />
            )
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">
              {t("cases.persona.count", {
                defaultValue: "{{count}} cases for you",
                count: visible.length,
              })}
            </p>
            <p className="text-xs opacity-80">
              {role && companyType
                ? t("cases.persona.role_and_company", {
                    defaultValue: "{{role}} at a {{company}}",
                    role: t(ROLE_BY_ID[role]?.labelKey ?? "", {
                      defaultValue: ROLE_BY_ID[role]?.labelDefault ?? "",
                    }),
                    company: t(
                      COMPANY_TYPE_BY_ID[companyType]?.labelKey ?? "",
                      {
                        defaultValue:
                          COMPANY_TYPE_BY_ID[companyType]?.labelDefault ?? "",
                      },
                    ),
                  })
                : role
                  ? t(ROLE_BY_ID[role]?.labelKey ?? "", {
                      defaultValue: ROLE_BY_ID[role]?.labelDefault ?? "",
                    })
                  : t(COMPANY_TYPE_BY_ID[companyType!]?.labelKey ?? "", {
                      defaultValue:
                        COMPANY_TYPE_BY_ID[companyType!]?.labelDefault ?? "",
                    })}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setRole(null);
              setCompanyType(null);
            }}
            className="shrink-0 rounded-lg border border-current/30 px-2.5 py-1 text-2xs font-semibold transition-colors hover:bg-white/30 dark:hover:bg-black/10"
          >
            {t("cases.persona.clear", { defaultValue: "Clear" })}
          </button>
        </div>
      )}

      {/* ── Cards ───────────────────────────────────────────────────────── */}
      {PLAYBOOKS.length === 0 ? (
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
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
            {windowed.map((pb) => {
              const stageId = stageByPlaybook.get(pb.id);
              return (
                <CaseCard
                  key={pb.id}
                  pb={pb}
                  num={caseNumbers.get(pb.id)}
                  totalCases={caseNumbers.size}
                  stage={stageId ? STAGE_BY_ID[stageId] : undefined}
                  roles={rolesByPlaybook.get(pb.id) ?? []}
                  done={bestDoneFor(pb)}
                  pinProjectId={pinProjectId}
                  pinned={pinProjectId ? pinnedIds.includes(pb.id) : false}
                  onOpen={() => navigate(`/cases/${pb.id}`)}
                  onTogglePin={() => togglePin(pinProjectId, pb.id)}
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
    </div>
  );
}

interface CaseCardProps {
  pb: Playbook;
  /** 1-based lifecycle number, or undefined if this case has none. */
  num: number | undefined;
  /** Total number of numbered cases, for the "Case X of N" tooltip. */
  totalCases: number;
  /** Resolved lifecycle-stage metadata, or undefined. */
  stage: StageMeta | undefined;
  /** Professional roles that run this case (already resolved). */
  roles: ProfessionalRole[];
  /** Furthest step reached across any run of this case. */
  done: number;
  /** The project the pin picker is scoped to ('' = none, hides the pin). */
  pinProjectId: string;
  /** Whether this case is pinned to `pinProjectId`. */
  pinned: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
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
  num,
  totalCases,
  stage,
  roles,
  done,
  pinProjectId,
  pinned,
  onOpen,
  onTogglePin,
}: CaseCardProps) {
  const { t } = useTranslation();
  const { ref, near } = useNearViewport<HTMLDivElement>("400px");
  const Icon = iconFor(pb.icon);
  const tint = tintFor(pb.category);
  const total = pb.steps.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const started = done > 0;
  const complete = total > 0 && done === total;
  const StageIcon = stage?.icon;
  const shownRoles = roles.slice(0, 3);

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
      {/* Line-art illustration banner: the picture carries the card, on an
          always-light tile so the slate linework reads in both themes. The tile
          keeps its 16/9 size whether the art or a placeholder sits inside, so
          gating the art on `near` never shifts the layout. */}
      <div className="relative aspect-[16/9] w-full shrink-0 overflow-hidden border-b border-border-light bg-gradient-to-b from-white to-slate-50 ring-1 ring-inset ring-slate-900/[0.04]">
        {near ? (
          <CaseArt id={pb.id} category={pb.category} fallbackIcon={Icon} fallbackClass={tint.text} />
        ) : (
          <div className="h-full w-full" aria-hidden="true" />
        )}
        {num != null && (
          <span
            className="absolute left-3 top-3 inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md bg-slate-900/85 px-1.5 text-2xs font-bold tabular-nums text-white shadow-sm ring-1 ring-inset ring-white/15"
            title={t("cases.card.number", {
              defaultValue: "Case {{num}} of {{total}}",
              num,
              total: totalCases,
            })}
          >
            {num}
          </span>
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
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
                pinned
                  ? "border-oe-blue/40 bg-oe-blue/10 text-oe-blue"
                  : "border-border-light bg-surface-primary/90 text-content-tertiary hover:border-oe-blue/30 hover:text-content-primary",
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

      {/* Hover / focus reveal: the fuller story surfaces over the whole card so
          the dense resting grid still explains itself at a glance. The panel is
          pointer-events-none so the card stays a single click target. */}
      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col gap-2 bg-gradient-to-t from-slate-950/95 via-slate-950/90 to-slate-950/80 p-3 opacity-0 backdrop-blur-[1px] transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none">
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
          </div>
          {roles.length > 0 && (
            <div
              className="flex items-center -space-x-1.5"
              aria-label={roles
                .map((id) =>
                  t(ROLE_BY_ID[id]?.labelKey ?? "", {
                    defaultValue: ROLE_BY_ID[id]?.labelDefault ?? id,
                  }),
                )
                .join(", ")}
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
