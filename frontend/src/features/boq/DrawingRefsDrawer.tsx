// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Source drawings" of one BOQ line: every sheet its quantity was measured on
 * (number, title, revision, page, measurements), whether the sheet was revised
 * since, and a small form for a drawing reference typed by hand.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';

import { Button, SideDrawer } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import type { Position } from './api';
import {
  drawingRefLabel,
  useSetManualDrawingRef,
  type DrawingRef,
  type PositionDrawingRefs,
} from './drawingRefsApi';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function DrawingRefsDrawer({
  boqId,
  position,
  entry,
  readOnly,
  onClose,
  onOpenRef,
  onCompareRef,
}: {
  boqId: string;
  position: Position;
  entry: PositionDrawingRefs | undefined;
  readOnly: boolean;
  onClose: () => void;
  onOpenRef: (ref: DrawingRef) => void;
  onCompareRef: (ref: DrawingRef) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const mutation = useSetManualDrawingRef(boqId);
  const [number, setNumber] = useState(entry?.manual?.drawing_ref ?? '');
  const [revision, setRevision] = useState(entry?.manual?.drawing_revision ?? '');

  const save = (clear: boolean) => {
    const ref = clear ? '' : number.trim();
    mutation.mutate(
      {
        positionId: position.id,
        body: { drawing_ref: ref || null, drawing_revision: ref ? revision.trim() || null : null },
      },
      {
        onSuccess: () => {
          if (clear) {
            setNumber('');
            setRevision('');
          }
          addToast({ type: 'success', title: t('boq.drawing_ref.saved', { defaultValue: 'Drawing reference saved' }) });
        },
        onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
      },
    );
  };

  const refs = entry?.refs ?? [];

  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-xl"
      title={t('boq.drawing_ref.title', { defaultValue: 'Source drawings' })}
      subtitle={`${position.ordinal} ${position.description}`.trim()}
      busy={mutation.isPending}
    >
      <div className="space-y-5 px-5 py-4" data-testid="drawing-refs-drawer">
        {refs.length === 0 ? (
          <p className="text-sm text-content-secondary">
            {t('boq.drawing_ref.none', { defaultValue: 'No measured drawing is linked to this line yet.' })}
          </p>
        ) : (
          <ul className="space-y-2">
            {refs.map((r, i) => (
              <li
                key={`${r.sheet_id ?? r.document_id ?? r.takeoff_document_id ?? 'ref'}-${r.page}-${i}`}
                className="rounded-lg border border-border-light p-3"
                data-testid="drawing-refs-row"
              >
                <div className="flex items-start justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenRef(r)}
                    className="inline-flex min-w-0 items-center gap-1.5 text-start text-sm font-medium text-oe-blue hover:underline"
                  >
                    <FileText size={14} className="shrink-0" />
                    <span className="truncate">{drawingRefLabel(r, t) || r.drawing_title}</span>
                  </button>
                  {r.outdated && (
                    <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-2xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
                      {t('boq.drawing_ref.revised', { defaultValue: 'Revised' })}
                    </span>
                  )}
                </div>
                {r.drawing_title && <p className="mt-0.5 truncate text-xs text-content-secondary">{r.drawing_title}</p>}
                <p className="mt-1 text-2xs text-content-tertiary">
                  {t('boq.drawing_ref.page_n', { defaultValue: 'page {{page}}', page: r.page })}
                  {' · '}
                  {t('boq.drawing_ref.measurements_n', {
                    defaultValue: '{{count}} measurements',
                    count: r.measurement_count,
                  })}
                </p>
                {r.outdated && (
                  <p className="mt-1 flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300">
                    {t('boq.drawing_ref.newer_exists', {
                      defaultValue: 'A newer revision exists: {{rev}}.',
                      rev: r.current_revision ?? '',
                    })}
                    {r.compare && (
                      <button type="button" onClick={() => onCompareRef(r)} className="font-medium text-oe-blue hover:underline">
                        {t('boq.drawing_ref.compare', { defaultValue: 'See what changed' })}
                      </button>
                    )}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2 border-t border-border-light pt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('boq.drawing_ref.manual_title', { defaultValue: 'Drawing noted by hand' })}
          </h3>
          <div className="grid grid-cols-[1fr_7rem] gap-2">
            <input
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              disabled={readOnly}
              placeholder={t('boq.drawing_ref.number_ph', { defaultValue: 'Drawing number, e.g. A-101' })}
              aria-label={t('boq.drawing_ref.number_aria', { defaultValue: 'Drawing number' })}
              data-testid="drawing-ref-number"
              className={inputCls}
            />
            <input
              value={revision}
              onChange={(e) => setRevision(e.target.value)}
              disabled={readOnly}
              placeholder={t('boq.drawing_ref.revision_ph', { defaultValue: 'Revision' })}
              aria-label={t('boq.drawing_ref.revision_aria', { defaultValue: 'Drawing revision' })}
              data-testid="drawing-ref-revision"
              className={inputCls}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => save(false)} disabled={readOnly || mutation.isPending || !number.trim()}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            {entry?.manual && (
              <Button size="sm" variant="ghost" onClick={() => save(true)} disabled={readOnly || mutation.isPending}>
                {t('boq.drawing_ref.clear', { defaultValue: 'Remove' })}
              </Button>
            )}
          </div>
        </div>
      </div>
    </SideDrawer>
  );
}
