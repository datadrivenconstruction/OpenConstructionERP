// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cover of a course card: a photo of the course's project, the learner's
// role with the people met on the way, and the course path as a row of
// hexagon steps, one per ERP module the tasks walk through. Checklists and
// guides keep the drawn cover (CourseCover).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ArrowLeftRight,
  BookOpenCheck,
  Box,
  Calculator,
  ChartGantt,
  ChartPie,
  Check,
  ClipboardCheck,
  Database,
  FileText,
  FileWarning,
  Flag,
  HardHat,
  Layers,
  Leaf,
  ListChecks,
  MessageCircleQuestion,
  NotebookPen,
  PencilRuler,
  Receipt,
  Ruler,
  Scale,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import type { AcademyItem, CourseStep } from './academyTypes';
import { CourseCover } from './CourseCover';

/** Photo of a course's project, shipped as `public/academy-courses/<slug>.webp`. */
export function coursePhotoUrl(item: Pick<AcademyItem, 'id' | 'kind'>): string | null {
  if (item.kind !== 'course') return null;
  const slug = item.id.split(':')[1];
  return slug ? `${import.meta.env.BASE_URL}academy-courses/${slug}.webp` : null;
}

function personUrl(img: string): string {
  return `${import.meta.env.BASE_URL}academy-courses/people/${img}.webp`;
}

export type StepState = 'done' | 'current' | 'ahead';

/** Every step is done once the course is; otherwise the first step is where the learner starts. */
export function stepStates(steps: readonly CourseStep[], courseDone: boolean): StepState[] {
  return steps.map((_, i) => (courseDone ? 'done' : i === 0 ? 'current' : 'ahead'));
}

export function stepRange(s: CourseStep): string {
  return s.from === s.to ? String(s.from) : `${s.from}–${s.to}`;
}

/** Pointy-top hexagon on a 40 × 46 box. */
const HEX_D = 'M20 2.2 38 12.6v20.8L20 43.8 2 33.4V12.6z';
const DONE = 'var(--oe-brand-academy)';

/** The ERP module a step works in, as an icon. */
const STEP_ICON: Record<string, LucideIcon> = {
  boq: Calculator,
  bid_management: Scale,
  contracts: Receipt,
  variations: ArrowLeftRight,
  documents: FileText,
  takeoff: Ruler,
  dwg_takeoff: PencilRuler,
  bim_hub: Box,
  bim: Box,
  costs: Database,
  carbon: Leaf,
  schedule: ChartGantt,
  full_evm: TrendingUp,
  cvr: ChartPie,
  risk: TriangleAlert,
  inspections: ClipboardCheck,
  ncr: FileWarning,
  rfi: MessageCircleQuestion,
  punchlist: ListChecks,
  closeout: BookOpenCheck,
  daily_diary: NotebookPen,
  safety: HardHat,
  clash: Layers,
  defects_liability: Wrench,
  bim_requirements: ShieldCheck,
  bcf: Flag,
};

