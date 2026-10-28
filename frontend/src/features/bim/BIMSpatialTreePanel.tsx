// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMSpatialTreePanel - the IFC spatial structure browser (B3).
 *
 * A collapsible tree of the model the way a modeller thinks about it:
 *
 *     Storey  ->  Element type  ->  individual element
 *
 * Storey is the spatial container every IFC / RVT export carries, so this
 * works without any extra backend call - it is built entirely from the
 * element list the viewer already loaded. Clicking a storey or type node
 * highlights every element under it in the 3D view; clicking a leaf selects
 * (and frames) that single element. A search box filters the leaves by name,
 * type, or storey and auto-expands the matches.
 *
 * Performance: the tree is grouped in one O(n) pass and leaves are only
 * rendered when their type node is expanded, capped per type, so even a
 * 50k-element model stays responsive.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, ChevronDown, Layers3, Box, Search, Crosshair } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';

interface BIMSpatialTreePanelProps {
  elements: BIMElementData[];
  /** The single selected element, highlighted in the tree. */
  selectedElementId?: string | null;
  /** Select (and frame) one element in the viewer. */
  onSelectElement: (id: string) => void;
  /** Highlight a set of elements (a whole storey or type) in the viewer. */
  onHighlightElements: (ids: string[]) => void;
}

const UNASSIGNED = '—'; // em-dash placeholder rendered for a null storey

/** Max leaves rendered under one expanded type node - guards the DOM on huge
 *  models. The remainder is summarised with a "+N more" row. */
const LEAF_CAP = 400;

interface LeafNode {
  id: string;
  label: string;
  elementType: string;
}
interface TypeNode {
  key: string;
  label: string;
  ids: string[];
  leaves: LeafNode[];
}
interface StoreyNode {
  key: string;
  label: string;
  ids: string[];
  types: TypeNode[];
}

function leafLabel(el: BIMElementData): string {
  return (el.name && el.name.trim()) || el.element_type || el.id;
}

/** Group the flat element list into storey -> type -> element. */
function buildTree(elements: BIMElementData[]): StoreyNode[] {
  const storeys = new Map<string, Map<string, LeafNode[]>>();
  for (const el of elements) {
    const storeyKey = (el.storey && el.storey.trim()) || '';
    const typeKey = (el.element_type && el.element_type.trim()) || '';
    let byType = storeys.get(storeyKey);
    if (!byType) {
      byType = new Map();
      storeys.set(storeyKey, byType);
    }
    let leaves = byType.get(typeKey);
    if (!leaves) {
      leaves = [];
      byType.set(typeKey, leaves);
    }
    leaves.push({ id: el.id, label: leafLabel(el), elementType: typeKey });
  }

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  const storeyNodes: StoreyNode[] = [];
  for (const [storeyKey, byType] of storeys) {
    const typeNodes: TypeNode[] = [];
    const storeyIds: string[] = [];
    for (const [typeKey, leaves] of byType) {
      leaves.sort((a, b) => collator.compare(a.label, b.label));
      const ids = leaves.map((l) => l.id);
      storeyIds.push(...ids);
      typeNodes.push({
        key: typeKey,
        label: typeKey || UNASSIGNED,
        ids,
        leaves,
      });
    }
    typeNodes.sort((a, b) => collator.compare(a.label, b.label));
    storeyNodes.push({
      key: storeyKey,
      label: storeyKey || UNASSIGNED,
      ids: storeyIds,
      types: typeNodes,
    });
  }
  // Real storeys first (natural sort), the "unassigned" bucket always last.
  storeyNodes.sort((a, b) => {
    if (a.key === '' && b.key !== '') return 1;
    if (b.key === '' && a.key !== '') return -1;
    return collator.compare(a.label, b.label);
  });
  return storeyNodes;
}

