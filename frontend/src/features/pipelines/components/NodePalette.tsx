// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<NodePalette>` — categorized list of node types, populated from
 * `GET /node-types/`. Cloned from EAC `EacBlockPalette`: 260 px collapsible
 * aside (wider than EAC's 220 — translated node names are long), local fuzzy
 * search on label + description, category accordion ordered by the workflow a
 * specialist thinks in.
 *
 * Each item supports drag (HTML5 dataTransfer) *and* click-to-insert (a
 * window CustomEvent the canvas listens for) so it works without a precise
 * drag — important for trackpad / touch / motor accessibility.
 */
import clsx from 'clsx';
import {
  ChevronLeft,
  ChevronRight,
  GripVertical,
  MousePointerClick,
  Search,
  X,
} from 'lucide-react';
import { useMemo, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Skeleton } from '@/shared/ui';

import { PortLegend } from './PortLegend';
import {
  PIPELINE_DND_MIME,
  type PaletteDragItem,
} from '../canvas/PipelineCanvas';
import { CATEGORY_ORDER, getCategoryTokens } from '../tokens';
import type { NodeTypeDef } from '../api';

export interface NodePaletteProps {
  nodeTypes: NodeTypeDef[];
  loading?: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  testId?: string;
}

function PaletteItem({ def }: { def: NodeTypeDef }) {
  const { t } = useTranslation();
  const tokens = getCategoryTokens(def.category);
  const Icon = tokens.Icon;
  const label =
    def.label ||
    t(`pipeline.nodetype.${def.type}`, { defaultValue: def.type });
  const description =
    def.description ||
    t(`pipeline.nodetype.${def.type}.desc`, { defaultValue: '' });

  const payload: PaletteDragItem = {
    type: def.type,
    category: def.category,
    label,
  };

  const onDragStart = (e: DragEvent<HTMLButtonElement>) => {
    e.dataTransfer.setData(PIPELINE_DND_MIME, JSON.stringify(payload));
    e.dataTransfer.effectAllowed = 'copy';
  };

  const onActivate = () => {
    window.dispatchEvent(
      new CustomEvent<PaletteDragItem>('oe-pipeline-insert', {
        detail: payload,
      }),
    );
  };

  return (
    <button
      type="button"
      draggable
      onDragStart={onDragStart}
      onClick={onActivate}
      data-testid={`pipeline-palette-item-${def.type}`}
      data-node-category={def.category}
      title={
        description
          ? t('pipeline.palette.item_title', {
              defaultValue: '{{label}} — {{description}}',
              label,
              description,
            })
          : label
      }
      className={clsx(
        'group flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-start',
        'transition-all duration-fast ease-oe transform-gpu cursor-grab',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        'hover:-translate-y-px hover:shadow-sm active:cursor-grabbing active:translate-y-0',
        tokens.classes.bg,
        tokens.classes.border,
        tokens.classes.text,
      )}
    >
      <span
        className={clsx(
          'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center',
          tokens.classes.icon,
        )}
      >
        <Icon size={14} aria-hidden="true" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{label}</span>
          {def.module && (
            <span
              className="shrink-0 rounded bg-black/5 px-1 text-2xs font-medium uppercase tracking-wide dark:bg-white/10"
              title={t('pipeline.palette.module_chip', {
                defaultValue: 'Touches the {{module}} module',
                module: def.module,
              })}
            >
              {def.module}
            </span>
          )}
          {def.side_effecting && (
            <span
              className="shrink-0 rounded bg-amber-200 px-1 text-2xs font-semibold text-amber-800 dark:bg-amber-800 dark:text-amber-100"
              title={t('pipeline.palette.writes_chip', {
                defaultValue: 'This step writes data - needs a gate before it',
              })}
            >
              {t('pipeline.palette.writes', { defaultValue: 'writes' })}
            </span>
          )}
        </span>
        {description && (
          <span className={clsx('truncate text-xs', tokens.classes.textSubtle)}>
            {description}
          </span>
        )}
      </span>
      {/* Drag affordance — signals the item is draggable (click also inserts) */}
      <GripVertical
        size={14}
        aria-hidden="true"
        className="mt-0.5 shrink-0 self-center text-content-tertiary opacity-0 transition-opacity group-hover:opacity-70"
      />
    </button>
  );
}

export function NodePalette({
  nodeTypes,
  loading = false,
  collapsed,
  onToggleCollapsed,
  testId,
}: NodePaletteProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');

  const byCategory = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const groups = new Map<string, NodeTypeDef[]>();
    for (const def of nodeTypes) {
      const label = (def.label ?? def.type).toLowerCase();
      const desc = (def.description ?? '').toLowerCase();
      if (
        normalized &&
        !label.includes(normalized) &&
        !desc.includes(normalized) &&
        !def.type.toLowerCase().includes(normalized)
      ) {
        continue;
      }
      const list = groups.get(def.category) ?? [];
      list.push(def);
      groups.set(def.category, list);
    }
    return groups;
  }, [nodeTypes, query]);

  if (collapsed) {
    return (
      <aside
        data-testid={testId ?? 'pipeline-palette'}
        data-collapsed="true"
        className="flex h-full w-11 shrink-0 flex-col items-center border-e border-border bg-surface-secondary py-2"
      >
        <button
          type="button"
          aria-label={t('pipeline.palette.expand', {
            defaultValue: 'Expand palette',
          })}
          onClick={onToggleCollapsed}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-tertiary"
        >
          <ChevronRight size={16} aria-hidden="true" className="rtl:scale-x-[-1]" />
        </button>
      </aside>
    );
  }

  const totalItems = Array.from(byCategory.values()).reduce(
    (s, l) => s + l.length,
    0,
  );

  return (
    <aside
      data-testid={testId ?? 'pipeline-palette'}
      data-collapsed="false"
      data-tour="pipeline-palette"
      className="flex h-full w-[260px] shrink-0 flex-col border-e border-border bg-surface-secondary"
      aria-label={t('pipeline.palette.aria', {
        defaultValue: 'Node palette',
      })}
    >
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('pipeline.palette.title', { defaultValue: 'Steps' })}
          {!loading && totalItems > 0 && (
            <span className="rounded bg-black/5 px-1 text-2xs font-medium tabular-nums text-content-tertiary dark:bg-white/10">
              {totalItems}
            </span>
          )}
        </span>
        <button
          type="button"
          aria-label={t('pipeline.palette.collapse', {
            defaultValue: 'Collapse palette',
          })}
          onClick={onToggleCollapsed}
          className="flex h-6 w-6 items-center justify-center rounded hover:bg-surface-tertiary"
        >
          <ChevronLeft size={14} aria-hidden="true" className="rtl:scale-x-[-1]" />
        </button>
      </header>
      <div className="px-3 pt-2">
        <label className="relative block">
          <span className="sr-only">
            {t('pipeline.palette.search', { defaultValue: 'Search steps' })}
          </span>
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute start-2 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('pipeline.palette.search_ph', {
              defaultValue: 'Search steps…',
            })}
            data-testid="pipeline-palette-search"
            className={clsx(
              'h-8 w-full rounded-lg border border-border bg-surface-primary ps-7 pe-7 text-sm',
              'placeholder:text-content-tertiary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
            )}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label={t('pipeline.palette.clear_search', {
                defaultValue: 'Clear search',
              })}
              data-testid="pipeline-palette-search-clear"
              className="absolute end-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-content-secondary"
            >
              <X size={13} aria-hidden="true" />
            </button>
          )}
        </label>
        <p className="mt-1.5 flex items-center gap-1.5 px-0.5 text-2xs text-content-tertiary">
          <MousePointerClick size={12} aria-hidden="true" className="shrink-0" />
          {t('pipeline.palette.drag_hint', {
            defaultValue: 'Drag onto the canvas, or click to add.',
          })}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <div className="space-y-2 px-1 pt-1">
            <Skeleton className="h-12 w-full rounded-md" />
            <Skeleton className="h-12 w-full rounded-md" />
            <Skeleton className="h-12 w-full rounded-md" />
          </div>
        ) : totalItems === 0 ? (
          <p
            data-testid="pipeline-palette-empty"
            className="px-2 py-4 text-center text-xs text-content-tertiary"
          >
            {query
              ? t('pipeline.palette.no_match', {
                  defaultValue: 'No steps match "{{query}}"',
                  query,
                })
              : t('pipeline.palette.none', {
                  defaultValue: 'No step types available.',
                })}
          </p>
        ) : (
          CATEGORY_ORDER.map((category) => {
            const items = byCategory.get(category);
            if (!items || items.length === 0) return null;
            const ctok = getCategoryTokens(category);
            const CatIcon = ctok.Icon;
            return (
              <section
                key={category}
                data-testid={`pipeline-palette-cat-${category}`}
                className="mt-3 first:mt-1"
              >
                <h3 className="mb-1 flex items-center gap-1.5 px-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  <span
                    className={clsx(
                      'flex h-4 w-4 items-center justify-center',
                      ctok.classes.icon,
                    )}
                  >
                    <CatIcon size={12} aria-hidden="true" />
                  </span>
                  <span className="truncate">
                    {t(ctok.labelKey, { defaultValue: ctok.labelDefault })}
                  </span>
                  <span className="ms-auto rounded bg-black/5 px-1 tabular-nums text-content-tertiary dark:bg-white/10">
                    {items.length}
                  </span>
                </h3>
                <div className="flex flex-col gap-1">
                  {items.map((def) => (
                    <PaletteItem key={def.type} def={def} />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </div>
      <PortLegend />
    </aside>
  );
}

export default NodePalette;
