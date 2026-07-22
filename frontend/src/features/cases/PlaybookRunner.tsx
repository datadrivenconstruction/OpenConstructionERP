// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PlaybookRunner - the case detail page that drives one case.
//
// Layout, top to bottom. First a full-width header: the tags (discipline,
// minutes, step count), the case title and purpose, then a control band with the
// progress track, one obvious primary action, and the sample-project picker and
// reset. Under it, the process as a full-width row of step cards (a picture of
// the work, the step title and the module it uses) - a map of the whole journey;
// clicking one jumps to that step below and marks it current. Below the row every
// step is laid out in full, one under the other, so the entire case reads on one
// page with nothing hidden behind a click. Each step block puts its text on the
// left (What you do / Why, then Mark done) and its data flow on the right: what
// goes IN, the module action scene you click to open it, and what comes OUT. On
// narrow screens the header controls and each step block stack their columns.
//
// Progress and the current step are owned by `useCasesStore` and persist across
// reloads: marking a step done, or clicking a process card, writes that state,
// and the cards, the highlight and the primary action all read back from it.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeft,
  ArrowRight,
  ArrowDown,
  Check,
  Clock,
  ListChecks,
  Play,
  RotateCcw,
  CheckCircle2,
  LogIn,
  LogOut,
} from "lucide-react";
import { Button, Badge } from "@/shared/ui";
import { projectsApi, type Project } from "@/features/projects/api";
import { useProjectContextStore } from "@/stores/useProjectContextStore";
import type { Playbook, PlaybookStep } from "./types";
import { tintFor, CATEGORY_BY_ID } from "./categories";
import { iconFor } from "./icons";
import { StepScene } from "./StepScene";
import { StepProcessScene, hasProcessScene } from "./processScenes";
import { useCasesStore, EMPTY_PROGRESS } from "./useCasesStore";
import {
  clampStepIndex,
  completedCount,
  isPlaybookDone,
  isStepDone,
  nextStepIndex,
  progressPct,
  resolveStepRoute,
  runKey,
  toggleStep,
} from "./progress";
import { nextCasesFor, relatedCasesFor } from "./relatedness";
import { PLAYBOOKS } from "./playbooks";

/** Returns true for seeded sample projects (they carry `metadata.demo_id`). */
function isDemoProject(p: Project): boolean {
  return Boolean((p.metadata as Record<string, unknown> | null)?.demo_id);
}

/** One side (In / Out) of a step's data flow: a titled column of chips. The In
 *  dots are quiet (raw material); the Out dots are green (the payoff), so the
 *  eye reads from what you start with to what you end up with. */
