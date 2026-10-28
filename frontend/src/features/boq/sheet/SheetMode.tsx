// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet mode wiring for the BOQ editor: the toggle, the write through the
 * sheet-edit endpoint and the validation verdict it returns. On a touch
 * screen the toggle is not offered and the editor keeps its usual grid.
 */

import { useCallback, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Table2 } from 'lucide-react';
import { boqApi, type BOQVariable, type Position } from '../api';
import type { PastedRow } from '../ExcelPasteModal';
import { useToastStore } from '@/stores/useToastStore';
import { BOQSheetView, type SheetCellIssue } from './BOQSheetView';
import type { SheetCellEdit } from './commit';

const STORAGE_KEY = 'oe.boq.sheetMode';

function coarsePointer(): boolean {
  try {
    return typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches === true;
  } catch {
    return false;
  }
}

/** Whether the sheet mode is on for this viewer, remembered per browser. */
export function useSheetMode(): { available: boolean; active: boolean; toggle: () => void } {
  const [available] = useState(() => !coarsePointer());
  const [on, setOn] = useState(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setOn((v) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, v ? '0' : '1');
      } catch {
        /* storage blocked: the choice lasts for this page only */
      }
      return !v;
    });
  }, []);
  return { available, active: available && on, toggle };
}

export function SheetModeToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      data-testid="boq-sheet-toggle"
      className={`mb-2 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${
        active ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border-light text-content-secondary'
      }`}
    >
      <Table2 size={14} />
      {t('boq.sheet.toggle', { defaultValue: 'Spreadsheet mode' })}
    </button>
  );
}

export interface BOQSheetModeProps {
  boqId: string;
  positions: Position[];
  locale: string;
  standard?: string | null;
  variables?: BOQVariable[];
  readOnly?: boolean;
  onCreateRows: (rows: PastedRow[]) => Promise<void> | void;
}

export function BOQSheetMode({ boqId, positions, locale, standard, variables, readOnly, onCreateRows }: BOQSheetModeProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [issues, setIssues] = useState<Map<string, SheetCellIssue[]>>(new Map());
  const [height, setHeight] = useState(600);

  useEffect(() => {
    const fit = () => setHeight(Math.max(320, Math.round(window.innerHeight * 0.68)));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  const onCommit = useCallback(
    async (edits: SheetCellEdit[]) => {
      try {
        const res = await boqApi.sheetEditPositions(boqId, { edits });
        const next = new Map<string, SheetCellIssue[]>();
        for (const i of res.issues ?? []) {
          next.set(i.position_id, [...(next.get(i.position_id) ?? []), { severity: i.severity, message: i.message }]);
        }
        setIssues(next);
        await queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      } catch (err) {
        const status = (err as { status?: number })?.status;
        addToast({
          type: 'error',
          title:
            status === 409
              ? t('boq.sheet.conflict', { defaultValue: 'Someone else changed these rows. The sheet was reloaded.' })
              : t('boq.sheet.save_failed', { defaultValue: 'The change could not be saved' }),
        });
        await queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        throw err;
      }
    },
    [boqId, queryClient, addToast, t],
  );

  return (
    <BOQSheetView
      positions={positions}
      locale={locale}
      standard={standard}
      variables={variables}
      readOnly={readOnly}
      issues={issues}
      onCommit={onCommit}
      onCreateRows={onCreateRows}
      height={height}
    />
  );
}