/** The course path: hexagon steps joined by a line, each named by its module and numbered by its tasks. */
export function CoursePathStrip({ steps, done, className }: { steps: readonly CourseStep[]; done: boolean; className?: string }) {
  const { t } = useTranslation();
  const states = stepStates(steps, done);
  return (
    <ol
      aria-hidden
      data-testid="course-path"
      className={clsx(
        'flex items-start rounded-xl border border-border-light bg-surface-elevated/95 px-1 py-2 shadow-md backdrop-blur-md',
        className,
      )}
    >
      {steps.map((s, i) => {
        const state = states[i]!;
        const filled = state !== 'ahead';
        const Icon = STEP_ICON[s.module] ?? FileText;
        return (
          <li key={i} className="relative flex min-w-0 flex-1 flex-col items-center" data-state={state}>
            {i > 0 && (
              <span
                className={clsx('absolute end-[calc(50%+15px)] top-[17px] h-px w-[calc(100%-30px)]', state !== 'done' && 'bg-border')}
                style={state === 'done' ? { background: DONE } : undefined}
              />
            )}
            <span className="relative flex h-[35px] w-[30px] items-center justify-center">
              <svg viewBox="0 0 40 46" className="absolute inset-0 h-full w-full overflow-visible">
                <path
                  d={HEX_D}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  className={filled ? undefined : 'fill-surface-secondary stroke-border'}
                  style={filled ? { fill: DONE, stroke: DONE } : undefined}
                />
              </svg>
              {state === 'done' ? (
                <Check size={15} strokeWidth={2.75} className="relative text-white" />
              ) : (
                <Icon size={15} strokeWidth={1.75} className={clsx('relative', filled ? 'text-white' : 'text-content-secondary')} />
              )}
            </span>
            <span
              className={clsx(
                'mt-1 line-clamp-2 max-w-full break-words px-0.5 text-center font-semibold leading-tight',
                steps.length > 3 ? 'text-[10px]' : 'text-2xs',
                state === 'ahead' ? 'text-content-secondary' : 'text-content-primary',
              )}
            >
              {t(`learn.cover.stage.${s.module}`, { defaultValue: s.module })}
            </span>
            <span className="text-[10px] leading-tight tabular-nums text-content-tertiary">{stepRange(s)}</span>
          </li>
        );
      })}
    </ol>
  );
}

const ROLE_LABEL: Record<NonNullable<AcademyItem['role']>, string> = {
  est: 'Estimator',
  qs: 'Quantity surveyor',
  site: 'Site & project manager',
  bim: 'BIM & data',
  client: 'Client & design side',
};

function Face({ img, className }: { img: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className={clsx('block bg-surface-secondary', className)} />;
  return (
    <img
      src={personUrl(img)}
      alt=""
      width={36}
      height={36}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={clsx('block object-cover', className)}
    />
  );
}

/** Photo with the learner's role and the people met; the drawn cover when the item has no photo. */
export function CourseCardCover({ item, done }: { item: AcademyItem; done: boolean }) {
  const { t } = useTranslation();
  const src = coursePhotoUrl(item);
  const [failed, setFailed] = useState(false);
  const people = item.people;
  const role = item.role;
  const steps = item.steps ?? [];
  return (
    <>
      {src && !failed ? (
        <img
          src={src}
          alt=""
          width={560}
          height={374}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
          data-testid="course-photo"
        />
      ) : (
        <CourseCover item={item} className="absolute inset-0 h-full w-full" />
      )}
      {role && (
        <span className="absolute inset-x-0 top-0 flex items-start justify-between gap-2 bg-gradient-to-b from-black/60 to-transparent p-2.5 pb-8" data-testid="course-role">
          <span className="inline-flex min-w-0 items-center gap-2">
            {people && <Face img={people.you} className="h-8 w-8 shrink-0 rounded-md ring-2 ring-white/80" />}
            <span className="flex min-w-0 flex-col leading-tight text-white [text-shadow:0_1px_2px_rgb(0_0_0/0.5)]">
              <span className="truncate text-xs font-semibold">
                {t(`learn.cover.role.${role}`, { defaultValue: ROLE_LABEL[role] })}
              </span>
              {people && people.crew > 0 && (
                <span className="truncate text-2xs text-white/85">
                  {t('learn.cover.works_with', {
                    count: people.crew,
                    defaultValue_one: 'works with {{count}} person',
                    defaultValue_other: 'works with {{count}} people',
                  })}
                </span>
              )}
            </span>
          </span>
          {people && people.others.length > 0 && (
            <span className="flex shrink-0 gap-1" aria-hidden>
              {people.others.map((img) => (
                <Face key={img} img={img} className="h-6 w-6 rounded-md ring-2 ring-white/80" />
              ))}
            </span>
          )}
        </span>
      )}
    </>
  );
}
