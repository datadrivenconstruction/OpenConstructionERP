// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ClassificationPicker - browse and pick a code of a code list.
//
// The codes come from the code-list API, the same lists a cost structure is
// built from (shipped standards, pack lists and a project's own uploads), so
// a code picked here is one the structure knows. Titles are data and are
// shown as the list carries them; only the picker's own chrome is translated.

import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight, ChevronDown, Search, X, Tag } from 'lucide-react';
import clsx from 'clsx';

import { costStructureApi, type CodeListEntry } from '@/features/costmodel/structureApi';

interface ClassificationNode {
  code: string;
  label: string;
  children?: ClassificationNode[];
}

/** Nest the flat, tree-ordered entries of a list under their parents. */
export function buildClassificationTree(entries: readonly CodeListEntry[]): ClassificationNode[] {
  const byCode = new Map<string, ClassificationNode>();
  for (const e of entries) byCode.set(e.code, { code: e.code, label: e.title });
  const roots: ClassificationNode[] = [];
  for (const e of entries) {
    const node = byCode.get(e.code)!;
    const parent = e.parent && e.parent !== e.code ? byCode.get(e.parent) : undefined;
    if (parent) (parent.children ??= []).push(node);
    else roots.push(node);
  }
  return roots;
}

/* ── Flatten for search ───────────────────────────────────────────────── */

function flattenTree(nodes: ClassificationNode[], parentPath = ''): Array<{ code: string; label: string; path: string }> {
  const result: Array<{ code: string; label: string; path: string }> = [];
  for (const node of nodes) {
    const path = parentPath ? `${parentPath} > ${node.code}` : node.code;
    result.push({ code: node.code, label: node.label, path });
    if (node.children) {
      result.push(...flattenTree(node.children, path));
    }
  }
  return result;
}

/* ── TreeNode component ───────────────────────────────────────────────── */

function TreeNode({
  node,
  depth,
  onSelect,
  selectedCode,
  expandedCodes,
  onToggle,
}: {
  node: ClassificationNode;
  depth: number;
  onSelect: (code: string, label: string) => void;
  selectedCode: string | null;
  expandedCodes: Set<string>;
  onToggle: (code: string) => void;
}) {
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedCodes.has(node.code);
  const isSelected = selectedCode === node.code;

  return (
    <>
      <button
        type="button"
        aria-expanded={hasChildren ? isExpanded : undefined}
        onClick={() => {
          if (hasChildren) onToggle(node.code);
          onSelect(node.code, node.label);
        }}
        className={clsx(
          'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-start text-xs transition-colors',
          isSelected
            ? 'bg-oe-blue/10 text-oe-blue font-medium'
            : 'text-content-primary hover:bg-surface-secondary',
        )}
        style={{ paddingInlineStart: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <span className="shrink-0 w-4 h-4 flex items-center justify-center text-content-tertiary">
            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} className="rtl:rotate-180" />}
          </span>
        ) : (
          <span className="shrink-0 w-4" />
        )}
        <span className="shrink-0 font-mono text-2xs text-content-tertiary w-8">{node.code}</span>
        <span className="truncate">{node.label}</span>
      </button>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.code}
          node={child}
          depth={depth + 1}
          onSelect={onSelect}
          selectedCode={selectedCode}
          expandedCodes={expandedCodes}
          onToggle={onToggle}
        />
      ))}
    </>
  );
}

/* ── Main ClassificationPicker component ──────────────────────────────── */

/**
 * Key of a code list. The shipped standards are `din276`, `nrm`,
 * `masterformat`, `uniformat`, `sinapi` and `gb50500`; packs and projects add
 * their own keys.
 */
export type ClassificationStandard = string;

interface ClassificationPickerProps {
  /** Key of the code list to browse */
  standard?: ClassificationStandard;
  /** Project whose own code lists are visible as well */
  projectId?: string;
  /** Currently selected code */
  value?: string | null;
  /** Called when user picks a code */
  onSelect: (code: string, label: string) => void;
  /** Optional: render as dropdown vs inline */
  mode?: 'dropdown' | 'inline';
  className?: string;
}

const EMPTY_TREE: ClassificationNode[] = [];

