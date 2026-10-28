// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The framework schedule: milestones ordered by date, each with its successor,
// lead time, gate and whether the schedule module agrees. A backward plan from
// the operating proof is shown as a preview first; a person confirms it.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { CalendarClock, CalendarRange, Flag, ListPlus, Pencil, Plus, Trash2, Upload } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  backplan,
  briefKeys,
  createMilestone,
  deleteMilestone,
  milestonesFromCatalogue,
  milestonesFromGates,
  publishSchedule,
  updateMilestone,
  type BriefCatalogue,
  type Can,
  type Milestone,
  type MilestoneInput,
} from './api';
import { ExportButtons, FIELD_CLASS, FormError, ReadOnlyNotice, useBriefAction, useSubmit } from './BriefBits';
import { useGates } from './hooks';
import { itemLabel, refusalText, type LabelContext, type TFn } from './labels';

const EMPTY: MilestoneInput = { kind_code: '', name: '', planned_date: null, lead_days: 0, successor_id: null, gate_code: null, notes: '' };

/** Milestones by planned date, the undated ones last; ties keep the server's order. */
export function sortByDate(rows: Milestone[]): Milestone[] {
  return rows
    .map((m, i) => ({ m, i }))
    .sort((a, b) => {
      const da = a.m.planned_date;
      const db = b.m.planned_date;
      if (da && db) return da === db ? a.i - b.i : da < db ? -1 : 1;
      if (da) return -1;
      if (db) return 1;
      return a.i - b.i;
    })
    .map((x) => x.m);
}

type Sync = 'in_sync' | 'out_of_sync' | 'not_published';

/** Whether the schedule module agrees with the milestone, from the server's findings about it. */
export function syncState(m: Milestone): Sync {
  if (!m.activity_id) return 'not_published';
  if (!m.published || m.findings.some((f) => f.code === 'schedule_out_of_sync' || f.code === 'activity_missing')) return 'out_of_sync';
  return 'in_sync';
}

const SYNC_TONE = { in_sync: 'success', out_of_sync: 'warning', not_published: 'neutral' } as const;

