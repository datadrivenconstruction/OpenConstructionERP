// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CostCategoryTree — recursive sidebar tree for the Cost Database modal.
 *
 * Each node renders a chevron + name + count badge.  Click selects (and emits
 * a slash-joined path); the chevron toggles expansion independently so the
 * user can drill down without committing a selection at the parent level.
 *
 * Search-within-tree filters node names recursively: when a deep node matches,
 * its ancestors stay visible so the user can see context.  Filtered ancestors
 * auto-expand for the duration of the filter so the match is reachable.
 *
 * Sentinel handling: backend emits ``__unspecified__`` when a classification
 * segment is NULL/empty.  We render the sentinel as ``(Not specified)`` via
 * the ``boq.uncategorized`` i18n key — the underlying path stays the sentinel
 * so the backend filter still resolves cleanly.
 *
 * A sentinel that is its parent's ONLY child is not rendered at all: it holds
 * every row the parent holds, so it is a click that changes nothing.  Its
 * children are drawn one level up instead, and the sentinel remains in their
 * path so each segment still lines up with the classification depth the
 * backend filters on.
 */
import { useMemo, useState, type KeyboardEvent } from 'react';
import { ChevronRight, ChevronDown, Search } from 'lucide-react';
import type { TFunction } from 'i18next';
import type { CategoryTreeNode } from './api';
import { getNumberLocale } from '@/stores/usePreferencesStore';

const UNSPECIFIED_SENTINEL = '__unspecified__';

export interface CostCategoryTreeProps {
  tree: CategoryTreeNode[];
  selectedPath: string;
  onSelect: (path: string) => void;
  /** Translation function — usually `useTranslation().t` from the parent. */
  t: TFunction;
  /** Optional ID for the search input (a11y label association). */
  searchInputId?: string;
  /** When true (and tree is still empty), render skeleton rows + a
   *  "Loading categories…" hint instead of the "No categories available"
   *  empty-state. The /costs sidebar fires a 5-min cached query that can
   *  take a moment on cold catalogues; without this flag the empty-state
   *  flashes for the entire wait, which reads as a real error. */
  isLoading?: boolean;
}

/* ── Pure helpers ──────────────────────────────────────────────────────── */

/** Lower-case haystack for fuzzy matching. */
function matches(needle: string, hay: string): boolean {
  if (!needle) return true;
  return hay.toLowerCase().includes(needle.toLowerCase());
}

/**
 * Recursively determine whether a node OR any of its descendants matches the
 * filter.  Used to keep ancestor nodes visible when a deep child matches.
 */
function nodeMatchesDeep(node: CategoryTreeNode, filter: string): boolean {
  if (!filter) return true;
  if (matches(filter, node.name)) return true;
  return node.children.some((c) => nodeMatchesDeep(c, filter));
}

/* ── Recursive node row ────────────────────────────────────────────────── */

interface TreeNodeRowProps {
  node: CategoryTreeNode;
  parentPath: string;
  depth: number;
  selectedPath: string;
  onSelect: (path: string) => void;
  expanded: Set<string>;
  setExpanded: (next: Set<string>) => void;
  filter: string;
  t: TFunction;
}

function TreeNodeRow({
  node,
  parentPath,
  depth,
  selectedPath,
  onSelect,
  expanded,
  setExpanded,
  filter,
  t,
}: TreeNodeRowProps) {
  const path = parentPath ? `${parentPath}/${node.name}` : node.name;
  const isSelected = path === selectedPath;

  // A level whose only child is the sentinel holds every row its parent holds,
  // so expanding it shows one row with the same count and costs a click that
  // tells the user nothing. Measured on the shipped catalogue: 129 such nodes
  // standing in front of 14967 rows, including every one of the five
  // top-level categories, because this data has no department level at all.
  //
  // The grandchildren are rendered here instead. The sentinel stays in their
  // path, so the backend still receives a segment for the depth it skipped and
  // the slash-joined path keeps lining up with the depth it filters on -
  // dropping it from the path would shift every deeper segment up one level.
  const onlyChild = node.children.length === 1 ? node.children[0] : undefined;
  const skipsSentinel =
    onlyChild?.name === UNSPECIFIED_SENTINEL && onlyChild.children.length > 0;
  const childNodes = skipsSentinel && onlyChild ? onlyChild.children : node.children;
  const childParentPath = skipsSentinel ? `${path}/${UNSPECIFIED_SENTINEL}` : path;
  const hasChildren = childNodes.length > 0;

  // While filtering, force ancestors of matches open so the path is visible.
  const childMatches = filter
    ? childNodes.some((c) => nodeMatchesDeep(c, filter))
    : false;
  const isExpanded = expanded.has(path) || (filter ? childMatches : false);

  // Hide nodes that neither match nor have a matching descendant.
  if (!nodeMatchesDeep(node, filter)) return null;

  const displayName =
    node.name === UNSPECIFIED_SENTINEL
      ? t('boq.uncategorized', { defaultValue: '(Not specified)' })
      : node.name;

  function toggleExpand(e: React.MouseEvent | KeyboardEvent) {
    e.stopPropagation();
    const next = new Set(expanded);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setExpanded(next);
  }

  function handleSelect() {
    onSelect(path);
    // Auto-expand on first click so the user immediately sees children.
    if (hasChildren && !expanded.has(path)) {
      const next = new Set(expanded);
      next.add(path);
      setExpanded(next);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleSelect();
    } else if (e.key === 'ArrowRight' && hasChildren && !isExpanded) {
      e.preventDefault();
      toggleExpand(e);
    } else if (e.key === 'ArrowLeft' && isExpanded) {
      e.preventDefault();
      toggleExpand(e);
    }
  }

  return (
    <>
      <div
        role="treeitem"
        tabIndex={0}
        aria-selected={isSelected}
        aria-expanded={hasChildren ? isExpanded : undefined}
        onClick={handleSelect}
        onKeyDown={handleKeyDown}
        className={`group flex items-center gap-1 rounded-md py-1 pr-2 text-xs transition-colors cursor-pointer ${
          isSelected
            ? 'bg-oe-blue text-white'
            : 'text-content-secondary hover:bg-surface-secondary'
        }`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
      >
        <button
          type="button"
          onClick={toggleExpand}
          aria-label={
            isExpanded
              ? t('common.collapse', { defaultValue: 'Collapse' })
              : t('common.expand', { defaultValue: 'Expand' })
          }
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded ${
            hasChildren
              ? isSelected
                ? 'text-white/80 hover:text-white'
                : 'text-content-tertiary hover:text-content-primary'
              : 'invisible'
          }`}
          tabIndex={-1}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )
          ) : null}
        </button>
        {/* Two-line clamp instead of a single-line ellipsis: German category
            names (Abdichtungsarbeiten in Wasserbauwerken ...) clipped so hard
            the list was unreadable. The title keeps the full text on hover. */}
        <span className="flex-1 min-w-0 line-clamp-2 break-words leading-snug" title={displayName}>
          {displayName}
        </span>
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${
            isSelected
              ? 'bg-white/20 text-white'
              : 'bg-surface-tertiary text-content-tertiary group-hover:bg-surface-primary'
          }`}
        >
          {node.count.toLocaleString(getNumberLocale())}
        </span>
      </div>
      {isExpanded &&
        childNodes.map((child) => (
          <TreeNodeRow
            key={`${childParentPath}/${child.name}`}
            node={child}
            parentPath={childParentPath}
            depth={depth + 1}
            selectedPath={selectedPath}
            onSelect={onSelect}
            expanded={expanded}
            setExpanded={setExpanded}
            filter={filter}
            t={t}
          />
        ))}
    </>
  );
}