export function ClassificationPicker({
  standard = 'din276',
  projectId,
  value = null,
  onSelect,
  mode = 'dropdown',
  className,
}: ClassificationPickerProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(mode === 'inline');
  const [search, setSearch] = useState('');
  const [expandedCodes, setExpandedCodes] = useState<Set<string>>(new Set());
  const dropdownRef = useRef<HTMLDivElement>(null);

  const listQuery = useQuery({
    queryKey: ['code-list', standard, projectId ?? null],
    queryFn: () => costStructureApi.getCodeList(standard, projectId),
    enabled: Boolean(standard),
    staleTime: 10 * 60 * 1000,
  });
  const entries = listQuery.data?.entries;
  const tree = useMemo(() => (entries ? buildClassificationTree(entries) : EMPTY_TREE), [entries]);
  const flatItems = useMemo(() => flattenTree(tree), [tree]);

  // Filter by search
  const filteredItems = useMemo(() => {
    if (!search.trim()) return null; // Show tree view
    const q = search.toLowerCase();
    return flatItems.filter(
      (item) => item.code.toLowerCase().includes(q) || item.label.toLowerCase().includes(q),
    );
  }, [search, flatItems]);

  // Close on outside click
  useEffect(() => {
    if (mode !== 'dropdown' || !isOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, mode]);

  const handleToggle = useCallback((code: string) => {
    setExpandedCodes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const handleSelect = useCallback(
    (code: string, label: string) => {
      onSelect(code, label);
      if (mode === 'dropdown') setIsOpen(false);
    },
    [onSelect, mode],
  );

  const selectedLabel = value ? flatItems.find((i) => i.code === value)?.label : null;

  // Dropdown trigger button
  const trigger = mode === 'dropdown' && (
    <button
      type="button"
      aria-expanded={isOpen}
      onClick={() => setIsOpen((prev) => !prev)}
      className={clsx(
        'flex items-center gap-1.5 h-7 rounded-md border border-border px-2 text-xs transition-colors',
        'hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
        value ? 'text-content-primary' : 'text-content-tertiary',
        className,
      )}
    >
      <Tag size={11} className="shrink-0 text-content-tertiary" />
      {value ? (
        <span className="truncate max-w-[180px]">
          <span className="font-mono">{value}</span>
          {selectedLabel && <span className="ms-1 text-content-tertiary">– {(selectedLabel.split('/')[0] ?? '').trim()}</span>}
        </span>
      ) : (
        <span>{t('boq.select_classification', { defaultValue: 'Classification...' })}</span>
      )}
    </button>
  );

  let body: React.ReactNode;
  if (listQuery.isLoading) {
    body = (
      <div className="py-6 text-center text-xs text-content-tertiary" role="status">
        {t('boq.classification_loading', { defaultValue: 'Loading codes...' })}
      </div>
    );
  } else if (listQuery.isError) {
    body = (
      <div className="py-6 px-3 text-center text-xs text-semantic-error" role="alert">
        {t('boq.classification_load_failed', { defaultValue: 'The code list could not be loaded.' })}
      </div>
    );
  } else if (filteredItems) {
    // Search results — flat list
    body = filteredItems.length > 0 ? (
      filteredItems.map((item) => (
        <button
          type="button"
          key={item.code}
          onClick={() => handleSelect(item.code, item.label)}
          className={clsx(
            'flex w-full items-center gap-2 rounded-md px-2 py-1 text-start text-xs transition-colors',
            value === item.code
              ? 'bg-oe-blue/10 text-oe-blue font-medium'
              : 'text-content-primary hover:bg-surface-secondary',
          )}
        >
          <span className="shrink-0 font-mono text-2xs text-content-tertiary w-8">{item.code}</span>
          <span className="truncate">{item.label}</span>
        </button>
      ))
    ) : (
      <div className="py-6 text-center text-xs text-content-tertiary">
        {t('common.no_results', { defaultValue: 'No results found' })}
      </div>
    );
  } else if (tree.length === 0) {
    body = (
      <div className="py-6 text-center text-xs text-content-tertiary">
        {t('boq.classification_empty', { defaultValue: 'This code list has no codes.' })}
      </div>
    );
  } else {
    // Tree view
    body = tree.map((node) => (
      <TreeNode
        key={node.code}
        node={node}
        depth={0}
        onSelect={handleSelect}
        selectedCode={value}
        expandedCodes={expandedCodes}
        onToggle={handleToggle}
      />
    ));
  }

  const panel = (
    <div
      className={clsx(
        'flex flex-col bg-surface-elevated border border-border-light shadow-lg rounded-lg overflow-hidden',
        mode === 'dropdown' ? 'absolute start-0 top-full mt-1 z-50 w-72 max-h-80' : 'w-full h-full',
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border-light p-2">
        <div className="flex items-center gap-1.5 flex-1 rounded-md bg-surface-secondary px-2 py-1">
          <Search size={12} className="text-content-tertiary shrink-0" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search', { defaultValue: 'Search...' })}
            aria-label={t('common.search', { defaultValue: 'Search...' })}
            className="flex-1 bg-transparent border-none outline-none text-xs text-content-primary placeholder:text-content-tertiary"
            autoFocus={mode === 'dropdown'}
          />
          {search && (
            <button type="button" aria-label={t('common.clear_search', { defaultValue: 'Clear search' })} onClick={() => setSearch('')} className="text-content-tertiary hover:text-content-primary">
              <X size={11} />
            </button>
          )}
        </div>
        <span
          className="text-2xs font-medium text-content-tertiary uppercase"
          title={listQuery.data?.name}
        >
          {standard.toUpperCase()}
        </span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-1">{body}</div>
    </div>
  );

  if (mode === 'inline') return panel;

  return (
    <div ref={dropdownRef} className="relative">
      {trigger}
      {isOpen && panel}
    </div>
  );
}
