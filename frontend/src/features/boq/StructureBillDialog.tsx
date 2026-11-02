// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Structure the bill: set a level per row (position or section 1..6) and the
 * server rebuilds the tree in one step. Levels are suggested from the
 * numbering and from title lines.
 */

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ListTree, Wand2, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { boqApi, type Position } from './api';
import { currentLevels, documentOrder, suggestLevels } from './boqStructure';
import { LevelSelect } from './ExcelPasteModal';

interface StructureBillDialogProps {
  open: boolean;
  boqId: string;
  positions: Position[];
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}

export function StructureBillDialog({ open, boqId, positions, onClose, onDone, onError }: StructureBillDialogProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panelRef, open);
  const ordered = useMemo(() => documentOrder(positions), [positions]);
  const [levels, setLevels] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setLevels(currentLevels(ordered));
  }, [open, ordered]);

  if (!open) return null;

  const changed = levels.some((l, i) => l !== currentLevels(ordered)[i]);

  const apply = async () => {
    setSaving(true);
    try {
      const res = await boqApi.restructurePositions(
        boqId,
        ordered.map((p, i) => ({ position_id: p.id, level: levels[i] ?? 0 })),
      );
      onDone(
        t('boq.structure_done', {
          defaultValue: 'Sections: {{sections}}. Positions: {{positions}}',
          sections: res.sections,
          positions: res.positions,
        }),
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-3xl mx-4 bg-surface-primary rounded-2xl shadow-2xl border border-border-light overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <ListTree size={18} className="text-oe-blue" />
            <div>
              <h2 id={titleId} className="text-base font-semibold">
                {t('boq.structure_title', { defaultValue: 'Structure the bill' })}
              </h2>
              <p className="text-xs text-content-secondary">
                {t('boq.structure_hint', {
                  defaultValue:
                    'Set each row as a position or a section level. A section holds the rows below it until the next section of the same or a higher level.',
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="p-1.5 rounded-lg hover:bg-surface-secondary"
          >
            <X size={18} className="text-content-tertiary" />
          </button>
        </div>

        <div className="p-6 space-y-3">
          <Button variant="secondary" size="sm" icon={<Wand2 size={14} />} onClick={() => setLevels(suggestLevels(ordered))}>
            {t('boq.structure_suggest', { defaultValue: 'Suggest from numbering' })}
          </Button>
          <div className="rounded-xl border border-border-light overflow-auto max-h-[55vh]">
            <table className="w-full text-xs">
              <tbody className="divide-y divide-border-light">
                {ordered.map((p, i) => {
                  const level = levels[i] ?? 0;
                  return (
                    <tr key={p.id}>
                      <td className="px-3 py-1.5 w-28">
                        <LevelSelect
                          value={level}
                          onChange={(v) => setLevels((prev) => prev.map((l, j) => (j === i ? v : l)))}
                        />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-content-tertiary whitespace-nowrap">{p.ordinal}</td>
                      <td
                        className={`py-1.5 pr-3 max-w-[420px] truncate ${level > 0 ? 'font-semibold' : ''}`}
                        style={{ paddingLeft: `${0.75 + Math.max(level - 1, 0) * 0.75}rem` }}
                      >
                        {p.description}
                      </td>
                      <td className="px-3 py-1.5 text-content-tertiary">{level > 0 ? '' : p.unit}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-content-tertiary">
            {t('boq.structure_convert_note', {
              defaultValue:
                'A position that becomes a section keeps its quantity and rate aside, and gets them back if you make it a position again.',
            })}
          </p>
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border-light bg-surface-secondary/30">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="sm" onClick={apply} disabled={!changed || saving} loading={saving}>
            {t('boq.structure_apply', { defaultValue: 'Apply structure' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
