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
        'pointer-events-none absolute bottom-full start-1/2 z-50 mb-1.5 -translate-x-1/2 rtl:translate-x-1/2 whitespace-nowrap',
        'rounded-md bg-slate-900 px-2 py-1 text-2xs font-medium text-white shadow-lg opacity-0 transition-opacity duration-150',
        'group-hover:opacity-100 group-hover:delay-300 group-focus-visible:opacity-100 dark:bg-slate-700 motion-reduce:transition-none',
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
        'group relative flex w-full items-center gap-2.5 px-3 py-2 text-start hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none',
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
      <ExternalLink size={11} className="shrink-0 text-content-quaternary rtl:-scale-x-100" aria-hidden />
      <span className="sr-only">{meta.newTab}</span>
      {paid && <PaidHint id={hint.id} lesson={item.kind === 'lesson'} dismissed={hint.dismissed} />}
    </a>
  );
}

/** The photo of a course: a still from the course itself, shipped as `public/academy-courses/<slug>.webp`. */
function photoUrl(item: AcademyItem): string | null {
  if (item.kind !== 'course') return null;
  const slug = item.id.split(':')[1];
  return slug ? `${import.meta.env.BASE_URL}academy-courses/${slug}.webp` : null;
}

function CardMedia({ item, Icon, country }: { item: AcademyItem; Icon: LucideIcon; country?: string }) {
  const src = photoUrl(item);
  const [failed, setFailed] = useState(false);
  return (
    <span
      className="relative block aspect-video overflow-hidden border-b border-border-light bg-surface-secondary"
      data-testid="academy-item-media"
    >
      {src && !failed ? (
        <img
          src={src}
          width={480}
          height={300}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-content-quaternary">
          <Icon size={32} strokeWidth={1.5} aria-hidden />
        </span>
      )}
      {(item.country ?? item.market) && country && (
        <span
          data-testid="academy-item-country"
          data-country={item.country ?? item.market}
          className="absolute start-2 top-2 inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-elevated/95 px-1.5 py-1 text-2xs font-medium text-content-primary"
        >
          <CountryFlag code={(item.country ?? item.market)!} size={16} />
          {country}
        </span>
      )}
    </span>
  );
}

/** With `media`, the card opens with a 16:9 picture (the course photo, else a quiet kind tile) and shows
 *  the item's country, named by `countryName`, over its corner. */
export function AcademyItemCard({
  item,
  media = false,
  countryName,
}: {
  item: AcademyItem;
  media?: boolean;
  countryName?: string;
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
      {media && <CardMedia item={item} Icon={Icon} country={countryName} />}
      {body(
        <>
          <span className="flex items-center gap-1.5 pe-6 text-2xs font-medium text-content-tertiary">
            <Icon size={14} className={paid ? 'text-oe-purple-text' : undefined} aria-hidden />
            <span className="truncate">{[meta.kindLabel, meta.duration, meta.otherLanguage].filter(Boolean).join(' · ')}</span>
          </span>
          <span lang={item.contentLanguage} className="line-clamp-2 text-sm font-semibold text-content-primary">
            {item.title}
          </span>
          <span className="flex flex-wrap gap-1">
            {itemTopics(item)
              .slice(0, 2)
              .map((topic) => (
                <Badge key={topic} variant="neutral" size="sm">
                  {topic}
                </Badge>
              ))}
          </span>
          <span className="mt-auto inline-flex items-center gap-1 text-xs font-medium text-oe-blue">
            {t('learn.opens_academy', { defaultValue: 'Opens on Academy' })}
            <ExternalLink size={11} className="rtl:-scale-x-100" aria-hidden />
            <span className="sr-only">{meta.newTab}</span>
          </span>
        </>,
      )}
      {paid && (
        <Crown
          size={14}
          strokeWidth={2}
          className={clsx('absolute end-3 text-oe-purple-text', media ? 'bottom-3' : 'top-3')}
          aria-hidden
        />
      )}
      {paid && <PaidHint id={hint.id} lesson={item.kind === 'lesson'} dismissed={hint.dismissed} />}
    </a>
  );
}
