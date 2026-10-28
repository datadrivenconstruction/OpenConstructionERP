// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Record a percent-complete observation from the Progress page.
 *
 * Why this exists: the page rendered progress but offered no way to produce
 * any. Every empty state told the user to "record field entries" while the
 * only surface that could actually record one was the 5D cost page, so the
 * module read as a report with no input, and it was not obvious that the
 * numbers came from anywhere a person could reach.
 *
 * The scope choice is the part worth understanding, because the two options
 * are different readings and not a convenience. A reading against a position
 * says how far one line item has got, and those are what the project
 * percentage is rolled up from, weighted by design quantity. A reading against
 * the whole project is an overall judgement; the rollup falls back to it only
 * when no line has been measured. Recording one while positions are being
 * measured keeps its own row and its entry count but does not move the
 * headline, which is deliberate and is stated on screen rather than left for
 * the user to discover by watching a number not change.
 *
 * Positions come from the quantity-variance payload the page has already
 * fetched, so opening this costs no extra request.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';

import { Button, Input, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { createProgressEntry, type PositionQuantityVarianceItem } from './api';

/** Current month as ``YYYY-MM``: the period label most entries want. */
function currentPeriodLabel(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export interface RecordProgressDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Tracked positions, already loaded by the page. Empty is a valid state. */
  positions: PositionQuantityVarianceItem[];
}

export function RecordProgressDialog({
  open,
  onClose,
  projectId,
  positions,
}: RecordProgressDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [scope, setScope] = useState<'project' | 'position'>('project');
  const [positionId, setPositionId] = useState<string>('');
  const [search, setSearch] = useState('');
  const [period, setPeriod] = useState(currentPeriodLabel);
  const [percent, setPercent] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  // Reopening starts clean rather than showing the previous entry's numbers,
  // which would invite recording the same reading twice by accident.
  useEffect(() => {
    if (!open) return;
    setScope('project');
    setPositionId('');
    setSearch('');
    setPeriod(currentPeriodLabel());
    setPercent('');
    setNotes('');
    setSaving(false);
  }, [open]);

  const filteredPositions = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return positions;
    return positions.filter((p) =>
      `${p.ordinal ?? ''} ${p.description ?? ''}`.toLowerCase().includes(q),
    );
  }, [positions, search]);

  const percentValue = Number(percent);
  const percentValid = percent.trim() !== '' && Number.isFinite(percentValue)
    && percentValue >= 0 && percentValue <= 100;
  const periodValid = period.trim().length > 0 && period.trim().length <= 20;
  const scopeValid = scope === 'project' || positionId !== '';
  const canSave = percentValid && periodValid && scopeValid && !saving;

  const handleSave = useCallback(async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await createProgressEntry({
        project_id: projectId,
        boq_position_id: scope === 'position' ? positionId : null,
        period_label: period.trim(),
        percent_complete: percentValue,
        notes: notes.trim() || null,
      });
      // Every panel on the page reads these three, so all three have to go
      // stale together or the S-curve and the KPI row disagree on screen.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['progress', 's-curve', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['progress', 'cumulative', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['progress', 'quantity-variance', projectId] }),
      ]);
      addToast({
        type: 'success',
        title: t('progress.record_saved_title', { defaultValue: 'Progress recorded' }),
        message: t('progress.record_saved_msg', {
          defaultValue: '{{percent}}% recorded for {{period}}.',
          percent: String(percentValue),
          period: period.trim(),
        }),
      });
      onClose();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('progress.record_failed_title', { defaultValue: 'Could not record progress' }),
        message:
          err instanceof Error
            ? err.message
            : t('progress.record_failed_msg', {
                defaultValue: 'The entry was not saved. Check the values and try again.',
              }),
      });
    } finally {
      setSaving(false);
    }
  }, [
    canSave, projectId, scope, positionId, period, percentValue, notes,
    queryClient, addToast, t, onClose,
  ]);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="md"
      title={t('progress.record_title', { defaultValue: 'Record progress' })}
      subtitle={t('progress.record_subtitle', {
        defaultValue:
          'Entries are append-only. To correct a reading, record the corrected value again in the same period.',
      })}
    >
      <div className="flex flex-col gap-4">
        {/* Scope */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-content-secondary">
            {t('progress.record_scope', { defaultValue: 'What is this reading about?' })}
          </span>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={scope === 'project' ? 'primary' : 'secondary'}
              onClick={() => setScope('project')}
            >
              {t('progress.record_scope_project', { defaultValue: 'The whole project' })}
            </Button>
            <Button
              type="button"
              size="sm"
              variant={scope === 'position' ? 'primary' : 'secondary'}
              onClick={() => setScope('position')}
              disabled={positions.length === 0}
            >
              {t('progress.record_scope_position', { defaultValue: 'One BOQ position' })}
            </Button>
          </div>
          <p className="text-2xs leading-relaxed text-content-tertiary">
            {scope === 'project'
              ? t('progress.record_scope_project_hint', {
                  defaultValue:
                    'An overall judgement for the project. It is used for the headline percentage only while no individual position has been measured; once positions are measured, the headline is rolled up from those instead and this reading keeps its own row without moving it.',
                })
              : t('progress.record_scope_position_hint', {
                  defaultValue:
                    'How far one line item has got. Position readings are what the project percentage is rolled up from, weighted by design quantity, so a position nobody has measured counts as zero rather than being left out.',
                })}
          </p>
          {positions.length === 0 && (
            <p className="text-2xs text-content-tertiary">
              {t('progress.record_no_positions', {
                defaultValue:
                  'This project has no priced BOQ positions yet, so only a project-level reading can be recorded.',
              })}
            </p>
          )}
        </div>

        {/* Position picker */}
        {scope === 'position' && positions.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="progress-position-search"
              className="text-xs font-medium text-content-secondary"
            >
              {t('progress.record_position', { defaultValue: 'Position' })}
            </label>
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-quaternary"
              />
              <Input
                id="progress-position-search"
                type="search"
                className="pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('progress.record_position_search', {
                  defaultValue: 'Search by number or description',
                })}
              />
            </div>
            <div className="max-h-48 overflow-y-auto rounded-lg border border-border-light">
              {filteredPositions.length === 0 ? (
                <p className="px-3 py-4 text-center text-xs text-content-tertiary">
                  {t('progress.record_position_none', {
                    defaultValue: 'No position matches your search.',
                  })}
                </p>
              ) : (
                filteredPositions.map((p) => (
                  <button
                    key={p.boq_position_id}
                    type="button"
                    onClick={() => setPositionId(p.boq_position_id)}
                    className={`flex w-full items-baseline gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-surface-secondary/60 ${
                      positionId === p.boq_position_id ? 'bg-oe-blue/[0.07]' : ''
                    }`}
                  >
                    {p.ordinal && (
                      <span className="shrink-0 font-mono text-2xs text-content-tertiary">
                        {p.ordinal}
                      </span>
                    )}
                    <span className="truncate text-content-primary">
                      {p.description ??
                        t('progress.record_position_untitled', { defaultValue: 'Untitled position' })}
                    </span>
                    {p.unit && (
                      <span className="ml-auto shrink-0 text-2xs text-content-tertiary">
                        {p.unit}
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        )}

        {/* Period + percent */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="progress-period" className="text-xs font-medium text-content-secondary">
              {t('progress.record_period', { defaultValue: 'Period' })}
            </label>
            <Input
              id="progress-period"
              value={period}
              maxLength={20}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2026-07"
            />
            <p className="text-2xs text-content-tertiary">
              {t('progress.record_period_hint', {
                defaultValue:
                  'Everything on this page is grouped by this label, so write it the same way every time. Month is the usual choice.',
              })}
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="progress-percent" className="text-xs font-medium text-content-secondary">
              {t('progress.record_percent', { defaultValue: 'Percent complete' })}
            </label>
            <Input
              id="progress-percent"
              type="number"
              min={0}
              max={100}
              step="0.1"
              value={percent}
              onChange={(e) => setPercent(e.target.value)}
              placeholder="0-100"
            />
            {percent.trim() !== '' && !percentValid && (
              <p className="text-2xs text-oe-red">
                {t('progress.record_percent_invalid', {
                  defaultValue: 'Enter a number between 0 and 100.',
                })}
              </p>
            )}
          </div>
        </div>

        {/* Notes */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="progress-notes" className="text-xs font-medium text-content-secondary">
            {t('progress.record_notes', { defaultValue: 'Notes (optional)' })}
          </label>
          <textarea
            id="progress-notes"
            rows={2}
            maxLength={2000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none"
            placeholder={t('progress.record_notes_ph', {
              defaultValue: 'What was observed, and by whom',
            })}
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-border-light pt-3">
          <Button type="button" variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button type="button" size="sm" onClick={() => void handleSave()} disabled={!canSave}>
            {saving
              ? t('progress.record_saving', { defaultValue: 'Recording...' })
              : t('progress.record_save', { defaultValue: 'Record progress' })}
          </Button>
        </div>
      </div>
    </WideModal>
  );
}