export default function BIMSpatialTreePanel({
  elements,
  selectedElementId,
  onSelectElement,
  onHighlightElements,
}: BIMSpatialTreePanelProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const q = query.trim().toLowerCase();

  // Filter the element list first, then group - so a search prunes whole
  // empty branches instead of showing them.
  const filtered = useMemo(() => {
    if (!q) return elements;
    return elements.filter((el) => {
      const hay = `${el.name ?? ''} ${el.element_type ?? ''} ${el.storey ?? ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [elements, q]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // When searching, every node is open so matches are visible without manual
  // expansion; otherwise honour the user's expand/collapse choices.
  const isOpen = (key: string) => (q ? true : expanded.has(key));

  if (elements.length === 0) {
    return (
      <div className="p-3 text-[11px] text-content-tertiary italic" data-testid="bim-structure-empty">
        {t('bim.structure.empty', {
          defaultValue: 'No elements to show. Load a model with element data to browse its structure.',
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-2" data-testid="bim-structure-panel">
      <div className="flex items-center gap-1.5 px-1">
        <Search size={12} className="text-content-tertiary shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('bim.structure.search_placeholder', {
            defaultValue: 'Find element, type or storey...',
          })}
          className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          data-testid="bim-structure-search"
        />
      </div>

      {tree.length === 0 ? (
        <p className="px-2 text-[11px] text-content-tertiary italic">
          {t('bim.structure.no_matches', { defaultValue: 'No elements match your search.' })}
        </p>
      ) : (
        <ul className="flex flex-col" data-testid="bim-structure-tree">
          {tree.map((storey) => {
            const storeyKey = `s:${storey.key}`;
            const open = isOpen(storeyKey);
            return (
              <li key={storeyKey}>
                <div className="flex items-center gap-1 rounded hover:bg-surface-tertiary">
                  <button
                    type="button"
                    onClick={() => toggle(storeyKey)}
                    aria-expanded={open}
                    aria-label={open ? t('common.collapse', { defaultValue: 'Collapse' }) : t('common.expand', { defaultValue: 'Expand' })}
                    className="inline-flex h-5 w-5 items-center justify-center text-content-tertiary shrink-0"
                  >
                    {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => onHighlightElements(storey.ids)}
                    className="flex flex-1 min-w-0 items-center gap-1.5 py-1 text-left text-[11px] font-medium text-content-primary"
                    title={t('bim.structure.highlight_storey', { defaultValue: 'Highlight this storey' })}
                  >
                    <Layers3 size={12} className="text-oe-blue shrink-0" />
                    <span className="truncate">{storey.label}</span>
                    <span className="ms-auto shrink-0 rounded bg-surface-tertiary px-1 text-[9px] tabular-nums text-content-tertiary">
                      {storey.ids.length}
                    </span>
                  </button>
                </div>

                {open && (
                  <ul className="ms-4 border-s border-border-light ps-1">
                    {storey.types.map((type) => {
                      const typeKey = `${storeyKey}|t:${type.key}`;
                      const typeOpen = isOpen(typeKey);
                      return (
                        <li key={typeKey}>
                          <div className="flex items-center gap-1 rounded hover:bg-surface-tertiary">
                            <button
                              type="button"
                              onClick={() => toggle(typeKey)}
                              aria-expanded={typeOpen}
                              aria-label={typeOpen ? t('common.collapse', { defaultValue: 'Collapse' }) : t('common.expand', { defaultValue: 'Expand' })}
                              className="inline-flex h-5 w-5 items-center justify-center text-content-tertiary shrink-0"
                            >
                              {typeOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                            </button>
                            <button
                              type="button"
                              onClick={() => onHighlightElements(type.ids)}
                              className="flex flex-1 min-w-0 items-center gap-1.5 py-1 text-left text-[11px] text-content-secondary"
                              title={t('bim.structure.highlight_type', { defaultValue: 'Highlight all of this type' })}
                            >
                              <Box size={11} className="text-content-tertiary shrink-0" />
                              <span className="truncate">{type.label}</span>
                              <span className="ms-auto shrink-0 rounded bg-surface-tertiary px-1 text-[9px] tabular-nums text-content-tertiary">
                                {type.ids.length}
                              </span>
                            </button>
                          </div>

                          {typeOpen && (
                            <ul className="ms-4 border-s border-border-light ps-1">
                              {type.leaves.slice(0, LEAF_CAP).map((leaf) => {
                                const active = leaf.id === selectedElementId;
                                return (
                                  <li key={leaf.id}>
                                    <button
                                      type="button"
                                      onClick={() => onSelectElement(leaf.id)}
                                      data-testid="bim-structure-leaf"
                                      className={`flex w-full min-w-0 items-center gap-1.5 rounded px-1 py-0.5 text-left text-[11px] ${
                                        active
                                          ? 'bg-oe-blue/10 text-oe-blue'
                                          : 'text-content-secondary hover:bg-surface-tertiary'
                                      }`}
                                    >
                                      <Crosshair size={10} className="shrink-0 opacity-60" />
                                      <span className="truncate">{leaf.label}</span>
                                    </button>
                                  </li>
                                );
                              })}
                              {type.leaves.length > LEAF_CAP && (
                                <li className="px-1 py-0.5 text-[10px] italic text-content-tertiary">
                                  {t('bim.structure.more_elements', {
                                    defaultValue: '+{{count}} more (refine the search to see them)',
                                    count: type.leaves.length - LEAF_CAP,
                                  })}
                                </li>
                              )}
                            </ul>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