/* ── Public component ─────────────────────────────────────────────────── */

export function CostCategoryTree({
  tree,
  selectedPath,
  onSelect,
  t,
  searchInputId,
  isLoading = false,
}: CostCategoryTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [filter, setFilter] = useState('');

  const visibleTree = useMemo(() => tree, [tree]);

  return (
    <div className="flex h-full flex-col" data-testid="cost-category-tree">
      {/* Search-within-tree */}
      <div className="px-3 pt-3 pb-2">
        <div className="relative">
          <Search
            size={12}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-content-quaternary"
          />
          <input
            id={searchInputId}
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('boq.cost_tree_search_placeholder', {
              defaultValue: 'Filter categories...',
            })}
            aria-label={t('boq.cost_tree_search_placeholder', {
              defaultValue: 'Filter categories...',
            })}
            className="h-7 w-full rounded-md border border-border-light bg-surface-primary pl-7 pr-2 text-xs text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
        </div>
      </div>

      {/* "All categories" reset row */}
      <div className="px-2 pb-1">
        <button
          type="button"
          onClick={() => onSelect('')}
          className={`flex w-full items-center justify-between rounded-md px-2 py-1 text-xs transition-colors ${
            selectedPath === ''
              ? 'bg-oe-blue text-white'
              : 'text-content-secondary hover:bg-surface-secondary'
          }`}
        >
          <span className="font-medium">
            {t('boq.cost_tree_all_categories', { defaultValue: 'All categories' })}
          </span>
        </button>
      </div>

      {/* Tree */}
      <div role="tree" className="flex-1 overflow-y-auto px-1 pb-3" aria-busy={isLoading}>
        {isLoading && visibleTree.length === 0 ? (
          <div
            className="flex flex-col gap-1.5 px-2 pt-1"
            aria-label={t('boq.cost_tree_loading', { defaultValue: 'Loading categories…' })}
          >
            {/* Skeleton rows mimic real category density (varied widths so
                the placeholder reads as content, not a single block). The
                shimmer animation comes from Tailwind `animate-pulse`. */}
            {[88, 72, 95, 60, 80, 70, 92, 55, 78, 65].map((w, i) => (
              <div
                key={i}
                className="flex items-center gap-2 px-2 py-1.5"
                style={{ paddingLeft: `${(i % 3) * 8 + 8}px` }}
              >
                <div className="h-2.5 w-2.5 rounded-sm bg-surface-secondary animate-pulse" />
                <div
                  className="h-2.5 rounded bg-surface-secondary animate-pulse"
                  style={{ width: `${w}%` }}
                />
              </div>
            ))}
            <p className="mt-3 px-3 text-center text-2xs text-content-quaternary">
              {t('boq.cost_tree_loading', { defaultValue: 'Loading categories…' })}
            </p>
          </div>
        ) : visibleTree.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-content-tertiary">
            {t('boq.cost_tree_no_categories', {
              defaultValue: 'No categories available',
            })}
          </p>
        ) : (
          visibleTree.map((node) => (
            <TreeNodeRow
              key={node.name}
              node={node}
              parentPath=""
              depth={0}
              selectedPath={selectedPath}
              onSelect={onSelect}
              expanded={expanded}
              setExpanded={setExpanded}
              filter={filter}
              t={t}
            />
          ))
        )}
      </div>
    </div>
  );
}
