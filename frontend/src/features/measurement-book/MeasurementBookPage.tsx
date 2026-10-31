// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measurement book: dated quantity entries per BOQ position (number x length x breadth x height,
 * or a direct quantity), a second-person check, and the running bill that feeds progress claims.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, Check, Ruler, Trash2, X } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  checkEntry,
  createEntry,
  deleteEntry,
  fetchEntries,
  fetchPositions,
  fetchRunningBill,
  fetchValidation,
  postToProgress,
  type CheckStatus,
  type EntryInput,
  type PositionSummary,
} from './api';

const inputCls =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

const STATUS_VARIANT: Record<CheckStatus, BadgeVariant> = {
  unchecked: 'warning',
  checked: 'success',
  disputed: 'error',
};

function pct(v: string): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function StatusBadge({ status }: { status: CheckStatus }) {
  const { t } = useTranslation();
  const label: Record<CheckStatus, string> = {
    unchecked: t('measurement_book.status_unchecked', { defaultValue: 'Unchecked' }),
    checked: t('measurement_book.status_checked', { defaultValue: 'Checked' }),
    disputed: t('measurement_book.status_disputed', { defaultValue: 'Disputed' }),
  };
  return (
    <Badge variant={STATUS_VARIANT[status]} size="sm">
      {label[status]}
    </Badge>
  );
}

function Explainer() {
  const { t } = useTranslation();
  return (
    <p className="text-xs text-content-tertiary">
      {t('measurement_book.explainer', {
        defaultValue:
          'Record what was actually built, one dated line per place: number x length x breadth x height, or a direct quantity. A second person checks each line. Checked quantities make the running bill, which progress claims then pick up.',
      })}
    </p>
  );
}

function ValidationPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['measurement-book', 'validation', projectId],
    queryFn: () => fetchValidation(projectId),
  });
  const failed = (q.data?.results ?? []).filter((r) => !r.passed);
  if (failed.length === 0) return null;
  return (
    <Card padding="sm" data-testid="measurement-book-findings">
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <AlertTriangle size={14} className="text-semantic-warning" />
        {t('measurement_book.findings', { defaultValue: 'Findings' })}
      </h3>
      <ul className="space-y-1 text-xs">
        {failed.map((r, i) => (
          <li key={`${r.rule_id}-${r.element_ref ?? ''}-${i}`} className="flex items-start gap-2">
            <Badge variant={r.severity === 'error' ? 'error' : 'warning'} size="sm">
              {r.severity}
            </Badge>
            <span className="text-content-secondary">{r.message}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function PositionsTable({ rows, onOpen }: { rows: PositionSummary[]; onOpen: (p: PositionSummary) => void }) {
  const { t } = useTranslation();
  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-2xs uppercase text-content-tertiary">
              <th className="px-3 py-2 text-start">{t('measurement_book.col_ordinal', { defaultValue: 'No.' })}</th>
              <th className="px-3 py-2 text-start">{t('measurement_book.col_description', { defaultValue: 'Description' })}</th>
              <th className="px-3 py-2 text-start">{t('measurement_book.col_unit', { defaultValue: 'Unit' })}</th>
              <th className="px-3 py-2 text-end">{t('measurement_book.col_boq_qty', { defaultValue: 'BOQ qty' })}</th>
              <th className="px-3 py-2 text-end">{t('measurement_book.col_measured', { defaultValue: 'Measured' })}</th>
              <th className="px-3 py-2 text-end">{t('measurement_book.col_checked', { defaultValue: 'Checked' })}</th>
              <th className="px-3 py-2 text-start">{t('measurement_book.col_percent', { defaultValue: '% measured' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const over = pct(p.percent_measured) > 100;
              return (
                <tr
                  key={p.boq_position_id}
                  onClick={() => onOpen(p)}
                  className="cursor-pointer border-b border-border-light hover:bg-surface-secondary/50"
                  data-testid="measurement-book-position"
                >
                  <td className="px-3 py-2 tabular-nums" dir="ltr">{p.ordinal}</td>
                  <td className="px-3 py-2 text-content-primary">{p.description}</td>
                  <td className="px-3 py-2">{p.unit}</td>
                  <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{p.boq_quantity}</td>
                  <td className={`px-3 py-2 text-end tabular-nums ${over ? 'font-semibold text-semantic-error' : ''}`} dir="ltr">
                    {p.measured_quantity}
                  </td>
                  <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{p.checked_quantity}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-tertiary">
                        <div
                          className={`h-full ${over ? 'bg-semantic-error' : 'bg-oe-blue'}`}
                          style={{ width: `${Math.min(100, Math.max(0, pct(p.percent_measured)))}%` }}
                        />
                      </div>
                      <span className="text-2xs tabular-nums text-content-secondary" dir="ltr">{p.percent_measured}%</span>
                      {p.unchecked_count > 0 && (
                        <Badge variant="warning" size="sm">
                          {t('measurement_book.n_unchecked', { defaultValue: '{{n}} unchecked', n: p.unchecked_count })}
                        </Badge>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

function EntryForm({ projectId, positionId, onDone }: { projectId: string; positionId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [f, setF] = useState({
    entry_date: today(),
    location: '',
    number: '',
    length: '',
    breadth: '',
    height: '',
    direct_quantity: '',
    measured_by: '',
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () => {
      const body: EntryInput = { project_id: projectId, boq_position_id: positionId, entry_date: f.entry_date };
      (['location', 'number', 'length', 'breadth', 'height', 'direct_quantity', 'measured_by'] as const).forEach((k) => {
        if (f[k].trim()) body[k] = f[k].trim();
      });
      return createEntry(body);
    },
    onSuccess: () => {
      setF({ ...f, location: '', number: '', length: '', breadth: '', height: '', direct_quantity: '' });
      onDone();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('measurement_book.save_failed', { defaultValue: 'Could not save' }),
        message: getErrorMessage(e),
      }),
  });
  const num = (label: string, k: keyof typeof f) => (
    <label className="flex flex-col gap-1 text-xs text-content-secondary">
      <span>{label}</span>
      <input type="number" step="any" dir="ltr" className={inputCls} value={f[k]} onChange={set(k)} />
    </label>
  );
  return (
    <Card padding="sm" data-testid="measurement-book-form">
      <div className="grid gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          <span>{t('measurement_book.f_date', { defaultValue: 'Date' })}</span>
          <input type="date" dir="ltr" className={inputCls} value={f.entry_date} onChange={set('entry_date')} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary sm:col-span-2">
          <span>{t('measurement_book.f_location', { defaultValue: 'Location' })}</span>
          <input className={inputCls} value={f.location} onChange={set('location')} />
        </label>
        {num(t('measurement_book.f_number', { defaultValue: 'No.' }), 'number')}
        {num(t('measurement_book.f_length', { defaultValue: 'Length' }), 'length')}
        {num(t('measurement_book.f_breadth', { defaultValue: 'Breadth' }), 'breadth')}
        {num(t('measurement_book.f_height', { defaultValue: 'Height' }), 'height')}
        {num(t('measurement_book.f_direct', { defaultValue: 'Or direct qty' }), 'direct_quantity')}
        <label className="flex flex-col gap-1 text-xs text-content-secondary sm:col-span-2">
          <span>{t('measurement_book.f_measured_by', { defaultValue: 'Measured by' })}</span>
          <input className={inputCls} value={f.measured_by} onChange={set('measured_by')} />
        </label>
      </div>
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('measurement_book.f_hint', {
          defaultValue: 'Empty dimensions count as 1. A direct quantity replaces the multiplication.',
        })}
      </p>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" size="sm" disabled={!f.entry_date || m.isPending} onClick={() => m.mutate()}>
          {t('measurement_book.add_entry', { defaultValue: 'Add entry' })}
        </Button>
      </div>
    </Card>
  );
}

function PositionDetail({ projectId, position, onBack }: { projectId: string; position: PositionSummary; onBack: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const q = useQuery({
    queryKey: ['measurement-book', 'entries', projectId, position.boq_position_id],
    queryFn: () => fetchEntries(projectId, position.boq_position_id),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['measurement-book'] });
  const onError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('measurement_book.save_failed', { defaultValue: 'Could not save' }),
      message: getErrorMessage(e),
    });
  const check = useMutation({
    mutationFn: (v: { id: string; status: CheckStatus; qty?: string }) =>
      checkEntry(v.id, { status: v.status, ...(v.qty ? { check_quantity: v.qty } : {}) }),
    onSuccess: refresh,
    onError,
  });
  const del = useMutation({ mutationFn: (id: string) => deleteEntry(id), onSuccess: refresh, onError });

  const doCheck = (id: string, status: CheckStatus, quantity: string) => {
    let qty: string | undefined;
    if (status === 'checked') {
      const answer = window.prompt(
        t('measurement_book.check_prompt', { defaultValue: 'Checked quantity (leave empty to accept the measured quantity)' }),
        quantity,
      );
      if (answer === null) return;
      qty = answer.trim() || undefined;
    }
    check.mutate({ id, status, qty });
  };

  const rows = q.data ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} className="rtl:rotate-180" />} onClick={onBack}>
          {t('measurement_book.back', { defaultValue: 'All positions' })}
        </Button>
        <h2 className="text-sm font-semibold text-content-primary">
          <span dir="ltr">{position.ordinal}</span> {position.description}
        </h2>
        <span className="text-xs text-content-tertiary" dir="ltr">
          {position.measured_quantity} / {position.boq_quantity} {position.unit}
        </span>
      </div>
      <EntryForm projectId={projectId} positionId={position.boq_position_id} onDone={refresh} />
      {q.isLoading ? (
        <SkeletonTable rows={4} columns={6} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Ruler size={28} />}
          title={t('measurement_book.no_entries', { defaultValue: 'No entries yet' })}
          description={t('measurement_book.no_entries_desc', { defaultValue: 'Add the first measured line above.' })}
        />
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-2xs uppercase text-content-tertiary">
                  <th className="px-3 py-2 text-start">{t('measurement_book.f_date', { defaultValue: 'Date' })}</th>
                  <th className="px-3 py-2 text-start">{t('measurement_book.f_location', { defaultValue: 'Location' })}</th>
                  <th className="px-3 py-2 text-end">{t('measurement_book.f_number', { defaultValue: 'No.' })}</th>
                  <th className="px-3 py-2 text-end">{t('measurement_book.f_length', { defaultValue: 'Length' })}</th>
                  <th className="px-3 py-2 text-end">{t('measurement_book.f_breadth', { defaultValue: 'Breadth' })}</th>
                  <th className="px-3 py-2 text-end">{t('measurement_book.f_height', { defaultValue: 'Height' })}</th>
                  <th className="px-3 py-2 text-end">{t('measurement_book.col_quantity', { defaultValue: 'Quantity' })}</th>
                  <th className="px-3 py-2 text-start">{t('measurement_book.f_measured_by', { defaultValue: 'Measured by' })}</th>
                  <th className="px-3 py-2 text-start">{t('measurement_book.col_status', { defaultValue: 'Status' })}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="border-b border-border-light" data-testid="measurement-book-entry">
                    <td className="px-3 py-2 tabular-nums" dir="ltr">{e.entry_date}</td>
                    <td className="px-3 py-2">{e.location ?? ''}</td>
                    <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{e.number ?? ''}</td>
                    <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{e.length ?? ''}</td>
                    <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{e.breadth ?? ''}</td>
                    <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{e.height ?? ''}</td>
                    <td className="px-3 py-2 text-end font-medium tabular-nums" dir="ltr">
                      {e.quantity}
                      {e.check_quantity != null && e.check_quantity !== e.quantity && (
                        <span className="ms-1 text-2xs text-content-tertiary">({e.check_quantity})</span>
                      )}
                    </td>
                    <td className="px-3 py-2">{e.measured_by ?? ''}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={e.check_status} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" icon={<Check size={13} />} onClick={() => doCheck(e.id, 'checked', e.quantity)}>
                          {t('measurement_book.check', { defaultValue: 'Check' })}
                        </Button>
                        <Button variant="ghost" size="sm" icon={<X size={13} />} onClick={() => doCheck(e.id, 'disputed', e.quantity)}>
                          {t('measurement_book.dispute', { defaultValue: 'Dispute' })}
                        </Button>
                        <button
                          type="button"
                          className="p-1.5 text-content-tertiary hover:text-semantic-error"
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          onClick={() => del.mutate(e.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function RunningBillTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [label, setLabel] = useState('');
  const q = useQuery({ queryKey: ['measurement-book', 'bill', projectId], queryFn: () => fetchRunningBill(projectId) });
  const send = useMutation({
    mutationFn: () => postToProgress(projectId, label.trim()),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('measurement_book.sent', { defaultValue: 'Sent to progress' }),
        message: t('measurement_book.sent_detail', {
          defaultValue: '{{recorded}} recorded, {{skipped}} skipped',
          recorded: r.recorded,
          skipped: r.skipped,
        }),
      });
      qc.invalidateQueries({ queryKey: ['measurement-book'] });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('measurement_book.send_failed', { defaultValue: 'Could not send to progress' }),
        message: getErrorMessage(e),
      }),
  });
  if (q.isLoading) return <SkeletonTable rows={4} columns={5} />;
  const bill = q.data;
  if (!bill || bill.lines.length === 0) {
    return (
      <EmptyState
        icon={<Ruler size={28} />}
        title={t('measurement_book.bill_empty', { defaultValue: 'Nothing measured yet' })}
        description={t('measurement_book.bill_empty_desc', { defaultValue: 'Positions with entries appear here.' })}
      />
    );
  }
  return (
    <div className="space-y-4">
      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-2xs uppercase text-content-tertiary">
                <th className="px-3 py-2 text-start">{t('measurement_book.col_ordinal', { defaultValue: 'No.' })}</th>
                <th className="px-3 py-2 text-start">{t('measurement_book.col_description', { defaultValue: 'Description' })}</th>
                <th className="px-3 py-2 text-end">{t('measurement_book.col_checked', { defaultValue: 'Checked' })}</th>
                <th className="px-3 py-2 text-end">{t('measurement_book.col_rate', { defaultValue: 'Unit rate' })}</th>
                <th className="px-3 py-2 text-end">{t('measurement_book.col_value', { defaultValue: 'Value to date' })}</th>
              </tr>
            </thead>
            <tbody>
              {bill.lines.map((l) => (
                <tr key={l.boq_position_id} className="border-b border-border-light">
                  <td className="px-3 py-2 tabular-nums" dir="ltr">{l.ordinal}</td>
                  <td className="px-3 py-2">{l.description}</td>
                  <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{l.checked_quantity} {l.unit}</td>
                  <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{l.unit_rate}</td>
                  <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{l.value_to_date}</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="px-3 py-2" colSpan={4}>{t('measurement_book.total', { defaultValue: 'Total' })}</td>
                <td className="px-3 py-2 text-end tabular-nums" dir="ltr">{bill.total_value} {bill.currency}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
      {bill.unchecked_count > 0 && (
        <p className="text-xs text-semantic-warning">
          {t('measurement_book.unchecked_block', {
            defaultValue: '{{n}} entries are not checked yet. Check them before sending to progress.',
            n: bill.unchecked_count,
          })}
        </p>
      )}
      <Card padding="sm">
        <p className="text-xs text-content-tertiary">
          {t('measurement_book.send_explainer', {
            defaultValue:
              'Sending records the checked quantities as progress for this period. Progress claims then pick them up with the existing populate-from-progress step.',
          })}
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            <span>{t('measurement_book.period_label', { defaultValue: 'Period label' })}</span>
            <input className={inputCls} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="2026-10" dir="ltr" />
          </label>
          <Button variant="primary" size="sm" disabled={!label.trim() || send.isPending} onClick={() => send.mutate()}>
            {t('measurement_book.send', { defaultValue: 'Send to progress' })}
          </Button>
          <Link to="/progress" className="text-xs text-oe-blue hover:underline">
            {t('measurement_book.open_progress', { defaultValue: 'Open progress' })}
          </Link>
        </div>
      </Card>
    </div>
  );
}

export function MeasurementBookPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const [tab, setTab] = useState<'positions' | 'bill'>('positions');
  const [selected, setSelected] = useState<PositionSummary | null>(null);
  const posQ = useQuery({
    queryKey: ['measurement-book', 'positions', projectId],
    queryFn: () => fetchPositions(projectId),
    enabled: !!projectId,
  });
  const rows = posQ.data ?? [];
  const tabCls = (on: boolean) =>
    `border-b-2 px-3 py-2 text-sm font-medium ${on ? 'border-oe-blue text-oe-blue-text' : 'border-transparent text-content-tertiary hover:text-content-primary'}`;

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('measurement_book.title', { defaultValue: 'Measurement book' })}
        subtitle={t('measurement_book.subtitle', {
          defaultValue: 'Measured quantities per BOQ position, checked by a second person, ready for the running bill.',
        })}
      />
      <Explainer />
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : (
        <>
          <ValidationPanel projectId={projectId} />
          <div className="flex gap-1 border-b border-border-light">
            <button type="button" className={tabCls(tab === 'positions')} onClick={() => setTab('positions')}>
              {t('measurement_book.tab_positions', { defaultValue: 'Positions' })}
            </button>
            <button type="button" className={tabCls(tab === 'bill')} onClick={() => setTab('bill')}>
              {t('measurement_book.tab_bill', { defaultValue: 'Running bill' })}
            </button>
          </div>
          {tab === 'bill' ? (
            <RunningBillTab projectId={projectId} />
          ) : selected ? (
            <PositionDetail projectId={projectId} position={selected} onBack={() => setSelected(null)} />
          ) : posQ.isLoading ? (
            <SkeletonTable rows={5} columns={6} />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Ruler size={28} />}
              title={t('measurement_book.empty_title', { defaultValue: 'No BOQ positions yet' })}
              description={t('measurement_book.empty_desc', { defaultValue: 'Add positions to a bill of quantities first, then measure them here.' })}
            />
          ) : (
            <PositionsTable rows={rows} onOpen={setSelected} />
          )}
        </>
      )}
    </div>
  );
}
