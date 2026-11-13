// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One course, checklist or guide as a link to the Academy site: a compact row
// for the popover and a card for the hub. A course with a purple edge and a
// crown is one the Academy offers as paid training; the hover or focus
// tooltip says so and is the only place the app uses the word. Nothing here
// opens by itself, and the link goes out as a plain new-tab anchor.

import { useId, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { BookOpen, Crown, ExternalLink, FileText, GraduationCap, ListChecks, type LucideIcon } from 'lucide-react';
import { Badge } from '@/shared/ui/Badge';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import type { AcademyItem, AcademyItemKind } from './academyTypes';
import { CourseCardCover, CoursePathStrip } from './CourseCardCover';
import { academyUrlFor, formatItemDuration, inOtherLanguage, itemTopics, languageName } from './academyItems';

const KIND_ICON: Record<AcademyItemKind, LucideIcon> = {
  course: GraduationCap,
  lesson: BookOpen,
  checklist: ListChecks,
  article: FileText,
};

const KIND_LABEL: Record<AcademyItemKind, [key: string, fallback: string]> = {
  course: ['learn.kind.course', 'Course'],
  lesson: ['learn.kind.lesson', 'Lesson'],
  checklist: ['learn.kind.checklist', 'Checklist'],
  article: ['learn.kind.article', 'Guide'],
};

/** The tooltip state of one link: id for `aria-describedby`, Esc to dismiss while focus stays. */
function useHint() {
  const id = useId();
  const [dismissed, setDismissed] = useState(false);
  return {
    id,
    dismissed,
    handlers: {
      onKeyDown: (e: KeyboardEvent) => {
        if (e.key === 'Escape') setDismissed(true);
      },
      onMouseLeave: () => setDismissed(false),
      onBlur: () => setDismissed(false),
    },
  };
}

function PaidHint({ id, lesson, dismissed }: { id: string; lesson: boolean; dismissed: boolean }) {
  const { t } = useTranslation();
  return (
    <span
      role="tooltip"
      id={id}
      className={clsx(
        'pointer-events-none absolute bottom-full start-1/2 z-dropdown mb-1.5 -translate-x-1/2 rtl:translate-x-1/2 whitespace-nowrap',
        'rounded-md bg-slate-900 px-2 py-1 text-2xs font-medium text-white shadow-lg opacity-0 transition-opacity duration-150',
        'group-hover:opacity-100 group-hover:delay-300 group-focus-visible:opacity-100 motion-reduce:transition-none',
        dismissed && '!opacity-0',
      )}
    >
      {lesson
        ? t('learn.paid_lesson_tooltip', { defaultValue: 'Lesson from a paid training course' })
        : t('learn.paid_tooltip', { defaultValue: 'Paid training course' })}
    </span>
  );
}

function useItemMeta(item: AcademyItem) {
  const { t, i18n } = useTranslation();
  const language = i18n.language || 'en';
  const other = inOtherLanguage(item, language);
  const kind = KIND_LABEL[item.kind];
  return {
    href: academyUrlFor(item, language),
    kindLabel: t(kind[0], { defaultValue: kind[1] }),
    duration: item.durationMin ? formatItemDuration(item.durationMin, language) : null,
    otherLanguage: other
      ? t('learn.in_language', { defaultValue: 'In {{language}}', language: languageName(other, language) })
      : null,
    newTab: t('learn.opens_new_tab', { defaultValue: '(opens in a new tab)' }),
  };
}

export function AcademyItemRow({ item }: { item: AcademyItem }) {
  const meta = useItemMeta(item);
  const hint = useHint();
  const paid = item.access === 'paid';
  const Icon = KIND_ICON[item.kind];
  return (
    <a
      href={meta.href}
      target="_blank"
      rel="noopener noreferrer"
      aria-describedby={paid ? hint.id : undefined}
      data-testid="academy-item-row"
      data-access={item.access}
      {...(paid ? hint.handlers : {})}
      className={clsx(
        'group relative flex w-full items-center gap-2 px-3 py-2 text-start hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none',
        paid && 'border-s-2 border-oe-purple/60',
      )}
    >
      <Icon size={14} className={clsx('shrink-0', paid ? 'text-oe-purple-text' : 'text-content-tertiary')} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="flex items-start gap-1">
          <span lang={item.contentLanguage} className="line-clamp-2 text-xs font-medium leading-snug text-content-primary">
            {item.title}
          </span>
          {paid && <Crown size={12} strokeWidth={2} className="mt-0.5 shrink-0 text-oe-purple-text" aria-hidden />}
        </span>
        <span className="mt-0.5 block truncate text-2xs text-content-tertiary">
          {[meta.kindLabel, meta.duration, meta.otherLanguage].filter(Boolean).join(' · ')}
        </span>
      </span>
      <ExternalLink size={12} className="shrink-0 text-content-quaternary rtl:-scale-x-100" aria-hidden />
      <span className="sr-only">{meta.newTab}</span>
      {paid && <PaidHint id={hint.id} lesson={item.kind === 'lesson'} dismissed={hint.dismissed} />}
    </a>
  );
}

function CardMedia({ item, done }: { item: AcademyItem; done: boolean }) {
  const steps = item.steps ?? [];
  return (
    <>
      <span
        className="relative block aspect-[16/9] overflow-hidden border-b border-border-light bg-surface-secondary"
        data-testid="academy-item-media"
      >
        <CourseCardCover item={item} done={done} />
      </span>
      {steps.length > 0 && <CoursePathStrip steps={steps} done={done} className="relative z-[1] mx-3 -mt-12" />}
    </>
  );
}

/** With `media`, the card opens with its cover (the project photo, role and path of a course; the
 *  drawn cover of a checklist or guide) and names the item's country, given as `countryName`. */
export function AcademyItemCard({
  item,
  media = false,
  countryName,
  done = false,
}: {
  item: AcademyItem;
  media?: boolean;
  countryName?: string;
  /** The reader marked this course done: its path shows every step done. */
  done?: boolean;
}) {
  const { t } = useTranslation();
  const meta = useItemMeta(item);
  const hint = useHint();
  const paid = item.access === 'paid';
  const Icon = KIND_ICON[item.kind];
  const body = (children: ReactNode) =>
    media ? <span className="flex flex-1 flex-col gap-2 p-3">{children}</span> : <>{children}</>;
  return (
    <a
      href={meta.href}
      target="_blank"
      rel="noopener noreferrer"
      aria-describedby={paid ? hint.id : undefined}
      data-testid="academy-item-card"
      data-access={item.access}
      {...(paid ? hint.handlers : {})}
      className={clsx(
        'group relative flex flex-col gap-2 rounded-xl border text-start transition-colors duration-150 hover:shadow-md',
        media ? 'overflow-hidden' : 'p-3',
        'focus-visible:outline-none focus-visible:ring-2 motion-reduce:transition-none',
        paid
          ? 'border-oe-purple/30 bg-oe-purple-subtle/40 hover:border-oe-purple/60 focus-visible:ring-oe-purple'
          : 'border-border-light bg-surface-elevated hover:border-oe-blue/40 focus-visible:ring-oe-blue',
      )}
    >
      {media && <CardMedia item={item} done={done} />}
      {body(
        <>
          <span className={clsx('flex items-center gap-1.5 text-2xs font-medium text-content-tertiary', media ? 'order-2' : 'pe-6')}>
            <Icon size={14} className={paid ? 'text-oe-purple-text' : undefined} aria-hidden />
            <span className="truncate">{[meta.kindLabel, meta.duration, meta.otherLanguage].filter(Boolean).join(' · ')}</span>
            {paid && media && <Crown size={14} strokeWidth={2} className="ms-auto shrink-0 text-oe-purple-text" aria-hidden />}
          </span>
          <span
            lang={item.contentLanguage}
            className={clsx('line-clamp-2 text-sm font-semibold text-content-primary', media && 'order-1 leading-snug')}
          >
            {item.title}
          </span>
          <span className={clsx('flex flex-wrap gap-1', media && 'order-3')}>
            {itemTopics(item)
              .slice(0, 2)
              .map((topic) => (
                <Badge key={topic} variant="neutral" size="sm">
                  {topic}
                </Badge>
              ))}
          </span>
          <span className={clsx('mt-auto flex items-center gap-2 text-xs', media && 'order-4')}>
            {media && (item.country ?? item.market) && countryName && (
              <span
                data-testid="academy-item-country"
                data-country={item.country ?? item.market}
                className="inline-flex min-w-0 items-center gap-1.5 text-content-secondary"
              >
                <CountryFlag code={(item.country ?? item.market)!} size={16} />
                <span className="truncate">{countryName}</span>
              </span>
            )}
            <span className={clsx('inline-flex shrink-0 items-center gap-1 font-medium text-oe-blue', media && 'ms-auto')}>
              {t('learn.opens_academy', { defaultValue: 'Opens on Academy' })}
              <ExternalLink size={12} className="rtl:-scale-x-100" aria-hidden />
              <span className="sr-only">{meta.newTab}</span>
            </span>
          </span>
        </>,
      )}
      {paid && !media && <Crown size={14} strokeWidth={2} className="absolute end-3 top-3 text-oe-purple-text" aria-hidden />}
      {paid && <PaidHint id={hint.id} lesson={item.kind === 'lesson'} dismissed={hint.dismissed} />}
    </a>
  );
}
