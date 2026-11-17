// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Formal revision navigator (R0, R1, R2, ...) for the Version History drawer.
 *
 * Lists every revision linked to the open bill, oldest first, with status,
 * author, date, total and the change against the revision it was raised
 * from. Open / Previous / Next go to the existing `/boq/{id}` route; ticking
 * two revisions hands them, older first, to the existing BOQ compare. Pure
 * read: nothing here writes.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, GitCompare, Loader2, Lock, Layers } from 'lucide-react';
import clsx from 'clsx';
import { boqApi, type BOQRevisionEntry } from './api';
import { compareOrder } from './revisionHelpers';
import { getIntlLocale } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export interface RevisionsPanelProps {
  boqId: string;
  onOpen: (boqId: string) => void;
  onCompare: (olderId: string, newerId: string) => void;
}

function money(v: string | null, signed = false): string {
  if (v == null) return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  return n.toLocaleString(getNumberLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
    signDisplay: signed ? 'exceptZero' : 'auto',
  });
}

function date(v: string): string {
  try {
    return new Date(v).toLocaleDateString(getIntlLocale(), { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return v;
  }
}

export function RevisionsPanel({ boqId, onOpen, onCompare }: RevisionsPanelProps) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<string[]>([]);
  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-revisions', boqId],
    queryFn: () => boqApi.getRevisions(boqId),
    enabled: !!boqId,
  });

  const toggle = (id: string) =>
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-2)));

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-content-tertiary" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <p role="alert" className="px-4 py-12 text-center text-sm text-content-secondary">
        {t('boq.revisions_error', { defaultValue: 'Failed to load revisions.' })}
      </p>
    );
  }

  const revisions = data.revisions;
  const canCompare = picked.length === 2;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <p className="border-b border-border px-4 py-2 text-2xs text-content-tertiary">
        {t('boq.revisions_hint', {
          defaultValue:
            'Revisions are bills issued one after another (R0, R1, R2). Snapshots are saved states of one bill; branches are alternative estimates.',
        })}
      </p>
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
        <button
          type="button"
          disabled={!data.previous_id}
          onClick={() => data.previous_id && onOpen(data.previous_id)}
          className="flex h-7 items-center gap-1 rounded-md px-2 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          <ChevronLeft size={12} />
          {t('common.previous', { defaultValue: 'Previous' })}
        </button>
        <button
          type="button"
          disabled={!data.next_id}
          onClick={() => data.next_id && onOpen(data.next_id)}
          className="flex h-7 items-center gap-1 rounded-md px-2 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          {t('common.next', { defaultValue: 'Next' })}
          <ChevronRight size={12} />
        </button>
        <button
          type="button"
          disabled={!canCompare}
          onClick={() => {
            const [older, newer] = compareOrder(revisions, picked[0]!, picked[1]!);
            onCompare(older, newer);
          }}
          title={t('boq.select_two_to_compare', { defaultValue: 'Tick two to compare' })}
          className="ml-auto flex h-7 items-center gap-1 rounded-md bg-oe-blue px-2 text-xs font-medium text-white hover:bg-oe-blue-hover disabled:opacity-40"
        >
          <GitCompare size={12} />
          {t('boq.compare_btn', { defaultValue: 'Compare' })}
        </button>
      </div>

      {revisions.length < 2 ? (
        <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
          <Layers size={32} className="mb-3 text-content-quaternary" />
          <p className="text-sm text-content-secondary">
            {t('boq.revisions_empty', {
              defaultValue: 'No other revisions yet. Use Create Revision to issue the next one.',
            })}
          </p>
        </div>
      ) : (
        <ul className="flex-1 divide-y divide-border-light overflow-y-auto">
          {revisions.map((r: BOQRevisionEntry) => {
            const delta = r.delta_vs_parent != null ? Number(r.delta_vs_parent) : null;
            return (
              <li
                key={r.boq_id}
                data-testid={`revision-${r.label}`}
                aria-current={r.is_current ? 'true' : undefined}
                className={clsx('flex items-start gap-2 px-4 py-3', r.is_current && 'bg-oe-blue/5')}
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={picked.includes(r.boq_id)}
                  onChange={() => toggle(r.boq_id)}
                  aria-label={t('boq.select_two_to_compare', { defaultValue: 'Tick two to compare' }) + ` ${r.label}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-xs font-medium text-content-primary">
                    <span
                      className="rounded bg-surface-secondary px-1.5 font-mono text-oe-blue"
                      title={
                        r.number_is_derived
                          ? t('boq.revision_derived_number', {
                              defaultValue: 'Number taken from creation order; this revision predates numbering.',
                            })
                          : undefined
                      }
                    >
                      {r.label}
                      {r.number_is_derived ? '*' : ''}
                    </span>
                    <span className="truncate">{r.name}</span>
                    {r.is_locked && <Lock size={10} className="shrink-0 text-content-tertiary" />}
                  </p>
                  <p className="mt-0.5 text-2xs text-content-tertiary">
                    {t(`boq.status_${r.status}`, { defaultValue: r.status })} · {date(r.created_at)}
                    {r.created_by_name ? ` · ${r.created_by_name}` : ''}
                  </p>
                  <p className="mt-0.5 flex items-center gap-2 text-2xs">
                    <span className="font-mono text-content-secondary">{money(r.grand_total)}</span>
                    {delta !== null && delta !== 0 && (
                      <span
                        className={clsx(
                          'font-mono font-medium',
                          delta > 0 ? 'text-semantic-success' : 'text-semantic-error',
                        )}
                      >
                        {money(r.delta_vs_parent, true)}
                      </span>
                    )}
                  </p>
                </div>
                {r.is_current ? (
                  <span className="shrink-0 text-2xs font-medium text-oe-blue">
                    {t('boq.revision_current', { defaultValue: 'You are here' })}
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => onOpen(r.boq_id)}
                    className="shrink-0 rounded px-2 py-0.5 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10"
                  >
                    {t('common.open', { defaultValue: 'Open' })}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
