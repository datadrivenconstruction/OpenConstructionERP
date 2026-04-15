import { useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, Link2, Hash, ExternalLink } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import type { BIMBOQLinkBrief } from '@/shared/ui/BIMViewer/ElementManager';

interface AggregatedPosition {
  boq_position_id: string;
  ordinal: string | null;
  description: string | null;
  quantity: number | null;
  unit: string | null;
  unit_rate: number | null;
  total: number | null;
  link_type: BIMBOQLinkBrief['link_type'];
  confidence: string | null;
  elementIds: string[];
}

interface BIMLinkedBOQPanelProps {
  elements: BIMElementData[];
  onHighlightElements: (ids: string[]) => void;
  onClose: () => void;
  boqId?: string | null;
}

export default function BIMLinkedBOQPanel({
  elements,
  onHighlightElements,
  onClose,
  boqId,
}: BIMLinkedBOQPanelProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [activePositionId, setActivePositionId] = useState<string | null>(null);

  const positions = useMemo(() => {
    const map = new Map<string, AggregatedPosition>();
    for (const el of elements) {
      if (!el.boq_links) continue;
      for (const link of el.boq_links) {
        const existing = map.get(link.boq_position_id);
        if (existing) {
          if (!existing.elementIds.includes(el.id)) {
            existing.elementIds.push(el.id);
          }
        } else {
          map.set(link.boq_position_id, {
            boq_position_id: link.boq_position_id,
            ordinal: link.boq_position_ordinal,
            description: link.boq_position_description,
            quantity: link.boq_position_quantity,
            unit: link.boq_position_unit,
            unit_rate: link.boq_position_unit_rate,
            total: link.boq_position_total,
            link_type: link.link_type,
            confidence: link.confidence,
            elementIds: [el.id],
          });
        }
      }
    }
    return Array.from(map.values()).sort((a, b) => {
      const oa = a.ordinal ?? '';
      const ob = b.ordinal ?? '';
      return oa.localeCompare(ob, undefined, { numeric: true });
    });
  }, [elements]);

  const filtered = useMemo(() => {
    if (!search.trim()) return positions;
    const q = search.trim().toLowerCase();
    return positions.filter(
      (p) =>
        (p.ordinal ?? '').toLowerCase().includes(q) ||
        (p.description ?? '').toLowerCase().includes(q),
    );
  }, [positions, search]);

  const totalLinkedElements = useMemo(() => {
    const ids = new Set<string>();
    for (const p of positions) {
      for (const id of p.elementIds) ids.add(id);
    }
    return ids.size;
  }, [positions]);

  const handleRowClick = useCallback(
    (pos: AggregatedPosition) => {
      const next = activePositionId === pos.boq_position_id ? null : pos.boq_position_id;
      setActivePositionId(next);
      onHighlightElements(next ? pos.elementIds : []);
    },
    [activePositionId, onHighlightElements],
  );

  return (
    <div
      className="h-full flex flex-col bg-surface-primary border-s border-border-light"
      style={{ width: 320, minWidth: 320 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light shrink-0">
        <div className="flex items-center gap-2">
          <Link2 size={16} className="text-content-tertiary" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bim.linked_boq_title', { defaultValue: 'Linked BOQ' })}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
        >
          <X size={14} />
        </button>
      </div>

      {/* Search */}
      <div className="px-4 py-3 border-b border-border-light shrink-0">
        <div className="relative">
          <Search size={14} className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('bim.linked_boq_search', { defaultValue: 'Search positions...' })}
            className="w-full ps-8 pe-8 py-1.5 text-xs rounded-md bg-surface-secondary border border-border-light focus:outline-none focus:ring-1 focus:ring-oe-blue focus:border-oe-blue"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute end-2 top-1/2 -translate-y-1/2 text-content-quaternary hover:text-content-secondary"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Summary */}
        <div className="mt-2 px-2.5 py-1.5 rounded-md bg-oe-blue/5 border border-oe-blue/15 text-[11px] font-medium text-oe-blue">
          {t('bim.linked_boq_summary', {
            defaultValue: '{{positions}} positions linked to {{elements}} elements',
            positions: positions.length,
            elements: totalLinkedElements,
          })}
        </div>
      </div>

      {/* Position list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-content-quaternary">
            <Link2 size={24} className="mb-2 opacity-40" />
            <p className="text-xs">
              {positions.length === 0
                ? t('bim.linked_boq_empty', { defaultValue: 'No linked BOQ positions' })
                : t('bim.linked_boq_no_match', { defaultValue: 'No matching positions' })}
            </p>
          </div>
        ) : (
          filtered.map((pos) => {
            const isActive = activePositionId === pos.boq_position_id;
            return (
              <button
                key={pos.boq_position_id}
                type="button"
                onClick={() => handleRowClick(pos)}
                className={`w-full text-start px-4 py-2.5 border-b border-border-light transition-colors ${
                  isActive
                    ? 'bg-oe-blue/8 border-s-2 border-s-oe-blue'
                    : 'hover:bg-surface-secondary border-s-2 border-s-transparent'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    {pos.ordinal && (
                      <div className="flex items-center gap-1 mb-0.5">
                        <Hash size={10} className="text-content-quaternary shrink-0" />
                        <span className="text-[11px] font-bold text-content-primary tabular-nums">
                          {pos.ordinal}
                        </span>
                        <span
                          className={`inline-flex items-center justify-center min-w-[18px] h-[14px] px-0.5 rounded text-[8px] font-bold tabular-nums ${
                            isActive
                              ? 'bg-oe-blue text-white'
                              : 'bg-surface-secondary text-content-tertiary'
                          }`}
                        >
                          {pos.elementIds.length}
                        </span>
                      </div>
                    )}
                    <p className="text-[11px] text-content-secondary truncate">
                      {pos.description || t('bim.linked_boq_no_desc', { defaultValue: '(no description)' })}
                    </p>
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      {pos.quantity != null && (
                        <span className="text-[10px] tabular-nums font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30 px-1.5 py-0.5 rounded">
                          {pos.quantity.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                          {pos.unit ? ` ${pos.unit}` : ''}
                        </span>
                      )}
                      {pos.total != null && (
                        <span className="text-[10px] tabular-nums font-medium text-content-primary bg-surface-secondary px-1.5 py-0.5 rounded">
                          {pos.total.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                      )}
                      {boqId && (
                        <a
                          href={`/boq/${boqId}?highlight=${pos.boq_position_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="text-[9px] text-oe-blue hover:text-oe-blue/80 flex items-center gap-0.5"
                          title="Open in BOQ"
                        >
                          <ExternalLink size={8} />
                          BOQ
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