function MilestoneDialog({
  open,
  projectId,
  catalogue,
  labels,
  milestones,
  editing,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  catalogue: BriefCatalogue;
  labels: LabelContext;
  milestones: Milestone[];
  editing: Milestone | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<MilestoneInput>(EMPTY);
  const gates = useGates(projectId, open);
  const [tried, setTried] = useState(false);
  const sub = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (!open) return;
    setTried(false);
    sub.reset();
    setForm(
      editing
        ? {
            kind_code: editing.kind_code,
            name: editing.name,
            planned_date: editing.planned_date,
            lead_days: editing.lead_days,
            successor_id: editing.successor_id,
            gate_code: editing.gate_code,
            notes: '',
          }
        : { ...EMPTY, kind_code: catalogue.milestone_kinds[0]?.code ?? '' },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const kind = catalogue.milestone_kinds.find((k) => k.code === form.kind_code);
  const save = () => {
    if (!form.name.trim() || !form.kind_code) {
      setTried(true);
      return;
    }
    const body = { ...form, gate_code: kind?.gate ? form.gate_code || null : null };
    // Notes are not shown back by the list, so an edit leaves them out instead of blanking them.
    const { notes: _notes, ...withoutNotes } = body;
    void sub.run(() => (editing ? updateMilestone(projectId, editing.id, withoutNotes) : createMilestone(projectId, body)));
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="md"
      testId="brief-milestone-dialog"
      title={
        editing
          ? t('engineeringBrief.schedule.edit', { defaultValue: 'Edit milestone' })
          : t('engineeringBrief.schedule.add', { defaultValue: 'Add milestone' })
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={save} data-testid="brief-milestone-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <WideModalField label={t('engineeringBrief.schedule.kind', { defaultValue: 'Kind' })} required>
          <select className={FIELD_CLASS} value={form.kind_code} onChange={(e) => setForm({ ...form, kind_code: e.target.value })}>
            {catalogue.milestone_kinds.map((k) => (
              <option key={k.code} value={k.code}>
                {itemLabel(labels, k, k.code)}
              </option>
            ))}
            {form.kind_code && !kind ? <option value={form.kind_code}>{form.kind_code}</option> : null}
          </select>
        </WideModalField>
        <WideModalField
          label={t('engineeringBrief.schedule.name', { defaultValue: 'Name' })}
          required
          error={tried && !form.name.trim() ? t('engineeringBrief.required', { defaultValue: 'Required' }) : undefined}
        >
          <input className={FIELD_CLASS} value={form.name} maxLength={255} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="brief-milestone-name" />
        </WideModalField>
        <div className="grid grid-cols-2 gap-3">
          <WideModalField label={t('engineeringBrief.schedule.date', { defaultValue: 'Planned date' })}>
            <input className={FIELD_CLASS} type="date" value={form.planned_date ?? ''} onChange={(e) => setForm({ ...form, planned_date: e.target.value || null })} data-testid="brief-milestone-date" />
          </WideModalField>
          <WideModalField label={t('engineeringBrief.schedule.lead_days', { defaultValue: 'Lead time (days)' })}>
            <input
              className={FIELD_CLASS}
              type="number"
              min={0}
              max={3650}
              value={form.lead_days}
              onChange={(e) => setForm({ ...form, lead_days: Math.max(0, Math.min(3650, Math.trunc(Number(e.target.value) || 0))) })}
            />
          </WideModalField>
        </div>
        <WideModalField label={t('engineeringBrief.schedule.successor', { defaultValue: 'Successor' })} hint={t('engineeringBrief.schedule.successor_hint', { defaultValue: 'The milestone that follows this one. The date is planned backwards from it.' })}>
          <select className={FIELD_CLASS} value={form.successor_id ?? ''} onChange={(e) => setForm({ ...form, successor_id: e.target.value || null })}>
            <option value="">{t('engineeringBrief.none', { defaultValue: 'None' })}</option>
            {milestones
              .filter((m) => m.id !== editing?.id)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.code} {m.name}
                </option>
              ))}
          </select>
        </WideModalField>
        {kind?.gate ? (
          <WideModalField label={t('engineeringBrief.schedule.gate', { defaultValue: 'Gate' })}>
            <select className={FIELD_CLASS} value={form.gate_code ?? ''} onChange={(e) => setForm({ ...form, gate_code: e.target.value || null })} data-testid="brief-milestone-gate">
              <option value="">{t('engineeringBrief.none', { defaultValue: 'None' })}</option>
              {(gates.data ?? []).map((g) => (
                <option key={g.code} value={g.code}>
                  {g.label || g.code}
                </option>
              ))}
            </select>
          </WideModalField>
        ) : null}
      </div>
    </WideModal>
  );
}

