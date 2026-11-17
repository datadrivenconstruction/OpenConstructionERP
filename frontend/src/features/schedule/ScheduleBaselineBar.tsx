// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Programme baselines and the printable Gantt in the schedule toolbar:
// pick the baseline the Gantt compares against (the approved one by default),
// save the live plan as the next baseline (B0, B1, ...), approve a saved one,
// and download the Gantt chart as a landscape PDF.

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { BadgeCheck, Bookmark, FileDown } from 'lucide-react';

import { Button } from '@/shared/ui';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { scheduleApi, type GanttPaper, type ScheduleBaseline } from './api';
import { approvalOf, baselinesOfSchedule, effectiveBaseline } from './baselineOverlay';

const NONE = '__none__';
const PAPERS: GanttPaper[] = ['A3', 'A4', 'LETTER', 'LEGAL'];

interface ScheduleBaselineBarProps {
  scheduleId: string;
  projectId: string;
  canEdit: boolean;
  /** The baseline the Gantt should draw, or null for none. */
  onBaselineChange: (baseline: ScheduleBaseline | null) => void;
  /** The reader picked or saved a baseline, so the overlay should show. */
  onUserSelect?: () => void;
}

export function ScheduleBaselineBar({
  scheduleId,
  projectId,
  canEdit,
  onBaselineChange,
  onUserSelect,
}: ScheduleBaselineBarProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [chosenId, setChosenId] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [approveNow, setApproveNow] = useState(true);
  const [paper, setPaper] = useState<GanttPaper>('A3');

  const baselinesQ = useQuery<ScheduleBaseline[]>({
    queryKey: ['schedule', 'baselines', projectId],
    queryFn: () => scheduleApi.listBaselines(projectId),
    enabled: !!projectId,
  });
  const baselines = useMemo(
    () => baselinesOfSchedule(baselinesQ.data ?? [], scheduleId),
    [baselinesQ.data, scheduleId],
  );
  const approved = useMemo(() => effectiveBaseline(baselines), [baselines]);
  const selected: ScheduleBaseline | null =
    chosenId === NONE ? null : (baselines.find((b) => b.id === chosenId) ?? approved);

  useEffect(() => {
    onBaselineChange(selected);
  }, [selected, onBaselineChange]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['schedule', 'baselines', projectId] });

  const captureMut = useMutation({
    mutationFn: () =>
      scheduleApi.captureBaseline(scheduleId, {
        name: name.trim() || undefined,
        note: note.trim() || undefined,
        approve: approveNow,
      }),
    onSuccess: (row) => {
      setCapturing(false);
      setName('');
      setNote('');
      setChosenId(row.id);
      onUserSelect?.();
      void refresh();
      addToast({
        type: 'success',
        title: t('schedule.baselines.saved', { defaultValue: 'Baseline {{name}} saved', name: row.name }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message:
          e instanceof ApiError && e.status === 422
            ? t('schedule.baselines.empty_schedule', { defaultValue: 'Add activities before saving a baseline.' })
            : getErrorMessage(e),
      });
    },
  });

  const approveMut = useMutation({
    mutationFn: (baselineId: string) => scheduleApi.approveBaseline(scheduleId, baselineId),
    onSuccess: (row) => {
      void refresh();
      addToast({
        type: 'success',
        title: t('schedule.baselines.approved_toast', {
          defaultValue: '{{name}} is now the approved baseline',
          name: row.name,
        }),
      });
    },
    onError: (e) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    },
  });

  const pdfMut = useMutation({
    mutationFn: () =>
      scheduleApi.downloadGanttPdf(scheduleId, { baselineId: selected ? selected.id : null, paper }),
    onError: (e) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    },
  });

  const optionLabel = (b: ScheduleBaseline) =>
    approvalOf(b) && b.is_active
      ? t('schedule.baselines.approved_suffix', { defaultValue: '{{name}} (approved)', name: b.name })
      : `${b.name} · ${b.baseline_date}`;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="schedule-baseline-bar">
      <select
        className="oe-select h-8 w-auto py-0 text-xs"
        aria-label={t('schedule.baselines.select_aria', { defaultValue: 'Baseline to compare against' })}
        value={selected ? selected.id : NONE}
        onChange={(e) => {
          setChosenId(e.target.value);
          if (e.target.value !== NONE) onUserSelect?.();
        }}
      >
        <option value={NONE}>{t('schedule.baselines.none', { defaultValue: 'No baseline' })}</option>
        {baselines.map((b) => (
          <option key={b.id} value={b.id}>
            {optionLabel(b)}
          </option>
        ))}
      </select>
      {canEdit && selected && !(selected.is_active && approvalOf(selected)) && (
        <Button
          variant="secondary"
          size="sm"
          icon={<BadgeCheck size={14} />}
          loading={approveMut.isPending}
          onClick={() => approveMut.mutate(selected.id)}
          title={t('schedule.baselines.approve_tooltip', {
            defaultValue: 'Make this baseline the approved plan. The previously approved one stays saved, unchanged.',
          })}
        >
          {t('schedule.baselines.approve', { defaultValue: 'Approve' })}
        </Button>
      )}
      {canEdit && (
        <Button
          variant="secondary"
          size="sm"
          icon={<Bookmark size={14} />}
          aria-expanded={capturing}
          onClick={() => setCapturing((v) => !v)}
          title={t('schedule.baselines.save_tooltip', {
            defaultValue: 'Freeze the current plan as the next baseline (B0, B1, ...). It never changes afterwards.',
          })}
        >
          {t('schedule.baselines.save', { defaultValue: 'Save baseline' })}
        </Button>
      )}
      <select
        className="oe-select h-8 w-auto py-0 text-xs"
        aria-label={t('schedule.gantt_pdf.paper_aria', { defaultValue: 'Paper size' })}
        value={paper}
        onChange={(e) => setPaper(e.target.value as GanttPaper)}
      >
        {PAPERS.map((p) => (
          <option key={p} value={p}>
            {p === 'LETTER' ? 'Letter' : p === 'LEGAL' ? 'Legal' : p}
          </option>
        ))}
      </select>
      <Button
        variant="secondary"
        size="sm"
        icon={<FileDown size={14} />}
        loading={pdfMut.isPending}
        onClick={() => pdfMut.mutate()}
        title={t('schedule.gantt_pdf.tooltip', {
          defaultValue:
            'Printable Gantt chart: activity table, timescale, current, baseline and actual bars, critical path and legend.',
        })}
      >
        {t('schedule.gantt_pdf.export', { defaultValue: 'Export PDF' })}
      </Button>

      {capturing && (
        <form
          className="flex w-full flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary p-2"
          data-testid="baseline-capture-form"
          onSubmit={(e) => {
            e.preventDefault();
            captureMut.mutate();
          }}
        >
          <input
            className="oe-input h-8 w-40 text-xs"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('schedule.baselines.name_placeholder', { defaultValue: 'Name (optional)' })}
            aria-label={t('schedule.baselines.name_placeholder', { defaultValue: 'Name (optional)' })}
          />
          <input
            className="oe-input h-8 min-w-[14rem] flex-1 text-xs"
            value={note}
            maxLength={1000}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('schedule.baselines.note_placeholder', {
              defaultValue: 'Reason, e.g. approved variation (optional)',
            })}
            aria-label={t('schedule.baselines.note_placeholder', {
              defaultValue: 'Reason, e.g. approved variation (optional)',
            })}
          />
          <label className="flex items-center gap-1.5 text-xs text-content-secondary">
            <input type="checkbox" checked={approveNow} onChange={(e) => setApproveNow(e.target.checked)} />
            {t('schedule.baselines.approve_now', { defaultValue: 'Approve as the current baseline' })}
          </label>
          <Button type="submit" size="sm" loading={captureMut.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setCapturing(false)}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </form>
      )}
    </div>
  );
}
