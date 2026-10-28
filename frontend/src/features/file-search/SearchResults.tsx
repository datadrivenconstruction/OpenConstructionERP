// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Vertical list of search hits with highlighted snippets.
 *
 * Renders the result returned by `useContentSearch`. Designed to slot
 * underneath / next to the file grid — the caller controls layout.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { FileText, Image as ImageIcon, Layout, Box, Pencil, File, PenTool, FileBarChart, Tag } from 'lucide-react';
import { SnippetHighlight } from './SnippetHighlight';
import type { SearchHit } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

const KIND_ICON: Record<string, typeof FileText> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

interface SearchResultsProps {
  hits: SearchHit[];
  query: string;
  isLoading?: boolean | undefined;
  onOpen?: ((hit: SearchHit) => void) | undefined;
  className?: string | undefined;
}

export function SearchResults({ hits, query, isLoading, onOpen, className }: SearchResultsProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className={clsx('p-4 space-y-2', className)}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-14 rounded-lg border border-border-light bg-surface-secondary/40 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (hits.length === 0) {
    return (
      <div
        className={clsx(
          'flex flex-col items-center justify-center py-10 px-6 text-center text-content-tertiary',
          className,
        )}
      >
        <FileText size={22} className="mb-2 opacity-60" />
        <p className="text-sm">
          {t('files.search.empty', { defaultValue: 'No matching files yet.' })}
        </p>
      </div>
    );
  }

  return (
    <ul
      className={clsx('divide-y divide-border-light', className)}
      role="list"
      aria-label={t('files.search.results', { defaultValue: 'Search results' })}
    >
      {hits.map((hit) => {
        const Icon = KIND_ICON[hit.kind] ?? File;
        return (
          <li key={`${hit.kind}-${hit.file_id}`}>
            <button
              type="button"
              onClick={() => onOpen?.(hit)}
              className="w-full text-left flex gap-3 p-3 hover:bg-surface-secondary focus:outline-none focus-visible:bg-surface-secondary"
            >
              <div className="shrink-0 mt-0.5 text-content-tertiary">
                <Icon size={16} strokeWidth={1.5} />
              </div>
              <div className="min-w-0 flex-1">
                <p
                  className="text-sm font-medium text-content-primary truncate"
                  title={hit.canonical_name}
                >
                  <SnippetHighlight text={hit.canonical_name} query={query} />
                </p>
                <p className="text-xs text-content-secondary mt-0.5 line-clamp-2 leading-snug">
                  <SnippetHighlight text={hit.snippet} query={query} />
                </p>
                <div className="mt-1 flex items-center gap-2 text-2xs text-content-tertiary">
                  <span className="uppercase tracking-wide">{hit.kind}</span>
                  {hit.page_count != null && (
                    <span className="tabular-nums">
                      {t('files.search.pages', {
                        defaultValue: '{{count}} pages',
                        count: hit.page_count,
                      })}
                    </span>
                  )}
                  <span className="ms-auto tabular-nums">
                    {t('files.search.score', {
                      defaultValue: 'Score {{score}}',
                      score: fmtFixed(hit.score, 2),
                    })}
                  </span>
                </div>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