function FlowSide({
  label,
  items,
  tone,
  hint,
}: {
  label: string;
  items: string[];
  tone: "in" | "out";
  hint?: string;
}): ReactElement {
  const Icon = tone === "in" ? LogIn : LogOut;
  return (
    <div className="flex flex-col rounded-xl border border-border-light bg-surface-secondary/40 p-3">
      <p
        className={clsx(
          "flex items-center gap-2 text-2xs font-semibold uppercase tracking-wide text-content-secondary",
          hint ? "mb-1" : "mb-2",
        )}
      >
        <Icon size={14} strokeWidth={2.2} aria-hidden="true" />
        {label}
      </p>
      {hint ? (
        <p className="mb-2.5 text-2xs leading-relaxed text-content-tertiary">{hint}</p>
      ) : null}
      <ul className="space-y-1.5">
        {items.map((text, i) => (
          <li
            key={i}
            className="flex items-start gap-2 text-sm leading-snug text-content-secondary"
          >
            <span
              className={clsx(
                "mt-[6px] h-2 w-2 shrink-0 rounded-full",
                tone === "in" ? "bg-content-quaternary" : "bg-semantic-success",
              )}
              aria-hidden="true"
            />
            <span className="min-w-0">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The arrowhead chip in the middle of a connector: a small ringed badge that
 *  carries the direction glyph, so the hand-off between blocks reads as one
 *  deliberate step rather than a stray floating arrow. */
function ConnectorChip({ down = false }: { down?: boolean }): ReactElement {
  const Glyph = down ? ArrowDown : ArrowRight;
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 ring-1 ring-inset ring-oe-blue/25">
      {/* rtl:rotate-180 keeps a horizontal arrow pointing from In to Out when the
          flow mirrors under a right-to-left language. */}
      <Glyph
        size={14}
        strokeWidth={2.2}
        className={clsx("text-oe-blue", !down && "rtl:rotate-180")}
        aria-hidden="true"
      />
    </span>
  );
}

/** The thumbnail for one step in the process card row: the step's bespoke
 *  process scene when it has one, otherwise its icon scene, framed so the row
 *  reads as a strip of pictures of the actual work. */
function StepThumb({
  step,
  className = "aspect-[16/9] w-full",
}: {
  step: PlaybookStep;
  className?: string;
}): ReactElement {
  return step.scene && hasProcessScene(step.scene) ? (
    <StepProcessScene sceneId={step.scene} rounded="rounded-lg" className={className} />
  ) : (
    <StepScene icon={step.icon} rounded="rounded-lg" className={className} />
  );
}

/** One step, laid out in full: its text on the left (What you do / Why, then the
 *  Mark-done toggle) and its data flow on the right (what goes in, the module
 *  action scene you click to open it, what comes out). Every step block renders
 *  the same way, one under the other, so the whole case reads on one page. */
function StepBlock({
  id,
  index,
  total,
  title,
  moduleLabel,
  iconName,
  what,
  why,
  inputs,
  outputs,
  inputsHint,
  outputsHint,
  scene,
  done,
  isCurrent,
  onOpen,
  onToggle,
  openLabel,
}: {
  id: string;
  index: number;
  total: number;
  title: string;
  moduleLabel: string;
  iconName?: string;
  what: string;
  why: string;
  inputs: string[];
  outputs: string[];
  inputsHint?: string;
  outputsHint?: string;
  scene: ReactElement;
  done: boolean;
  isCurrent: boolean;
  onOpen: () => void;
  onToggle: () => void;
  openLabel: string;
}): ReactElement {
  const { t } = useTranslation();
  const Icon = iconFor(iconName);
  const hasFlow = inputs.length > 0 || outputs.length > 0;
  const sceneButton = (
    <button
      type="button"
      onClick={onOpen}
      title={t("cases.step.go_to", {
        defaultValue: "Go to {{module}}",
        module: moduleLabel,
      })}
      className="group mx-auto w-full max-w-[240px] rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
    >
      {scene}
      <span className="mt-2 inline-flex w-full items-center justify-center gap-1 text-xs font-semibold text-oe-blue-text transition-colors group-hover:text-oe-blue">
        <Icon size={12} strokeWidth={2} aria-hidden="true" />
        {openLabel}
        <ArrowRight
          size={12}
          strokeWidth={2.2}
          className="transition-transform group-hover:translate-x-0.5 rtl:rotate-180"
          aria-hidden="true"
        />
      </span>
    </button>
  );
  return (
    <article
      id={id}
      aria-current={isCurrent ? "step" : undefined}
      className={clsx(
        "relative scroll-mt-4 rounded-2xl border bg-surface-primary p-3.5 shadow-xs transition-colors sm:p-4",
        isCurrent
          ? "border-oe-blue/50 ring-1 ring-inset ring-oe-blue/20"
          : done
            ? "border-semantic-success/30"
            : "border-border-light",
      )}
    >
      {/* Step number / status, pinned to the top-right corner so the counter,
          title, "What you do" and "Why" below all share one clean left edge. */}
      <span
        className={clsx(
          "absolute end-3 top-3 flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold",
          done
            ? "bg-semantic-success text-white"
            : isCurrent
              ? "bg-oe-blue text-white"
              : "bg-surface-secondary text-content-secondary ring-1 ring-inset ring-border-light",
        )}
        aria-hidden="true"
      >
        {done ? <Check size={16} strokeWidth={2.5} /> : index + 1}
      </span>

      {/* Step counter + module tag: a left-aligned row, padded to clear the
          corner badge. */}
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 pe-9">
        <span className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t("cases.step_counter", {
            defaultValue: "Step {{n}} of {{total}}",
            n: index + 1,
            total,
          })}
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary">
          <Icon size={12} strokeWidth={2} aria-hidden="true" />
          {moduleLabel}
        </span>
      </div>

      {/* Title + detail on the left, the data flow on the right. `items-start`
          keeps the In / Out cards' top aligned with the step title, and every
          left-column line shares one left edge. */}
      <div className="grid gap-4 lg:grid-cols-[2fr_3fr] lg:items-start lg:gap-6">
        <div className="min-w-0 space-y-3">
          <h3 className="text-base font-semibold leading-snug text-content-primary sm:text-lg">
            {title}
          </h3>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-oe-blue-text">
              {t("cases.step.what", { defaultValue: "What you do" })}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-content-primary">
              {what}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t("cases.step.why", { defaultValue: "Why" })}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-content-secondary">
              {why}
            </p>
          </div>
          <div className="pt-0.5">
            <Button
              variant={done ? "ghost" : "secondary"}
              size="sm"
              icon={done ? <RotateCcw size={14} /> : <Check size={14} />}
              onClick={onToggle}
            >
              {done
                ? t("cases.step.mark_undone", { defaultValue: "Mark not done" })
                : t("cases.step.mark_done", { defaultValue: "Mark done" })}
            </Button>
          </div>
        </div>

        {/* Data flow: what goes in, the module you open, what comes out - three
            equal-height blocks read left to right so the hand-off is obvious.
            Stacks on narrow screens. */}
        <div className="min-w-0">
          {hasFlow ? (
            <div className="grid grid-cols-1 items-stretch gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] sm:gap-2.5">
              <FlowSide
                label={t("cases.flow.in", { defaultValue: "Goes in" })}
                items={inputs}
                tone="in"
                hint={inputsHint}
              />
              <div
                className="hidden items-center justify-center sm:flex"
                aria-hidden="true"
              >
                <ConnectorChip />
              </div>
              <div className="flex flex-col items-center justify-center rounded-xl border border-border-light bg-surface-secondary/40 p-3">
                {sceneButton}
              </div>
              <div
                className="hidden items-center justify-center sm:flex"
                aria-hidden="true"
              >
                <ConnectorChip />
              </div>
              <FlowSide
                label={t("cases.flow.out", { defaultValue: "Comes out" })}
                items={outputs}
                tone="out"
                hint={outputsHint}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-3">
              {sceneButton}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

/** A compact link to another case, used in the "Do this next" and "Related
 *  cases" grids at the foot of the page. Shows the case's icon, discipline and
 *  size so the user can judge where a link leads before taking it. The primary
 *  variant (the next case) is tinted and carries a "Next" badge. */
function CaseLinkCard({
  playbook,
  primary = false,
  onOpen,
}: {
  playbook: Playbook;
  primary?: boolean;
  onOpen: () => void;
}): ReactElement {
  const { t } = useTranslation();
  const tint = tintFor(playbook.category);
  const cat = CATEGORY_BY_ID[playbook.category];
  const Icon = iconFor(playbook.icon);
  const title = t(playbook.titleKey, { defaultValue: playbook.titleDefault });
  return (
    <button
      type="button"
      onClick={onOpen}
      className={clsx(
        "group flex h-full w-full items-start gap-3 rounded-2xl border p-4 text-left transition-all",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
        primary
          ? "border-oe-blue/50 bg-oe-blue-subtle hover:border-oe-blue"
          : "border-border-light bg-surface-primary hover:border-oe-blue/40 hover:bg-surface-secondary/40",
      )}
    >
      <span
        className={clsx(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset",
          tint.tile,
        )}
      >
        <Icon size={18} strokeWidth={2} aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={clsx(
              "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-medium",
              tint.chip,
            )}
          >
            {t(cat.labelKey, { defaultValue: cat.labelDefault })}
          </span>
          {primary && (
            <span className="inline-flex items-center rounded-md bg-oe-blue px-1.5 py-0.5 text-2xs font-semibold text-white">
              {t("cases.next.badge", { defaultValue: "Next" })}
            </span>
          )}
        </span>
        <span className="mt-1.5 block text-sm font-semibold leading-snug text-content-primary group-hover:text-oe-blue-text">
          {title}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs font-medium text-content-tertiary">
          <span className="inline-flex items-center gap-1">
            <ListChecks size={11} aria-hidden="true" />
            {t("cases.card.steps", {
              defaultValue: "{{count}} steps",
              count: playbook.steps.length,
            })}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock size={11} aria-hidden="true" />
            {t("cases.card.minutes", {
              defaultValue: "about {{count}} min",
              count: playbook.estMinutes,
            })}
          </span>
        </span>
      </span>
      <ArrowRight
        size={16}
        strokeWidth={2.2}
        className="mt-0.5 shrink-0 text-content-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue rtl:rotate-180"
        aria-hidden="true"
      />
    </button>
  );
}

export interface PlaybookRunnerProps {
  playbook: Playbook;
  /** Optional handler for the "All cases" back control. */
  onBack?: () => void;
}

export function PlaybookRunner({ playbook, onBack }: PlaybookRunnerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cardRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const toggleStepDone = useCasesStore((s) => s.toggleStepDone);
  const setCurrentStep = useCasesStore((s) => s.setCurrentStep);
  const reset = useCasesStore((s) => s.reset);
  const setSelectedProject = useCasesStore((s) => s.setSelectedProject);

  /* ── Sample-project picker ────────────────────────────────────────────── */
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: projectsApi.list,
    retry: false,
    staleTime: 5 * 60_000,
  });

  // Sample (seeded) projects first so they are the obvious thing to learn on,
  // then the rest, each group alphabetical.
  const sortedProjects = useMemo(() => {
    const list = [...(projects ?? [])];
    return list.sort((a, b) => {
      const ad = isDemoProject(a) ? 0 : 1;
      const bd = isDemoProject(b) ? 0 : 1;
      if (ad !== bd) return ad - bd;
      return a.name.localeCompare(b.name);
    });
  }, [projects]);

  const selectedRaw = useCasesStore((s) => s.selected[playbook.id]) ?? "";
  const projectsLoaded = projects !== undefined;
  // Validate the persisted selection against the live list. A stale id resolves
  // to null, so "Go" never navigates into a dead /projects/<id> route.
  const selectedProject = useMemo(
    () =>
      selectedRaw
        ? (sortedProjects.find((p) => p.id === selectedRaw) ?? null)
        : null,
    [sortedProjects, selectedRaw],
  );
  const projectId =
    selectedProject?.id ?? (projectsLoaded ? null : selectedRaw || null);

  // Drop a persisted selection that no longer resolves to a live project.
  useEffect(() => {
    if (projectsLoaded && selectedRaw && !selectedProject) {
      setSelectedProject(playbook.id, "");
    }
  }, [
    projectsLoaded,
    selectedRaw,
    selectedProject,
    setSelectedProject,
    playbook.id,
  ]);

  /* ── Progress for the active run ──────────────────────────────────────── */
  const key = runKey(playbook.id, projectId);
  const progress = useCasesStore((s) => s.runs[key]) ?? EMPTY_PROGRESS;
  const total = playbook.steps.length;
  const currentIndex = clampStepIndex(progress.currentStepIndex, total);
  const doneCount = completedCount(progress, playbook);
  const pct = progressPct(progress, playbook);
  const allDone = isPlaybookDone(progress, playbook);

  // Single writer for the current step: clamps, dedupes and persists the index.
  const selectStep = useCallback(
    (index: number) => setCurrentStep(playbook.id, projectId, index, total),
    [setCurrentStep, playbook.id, projectId, total],
  );

  // Bring a step block into view (card taps and the primary action both use it).
  const scrollToStep = useCallback((stepId: string) => {
    document
      .getElementById(`case-step-${stepId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // Open another case from the journey footer and start it from the top.
  const openCase = useCallback(
    (id: string) => {
      navigate(`/cases/${id}`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [navigate],
  );

  // Where to go from here: the case(s) that naturally follow this one and a few
  // related siblings. Explicit `next` / `related` on the case win; otherwise
  // both are derived from the whole catalogue (see relatedness.ts). The `next`
  // ids are excluded from `related` so a case never shows in both lists.
  const nextCases = useMemo(() => nextCasesFor(playbook, PLAYBOOKS, 2), [playbook]);
  const relatedCases = useMemo(
    () =>
      relatedCasesFor(
        playbook,
        PLAYBOOKS,
        new Set(nextCases.map((c) => c.id)),
        4,
      ),
    [playbook, nextCases],
  );

  const handleGo = useCallback(
    (step: PlaybookStep) => {
      // Scope the chosen sample project so unscoped module pages also follow it.
      if (projectId && selectedProject) {
        useProjectContextStore
          .getState()
          .setActiveProject(projectId, selectedProject.name);
      }
      navigate(resolveStepRoute(step.to, projectId));
    },
    [navigate, projectId, selectedProject],
  );

  const handleToggle = useCallback(
    (step: PlaybookStep) => {
      const updated = toggleStep(progress, step.id);
      toggleStepDone(playbook.id, projectId, step.id);
      // When the step was just completed, move the current marker to the next
      // gap so the highlight tracks where the work is.
      if (isStepDone(updated, step.id)) {
        setCurrentStep(
          playbook.id,
          projectId,
          nextStepIndex(updated, playbook),
          total,
        );
      }
    },
    [progress, toggleStepDone, setCurrentStep, playbook, projectId, total],
  );

  // Keyboard walking of the process card row: both axes step through the row.
  const onCardKeyDown = useCallback(
    (e: KeyboardEvent, index: number) => {
      let target: number | null = null;
      if (e.key === "ArrowDown" || e.key === "ArrowRight")
        target = clampStepIndex(index + 1, total);
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft")
        target = clampStepIndex(index - 1, total);
      else if (e.key === "Home") target = 0;
      else if (e.key === "End") target = total - 1;
      if (target === null) return;
      e.preventDefault();
      selectStep(target);
      cardRefs.current[target]?.focus();
    },
    [selectStep, total],
  );

  // Resolve a flow item list (input / output) to display strings once.
  const resolveFlow = useCallback(
    (step: PlaybookStep | undefined, side: "inputs" | "outputs"): string[] =>
      (step?.[side] ?? []).map((it) =>
        it.labelKey ? t(it.labelKey, { defaultValue: it.label }) : it.label,
      ),
    [t],
  );

  // Resolve the optional one-line hint that sits above an In / Out list and
  // explains, in a sentence, what the estimator is bringing in or getting out.
  const resolveHint = useCallback(
    (step: PlaybookStep, side: "inputs" | "outputs"): string | undefined => {
      const key = side === "inputs" ? step.inputsHintKey : step.outputsHintKey;
      const def = side === "inputs" ? step.inputsHintDefault : step.outputsHintDefault;
      if (key) return t(key, { defaultValue: def ?? "" }) || undefined;
      return def || undefined;
    },
    [t],
  );

  const title = t(playbook.titleKey, { defaultValue: playbook.titleDefault });
  const desc = t(playbook.descKey, { defaultValue: playbook.descDefault });
  const longDesc =
    playbook.longDescKey && playbook.longDescDefault
      ? t(playbook.longDescKey, { defaultValue: playbook.longDescDefault })
      : null;
  const selectId = `cases-run-on-${playbook.id}`;
  const progressLabel = t("cases.steps_progress", {
    defaultValue: "{{done}} of {{total}} steps",
    done: doneCount,
    total,
  });

  // Visual identity for the case meta chip.
  const tint = tintFor(playbook.category);
  const cat = CATEGORY_BY_ID[playbook.category];
  const PlaybookIcon = iconFor(playbook.icon);

  // The primary reads as Start / Continue / Review depending on where the run
  // stands, so returning to a half-finished case is obvious.
  const hasStarted = doneCount > 0 || currentIndex > 0;
  const primaryLabel = allDone
    ? t("cases.hero.review", { defaultValue: "Review case" })
    : hasStarted
      ? t("cases.hero.continue", { defaultValue: "Continue" })
      : t("cases.hero.start", { defaultValue: "Start case" });

  const resetButton = (
    <Button
      variant="ghost"
      size="sm"
      icon={<RotateCcw size={13} />}
      onClick={() => reset(playbook.id, projectId)}
      disabled={doneCount === 0 && progress.currentStepIndex === 0}
      title={t("cases.reset_hint", {
        defaultValue: "Clear progress for this case and start over",
      })}
    >
      {t("cases.reset", { defaultValue: "Reset progress" })}
    </Button>
  );

  // The scene element for a step's module action, resolved per step.
  const sceneFor = (step: PlaybookStep, stepTitle: string): ReactElement =>
    step.scene && hasProcessScene(step.scene) ? (
      <StepProcessScene
        sceneId={step.scene}
        title={stepTitle}
        className="aspect-[10/7] w-full"
      />
    ) : (
      <StepScene
        icon={step.icon}
        title={stepTitle}
        className="aspect-[10/7] w-full"
      />
    );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* ── Back ────────────────────────────────────────────────────────── */}
      <button
        type="button"
        onClick={onBack ?? (() => navigate("/cases"))}
        className="inline-flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      >
        <ArrowLeft size={14} className="rtl:rotate-180" />
        {t("cases.back_to_list", { defaultValue: "All cases" })}
      </button>

      <header className="rounded-2xl border border-border-light bg-gradient-to-br from-oe-blue/[0.08] via-oe-blue/[0.03] to-transparent p-5 sm:p-6">
        {/* Two columns on wide screens: the case identity and purpose on the
            left, a compact control panel (progress, the primary action, reset
            and the sample-project picker) on the right. They stack on narrow
            screens; the panel sits at its natural height, top-aligned. */}
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_19rem] lg:items-start lg:gap-8">
          {/* Left: what this case is and why */}
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              <span
                className={clsx(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-2xs font-medium",
                  tint.chip,
                )}
              >
                <PlaybookIcon size={11} strokeWidth={2} aria-hidden="true" />
                {t(cat.labelKey, { defaultValue: cat.labelDefault })}
              </span>
              <span className="inline-flex items-center gap-1 text-2xs font-medium text-content-tertiary">
                <Clock size={11} aria-hidden="true" />
                {t("cases.card.minutes", {
                  defaultValue: "about {{count}} min",
                  count: playbook.estMinutes,
                })}
              </span>
              <span className="inline-flex items-center gap-1 text-2xs font-medium text-content-tertiary">
                <ListChecks size={11} aria-hidden="true" />
                {t("cases.card.steps", { defaultValue: "{{count}} steps", count: total })}
              </span>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-content-primary sm:text-3xl">
              {title}
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-content-secondary sm:text-base">
              {desc}
            </p>
            {longDesc && (
              <p className="mt-2 text-sm leading-relaxed text-content-tertiary">
                {longDesc}
              </p>
            )}
          </div>

          {/* Right: a compact control panel - progress, primary action, reset
              and the sample-project picker, stacked in one tidy card. */}
          <div className="rounded-xl border border-border-light/70 bg-surface-primary/60 p-4">
            <div
              className="flex flex-col gap-1.5"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={doneCount}
              aria-valuetext={progressLabel}
              aria-label={t("cases.progress_label", { defaultValue: "Case progress" })}
              aria-live="polite"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t("cases.progress_label", { defaultValue: "Case progress" })}
                </span>
                <span className="shrink-0 text-2xs font-medium tabular-nums text-content-secondary">
                  {progressLabel}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="h-full rounded-full bg-oe-blue transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
            <div className="mt-4 flex flex-col gap-2">
              <Button
                variant="primary"
                size="lg"
                icon={<Play size={16} />}
                className="w-full justify-center"
                onClick={() => {
                  selectStep(currentIndex);
                  const step = playbook.steps[currentIndex];
                  if (step) scrollToStep(step.id);
                }}
              >
                {primaryLabel}
              </Button>
              <div className="flex justify-center">{resetButton}</div>
            </div>
            <div className="mt-4 border-t border-border-light/70 pt-3">
              <label
                htmlFor={selectId}
                className="block text-2xs font-semibold uppercase tracking-wide text-content-tertiary"
              >
                {t("cases.run_on", { defaultValue: "Run on" })}
              </label>
              <select
                id={selectId}
                value={selectedRaw}
                onChange={(e) => setSelectedProject(playbook.id, e.target.value)}
                className="mt-1.5 h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-xs text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                <option value="">
                  {t("cases.run_on_none", {
                    defaultValue: "No sample project (just open the module)",
                  })}
                </option>
                {sortedProjects.map((p) => {
                  const label = isDemoProject(p)
                    ? t("cases.run_on_sample_option", {
                        defaultValue: "{{name}} (sample)",
                        name: p.name,
                      })
                    : p.name;
                  return (
                    <option key={p.id} value={p.id}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>
        </div>
      </header>

      {/* ── The process: a full-width row of step cards, up to six across and
          wrapping after that. Each card is a picture of the work and its title;
          clicking one jumps to that step below and marks it current. ──────── */}
      <section aria-label={t("cases.the_process", { defaultValue: "The process" })}>
        <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t("cases.the_process", { defaultValue: "The process" })}
          </p>
          <p className="text-xs text-content-tertiary">
            {t("cases.process_help", {
              defaultValue: "Choose a step to see what happens and why",
            })}
          </p>
        </div>
        {/* Six across from the small breakpoint up so the strip stays a compact
            journey map (three across on the narrowest screens); more steps just
            wrap to a second row of six. */}
        <ol
          className="grid grid-cols-3 gap-2 sm:grid-cols-6"
          aria-label={title}
        >
          {playbook.steps.map((step, i) => {
            const done = isStepDone(progress, step.id);
            const isCurrent = i === currentIndex;
            const stepTitle = t(step.titleKey, { defaultValue: step.titleDefault });
            return (
              <li key={step.id} className="min-w-0">
                <button
                  type="button"
                  ref={(el) => {
                    cardRefs.current[i] = el;
                  }}
                  onClick={() => {
                    selectStep(i);
                    scrollToStep(step.id);
                  }}
                  onKeyDown={(e) => onCardKeyDown(e, i)}
                  aria-current={isCurrent ? "step" : undefined}
                  title={stepTitle}
                  className={clsx(
                    "group flex h-full w-full flex-col gap-1 rounded-lg border p-1 text-left transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40",
                    isCurrent
                      ? "border-oe-blue bg-oe-blue-subtle ring-1 ring-inset ring-oe-blue/30"
                      : done
                        ? "border-semantic-success/30 bg-semantic-success/10 hover:border-semantic-success/50"
                        : "border-border-light bg-surface-primary hover:border-oe-blue/40 hover:bg-surface-secondary/40",
                  )}
                >
                  <div className="relative">
                    <StepThumb step={step} className="aspect-[16/9] w-full" />
                    <span
                      className={clsx(
                        "absolute start-0.5 top-0.5 flex h-4 w-4 items-center justify-center rounded-full text-2xs font-bold shadow-sm",
                        done
                          ? "bg-semantic-success text-white"
                          : isCurrent
                            ? "bg-oe-blue text-white"
                            : "bg-surface-primary/95 text-content-secondary ring-1 ring-inset ring-border-light",
                      )}
                      aria-hidden="true"
                    >
                      {done ? <Check size={12} strokeWidth={2.5} /> : i + 1}
                    </span>
                  </div>
                  <span
                    className={clsx(
                      "line-clamp-2 px-0.5 text-2xs font-semibold leading-snug",
                      isCurrent ? "text-oe-blue-text" : "text-content-primary",
                    )}
                  >
                    {stepTitle}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </section>

      {/* ── Every step, in full, one under the other ─────────────────────── */}
      <div className="space-y-3">
        {playbook.steps.map((step, i) => {
          const stepTitle = t(step.titleKey, { defaultValue: step.titleDefault });
          const stepModule = step.moduleLabelKey
            ? t(step.moduleLabelKey, { defaultValue: step.moduleLabel })
            : step.moduleLabel;
          return (
            <StepBlock
              key={step.id}
              id={`case-step-${step.id}`}
              index={i}
              total={total}
              title={stepTitle}
              moduleLabel={stepModule}
              iconName={step.icon}
              what={t(step.whatKey, { defaultValue: step.whatDefault })}
              why={t(step.whyKey, { defaultValue: step.whyDefault })}
              inputs={resolveFlow(step, "inputs")}
              outputs={resolveFlow(step, "outputs")}
              inputsHint={resolveHint(step, "inputs")}
              outputsHint={resolveHint(step, "outputs")}
              scene={sceneFor(step, stepTitle)}
              done={isStepDone(progress, step.id)}
              isCurrent={i === currentIndex}
              onOpen={() => handleGo(step)}
              onToggle={() => handleToggle(step)}
              openLabel={t("cases.step.go_to_module", {
                defaultValue: "Open {{module}}",
                module: stepModule,
              })}
            />
          );
        })}
      </div>

      {/* ── Completion note ─────────────────────────────────────────────── */}
      {allDone && (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-semantic-success/40 bg-semantic-success-bg px-4 py-3 animate-card-in"
        >
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-semantic-success" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-content-primary">
              {t("cases.all_done_title", { defaultValue: "Case complete" })}
            </p>
            <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
              {t("cases.all_done_body", {
                defaultValue:
                  "You have stepped through every part of this case. Reset it to run again, or pick another case.",
              })}
            </p>
          </div>
          <Badge variant="success" size="sm">
            {pct}%
          </Badge>
        </div>
      )}

      {/* ── Where to go next: the case that follows + related cases. Always
          shown (not gated on completion) so the catalogue reads as one
          connected journey rather than a set of dead ends. ───────────────── */}
      {(nextCases.length > 0 || relatedCases.length > 0) && (
        <section
          aria-label={t("cases.journey.heading", {
            defaultValue: "Where to go next",
          })}
          className="space-y-5 border-t border-border-light pt-6"
        >
          {nextCases.length > 0 && (
            <div>
              <div className="mb-2.5">
                <h2 className="text-base font-semibold text-content-primary">
                  {t("cases.next.heading", { defaultValue: "Do this next" })}
                </h2>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {t("cases.next.subtitle", {
                    defaultValue: "The case that naturally follows this one.",
                  })}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {nextCases.map((c) => (
                  <CaseLinkCard
                    key={c.id}
                    playbook={c}
                    primary
                    onOpen={() => openCase(c.id)}
                  />
                ))}
              </div>
            </div>
          )}
          {relatedCases.length > 0 && (
            <div>
              <div className="mb-2.5">
                <h2 className="text-base font-semibold text-content-primary">
                  {t("cases.related.heading", { defaultValue: "Related cases" })}
                </h2>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {t("cases.related.subtitle", {
                    defaultValue: "Other cases that touch the same work.",
                  })}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {relatedCases.map((c) => (
                  <CaseLinkCard
                    key={c.id}
                    playbook={c}
                    onOpen={() => openCase(c.id)}
                  />
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
