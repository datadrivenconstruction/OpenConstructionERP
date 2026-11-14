// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The long-form article beside the course filters: a narrow upright card
// (cover on top, words below) so it fits a fifth of the row on desktop and
// stacks under the filters on a phone. Same article and cover as the Cases
// hub card; a drawn panel stands in when the cover cannot load.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUpRight, Newspaper } from 'lucide-react';
import { FEATURED_ARTICLE_COVER, FEATURED_ARTICLE_URL } from '@/features/cases/FeaturedArticle';

export function CoursesFeaturedArticle() {
  const { t } = useTranslation();
  const [coverFailed, setCoverFailed] = useState(false);

  const title = t('sidebar.video_news.title', { defaultValue: 'Uberization of Construction' });
  const subtitle = t('sidebar.video_news.subtitle', {
    defaultValue: 'Open data, transparency, and the idea behind the platform',
  });
  const read = t('sidebar.video_news.read', { defaultValue: 'Read the article' });
  const eyebrow = t('cases.featured_article.eyebrow', { defaultValue: 'Featured article' });
  const label = t('cases.featured_article.label', {
    defaultValue: 'Featured article: {{title}}. Read the article, opens in a new tab',
    title,
  });

  return (
    <a
      href={FEATURED_ARTICLE_URL}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="courses-featured-article"
      aria-label={label}
      className="group flex h-full min-w-0 flex-row overflow-hidden rounded-xl border border-border-light bg-surface-elevated transition-shadow hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 md:flex-col"
    >
      <div className="relative aspect-[1200/630] w-2/5 shrink-0 overflow-hidden bg-gradient-to-br from-oe-blue/25 via-oe-blue/10 to-surface-secondary md:w-full">
        {coverFailed ? (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface-primary/80 text-oe-blue-text ring-1 ring-oe-blue/20">
              <Newspaper size={22} strokeWidth={1.8} />
            </span>
          </div>
        ) : (
          <img
            src={FEATURED_ARTICLE_COVER}
            alt=""
            width={1200}
            height={630}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setCoverFailed(true)}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03] motion-reduce:transition-none"
          />
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-3">
        <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-oe-blue-text">
          <Newspaper size={12} aria-hidden="true" />
          {eyebrow}
        </span>
        <span className="text-sm font-semibold leading-snug text-content-primary">{title}</span>
        <span className="line-clamp-3 text-xs leading-relaxed text-content-secondary">{subtitle}</span>
        <span className="mt-auto inline-flex items-center gap-1 pt-1 text-xs font-semibold text-oe-blue-text group-hover:underline">
          {read}
          <ArrowUpRight size={14} className="shrink-0" aria-hidden="true" />
        </span>
      </div>
    </a>
  );
}