function BackplanDialog({
  open,
  projectId,
  milestones,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  milestones: Milestone[];
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const preview = useQuery({
    queryKey: [...briefKeys.milestones(projectId), 'backplan-preview'],
    queryFn: () => backplan(projectId, false),
    enabled: open,
    gcTime: 0,
    retry: false,
  });
  const apply = useSubmit(() => {
    addToast({ type: 'success', title: t('engineeringBrief.backplan.applied', { defaultValue: 'Planned dates updated' }) });
    onDone();
    onClose();
  });
  const changes = preview.data?.changes ?? [];
  const moved = changes.filter((c) => c.changed);
  const name = (id: string) => milestones.find((m) => m.id === id)?.name ?? id;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={apply.busy}
      size="lg"
      testId="brief-backplan-dialog"
      title={t('engineeringBrief.backplan.title', { defaultValue: 'Plan backwards from the operating proof' })}
      subtitle={t('engineeringBrief.backplan.subtitle', {
        defaultValue: 'These dates are proposals. Gate milestones keep their dates. Nothing changes until you apply.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={apply.error} />
          <Button variant="ghost" onClick={onClose} disabled={apply.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            loading={apply.busy}
            disabled={preview.isLoading || preview.isError || moved.length === 0}
            onClick={() => void apply.run(() => backplan(projectId, true))}
            data-testid="brief-backplan-apply"
          >
            {t('engineeringBrief.backplan.apply', { defaultValue: 'Apply dates' })}
          </Button>
        </div>
      }
    >
      {preview.isLoading ? (
        <SkeletonTable rows={4} columns={4} />
      ) : preview.isError ? (
        <ErrorState
          title={t('engineeringBrief.backplan.failed', { defaultValue: 'The plan could not be calculated' })}
          hint={refusalText(t as TFn, preview.error)}
          onRetry={() => preview.refetch()}
        />
      ) : changes.length === 0 ? (
        <p className="text-sm text-content-secondary" data-testid="brief-backplan-empty">
          {t('engineeringBrief.backplan.none', { defaultValue: 'There is nothing to plan: add milestones with successors first.' })}
        </p>
      ) : (
        <div className="space-y-2">
          <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
            <table className="w-full text-sm" data-testid="brief-backplan-table">
              <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
                <tr>
                  <th className="px-3 py-2">{t('engineeringBrief.schedule.name', { defaultValue: 'Name' })}</th>
                  <th className="px-3 py-2">{t('engineeringBrief.backplan.from', { defaultValue: 'From' })}</th>
                  <th className="px-3 py-2">{t('engineeringBrief.backplan.to', { defaultValue: 'To' })}</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((c) => (
                  <tr key={c.id} className="border-t border-border-light" data-testid="brief-backplan-row">
                    <td className="px-3 py-2 text-content-primary">
                      <span className="mr-2 font-mono text-xs text-content-tertiary">{c.code}</span>
                      {name(c.id)}
                    </td>
                    <td className="px-3 py-2 text-content-secondary">{c.from ? fmtDate(c.from) : t('engineeringBrief.not_set', { defaultValue: 'Not set' })}</td>
                    <td className={`px-3 py-2 ${c.changed ? 'font-medium text-content-primary' : 'text-content-secondary'}`}>{fmtDate(c.to)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(preview.data?.unreached.length ?? 0) > 0 ? (
            <p className="text-sm text-semantic-warning" data-testid="brief-backplan-unreached">
              {t('engineeringBrief.backplan.unreached', {
                defaultValue: 'Milestones that cannot be reached from the anchor keep their dates: {{count}}.',
                count: preview.data?.unreached.length ?? 0,
              })}
            </p>
          ) : null}
        </div>
      )}
    </WideModal>
  );
}

export function ScheduleTab({
  projectId,
  milestones,
  catalogue,
  labels,
  edit,
  publish,
  onChanged,
}: {
  projectId: string;
  milestones: Milestone[];
  catalogue: BriefCatalogue;
  labels: LabelContext;
  edit: Can;
  publish: Can;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [dialog, setDialog] = useState<{ editing: Milestone | null } | null>(null);
  const [planning, setPlanning] = useState(false);
  const [removing, setRemoving] = useState<Milestone | null>(null);
  const fromCatalogue = useBriefAction(() => milestonesFromCatalogue(projectId), onChanged);
  const fromGates = useBriefAction(() => milestonesFromGates(projectId), onChanged);
  const published = useBriefAction(
    () => publishSchedule(projectId),
    (result) => {
      addToast({
        type: 'success',
        title: t('engineeringBrief.schedule.published', {
          defaultValue: 'Published to the schedule: {{created}} created, {{moved}} moved',
          created: result.created,
          moved: result.moved,
        }),
      });
      onChanged();
    },
  );
  const remove = useBriefAction((id: string) => deleteMilestone(projectId, id), () => {
    setRemoving(null);
    onChanged();
  });
  const rows = sortByDate(milestones);
  const byId = new Map(milestones.map((m) => [m.id, m]));
  const SYNC_LABEL: Record<Sync, string> = {
    in_sync: t('engineeringBrief.sync.in_sync', { defaultValue: 'In sync' }),
    out_of_sync: t('engineeringBrief.sync.out_of_sync', { defaultValue: 'Out of sync' }),
    not_published: t('engineeringBrief.sync.not_published', { defaultValue: 'Not published' }),
  };

  return (
    <div className="space-y-4" data-testid="brief-schedule">
      <ReadOnlyNotice edit={edit} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ExportButtons projectId={projectId} what="schedule" />
        <div className="flex flex-wrap gap-2">
          {edit.allowed ? (
            <>
              <Button variant="secondary" size="sm" icon={<ListPlus size={14} />} loading={fromCatalogue.isPending} onClick={() => fromCatalogue.mutate()} data-testid="brief-milestones-from-catalogue">
                {t('engineeringBrief.schedule.from_catalogue', { defaultValue: 'From catalogue' })}
              </Button>
              <Button variant="secondary" size="sm" icon={<Flag size={14} />} loading={fromGates.isPending} onClick={() => fromGates.mutate()} data-testid="brief-milestones-from-gates">
                {t('engineeringBrief.schedule.from_gates', { defaultValue: 'From gates' })}
              </Button>
              <Button variant="secondary" size="sm" icon={<CalendarRange size={14} />} onClick={() => setPlanning(true)} data-testid="brief-milestones-backplan">
                {t('engineeringBrief.schedule.backplan', { defaultValue: 'Plan backwards' })}
              </Button>
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ editing: null })} data-testid="brief-milestone-add">
                {t('engineeringBrief.schedule.add', { defaultValue: 'Add milestone' })}
              </Button>
            </>
          ) : null}
          {publish.applies !== false ? (
            <Button
              size="sm"
              icon={<Upload size={14} />}
              loading={published.isPending}
              disabled={!publish.allowed || milestones.length === 0}
              onClick={() => published.mutate()}
              data-testid="brief-milestones-publish"
            >
              {t('engineeringBrief.schedule.publish', { defaultValue: 'Publish to schedule' })}
            </Button>
          ) : null}
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<CalendarClock size={28} />}
          title={t('engineeringBrief.schedule.empty_title', { defaultValue: 'No milestones yet' })}
          description={t('engineeringBrief.schedule.empty_body', {
            defaultValue: 'Start from the catalogue chain or from the gates of the project, then adjust dates and successors.',
          })}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full text-sm" data-testid="brief-milestone-table">
            <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
              <tr>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.date', { defaultValue: 'Planned date' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.name', { defaultValue: 'Name' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.kind', { defaultValue: 'Kind' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.successor', { defaultValue: 'Successor' })}</th>
                <th className="px-3 py-2 text-right">{t('engineeringBrief.schedule.lead_days', { defaultValue: 'Lead time (days)' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.gate', { defaultValue: 'Gate' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.schedule.sync', { defaultValue: 'Schedule' })}</th>
                <th className="w-20 px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const sync = syncState(m);
                const successor = m.successor_id ? byId.get(m.successor_id) : undefined;
                const blocking = m.findings.filter((f) => f.severity === 'error').length;
                return (
                  <tr key={m.id} className="border-t border-border-light" data-testid="brief-milestone-row">
                    <td className="whitespace-nowrap px-3 py-2 text-content-primary">{m.planned_date ? fmtDate(m.planned_date) : t('engineeringBrief.not_set', { defaultValue: 'Not set' })}</td>
                    <td className="px-3 py-2 text-content-primary">
                      <span className="mr-2 font-mono text-xs text-content-tertiary">{m.code}</span>
                      {m.name}
                      {blocking > 0 ? (
                        <span className="ml-2 text-xs text-semantic-error" data-testid="brief-milestone-blocking">
                          {t('engineeringBrief.schedule.blocking', { defaultValue: '{{count}} blocking', count: blocking })}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-content-secondary">{itemLabel(labels, catalogue.milestone_kinds.find((k) => k.code === m.kind_code), m.kind_code)}</td>
                    <td className="px-3 py-2 text-content-secondary">{successor ? `${successor.code} ${successor.name}` : '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{m.lead_days}</td>
                    <td className="px-3 py-2 text-content-secondary">{m.gate ? m.gate.label || m.gate.code : m.gate_code || '-'}</td>
                    <td className="px-3 py-2">
                      <span data-testid="brief-milestone-sync" data-sync={sync}>
                        <Badge variant={SYNC_TONE[sync]} size="sm">
                          {SYNC_LABEL[sync]}
                        </Badge>
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {edit.allowed ? (
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={14} />} onClick={() => setDialog({ editing: m })} />
                          <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={14} />} onClick={() => setRemoving(m)} />
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <MilestoneDialog
        open={dialog !== null}
        projectId={projectId}
        catalogue={catalogue}
        labels={labels}
        milestones={milestones}
        editing={dialog?.editing ?? null}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <BackplanDialog open={planning} projectId={projectId} milestones={milestones} onClose={() => setPlanning(false)} onDone={onChanged} />
      <ConfirmDialog
        open={removing !== null}
        title={t('engineeringBrief.schedule.delete_title', { defaultValue: 'Delete milestone' })}
        message={t('engineeringBrief.schedule.delete_body', { defaultValue: 'This milestone is removed from the framework schedule.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
