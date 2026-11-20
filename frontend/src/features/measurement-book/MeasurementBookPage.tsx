// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measurement book: dated quantity entries per BOQ position (number x length x breadth x height,
 * or a direct quantity), a second-person check, and the running bill that feeds progress claims.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Ruler, Trash2, X } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable, WideModal } from '@/shared/ui';
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
  setPositionPercent,
  type CheckStatus,
  type EntryInput,
  type PositionSummary,
  type SectionRef,
} from './api';

const inputCls =
  'oe-input w-full';

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
      <h3 className="oe-card-title mb-2 flex items-center gap-1.5">
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

/** A table row: a section header or a measurable position. */
export type BookRow =
  | { kind: 'section'; key: string; depth: number; section: SectionRef; boqName: string }
  | { kind: 'position'; key: string; depth: number; position: PositionSummary };

/**
 * Interleave section header rows with the positions, in bill order. A header is
 * emitted whenever a position's section chain differs from the previous one at
 * that level, so subsections nest under their section.
 */
export function buildBookRows(rows: PositionSummary[]): BookRow[] {
  const out: BookRow[] = [];
  let prev: string[] = [];
  let prevBoq: string | null | undefined;
  for (const p of rows) {
    const path = p.sections ?? [];
    const ids = path.map((s) => s.id);
    if (p.boq_id !== prevBoq) prev = [];
    let same = 0;
    while (same < ids.length && same < prev.length && ids[same] === prev[same]) same += 1;
    for (let d = same; d < path.length; d += 1) {
      const section = path[d]!;
      out.push({ kind: 'section', key: `s-${section.id}-${p.boq_position_id}`, depth: d, section, boqName: p.boq_name ?? '' });
    }
    out.push({ kind: 'position', key: p.boq_position_id, depth: path.length, position: p });
    prev = ids;
    prevBoq = p.boq_id;
  }
  return out;
}

/** Slider plus number box; commits on release, Enter or blur, never while dragging. */
function PercentCell({
  position,
  disabled,
  onCommit,
}: {
  position: PositionSummary;
  disabled: boolean;
  onCommit: (percent: string) => void;
}) {
  const { t } = useTranslation();
  const stored = String(Math.round(pct(position.percent_measured) * 100) / 100);
  const [value, setValue] = useState(stored);
  useEffect(() => setValue(stored), [stored]);
  const commit = () => {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0 || value.trim() === '' || n === Number(stored)) {
      setValue(stored);
      return;
    }
    onCommit(String(n));
  };
  const label = t('measurement_book.set_percent', { defaultValue: 'Set progress %' });
  const noQty = pct(position.boq_quantity) <= 0;
  return (
    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={Math.min(100, Math.max(0, Number(value) || 0))}
        disabled={disabled || noQty}
        aria-label={label}
        title={label}
        className="h-1.5 w-24 cursor-pointer accent-oe-blue disabled:cursor-not-allowed disabled:opacity-40"
        onChange={(e) => setValue(e.target.value)}
        onPointerUp={commit}
        onKeyUp={(e) => {
          if (e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End' || e.key.startsWith('Page')) commit();
        }}
      />
      <input
        type="number"
        min={0}
        step="any"
        dir="ltr"
        value={value}
        disabled={disabled || noQty}
        aria-label={label}
        className="oe-input-sm w-16 px-1.5 text-end text-2xs tabular-nums"
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setValue(stored);
        }}
      />
      <span className="text-2xs text-content-tertiary">%</span>
    </div>
  );
}

function PositionsTable({
  rows,
  onOpen,
  onSetPercent,
  busyId,
}: {
  rows: PositionSummary[];
  onOpen: (p: PositionSummary) => void;
  onSetPercent: (p: PositionSummary, percent: string) => void;
  busyId: string | null;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="oe-table">
          <thead>
            <tr>
              <th>{t('measurement_book.col_ordinal', { defaultValue: 'No.' })}</th>
              <th>{t('measurement_book.col_description', { defaultValue: 'Description' })}</th>
              <th>{t('measurement_book.col_unit', { defaultValue: 'Unit' })}</th>
              <th className="text-end">{t('measurement_book.col_boq_qty', { defaultValue: 'BOQ qty' })}</th>
              <th className="text-end">{t('measurement_book.col_measured', { defaultValue: 'Measured' })}</th>
              <th className="text-end">{t('measurement_book.col_checked', { defaultValue: 'Checked' })}</th>
              <th>{t('measurement_book.col_percent', { defaultValue: '% measured' })}</th>
            </tr>
          </thead>
          <tbody>
            {buildBookRows(rows).map((row) => {
              if (row.kind === 'section') {
                return (
                  <tr key={row.key} className="bg-surface-secondary/60" data-testid="measurement-book-section">
                    <td
                      colSpan={7}
                      className={row.depth === 0 ? 'text-sm font-semibold text-content-primary' : 'text-[13px] font-semibold text-content-primary'}
                      style={{ paddingInlineStart: `${0.75 + row.depth * 1.25}rem` }}
                    >
                      <span className="tabular-nums" dir="ltr">{row.section.ordinal}</span> {row.section.description}
                    </td>
                  </tr>
                );
              }
              const p = row.position;
              const over = pct(p.percent_measured) > 100;
              return (
                <tr
                  key={row.key}
                  onClick={() => onOpen(p)}
                  className="cursor-pointer"
                  data-testid="measurement-book-position"
                >
                  <td className="tabular-nums" dir="ltr" style={{ paddingInlineStart: `${0.75 + row.depth * 1.25}rem` }}>
                    {p.ordinal}
                  </td>
                  <td>{p.description}</td>
                  <td>{p.unit}</td>
                  <td className="text-end tabular-nums" dir="ltr">{p.boq_quantity}</td>
                  <td className={`px-3 py-2 text-end tabular-nums ${over ? 'font-semibold text-semantic-error' : ''}`} dir="ltr">
                    {p.measured_quantity}
                  </td>
                  <td className="text-end tabular-nums" dir="ltr">{p.checked_quantity}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <PercentCell
                        position={p}
                        disabled={busyId === p.boq_position_id}
                        onCommit={(v) => onSetPercent(p, v)}
                      />
                      {over && (
                        <span className="text-2xs font-semibold tabular-nums text-semantic-error" dir="ltr">
                          {p.percent_measured}%
                        </span>
                      )}
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

function PositionDialog({ projectId, position, onClose }: { projectId: string; position: PositionSummary; onClose: () => void }) {
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
    <WideModal
      open
      onClose={onClose}
      size="full"
      title={`${position.ordinal} ${position.description}`}
      subtitle={
        <span dir="ltr">
          {position.measured_quantity} / {position.boq_quantity} {position.unit}
        </span>
      }
      testId="measurement-book-position-dialog"
    >
    <div className="space-y-4">
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
            <table className="oe-table">
              <thead>
                <tr>
                  <th>{t('measurement_book.f_date', { defaultValue: 'Date' })}</th>
                  <th>{t('measurement_book.f_location', { defaultValue: 'Location' })}</th>
                  <th className="text-end">{t('measurement_book.f_number', { defaultValue: 'No.' })}</th>
                  <th className="text-end">{t('measurement_book.f_length', { defaultValue: 'Length' })}</th>
                  <th className="text-end">{t('measurement_book.f_breadth', { defaultValue: 'Breadth' })}</th>
                  <th className="text-end">{t('measurement_book.f_height', { defaultValue: 'Height' })}</th>
                  <th className="text-end">{t('measurement_book.col_quantity', { defaultValue: 'Quantity' })}</th>
                  <th>{t('measurement_book.f_measured_by', { defaultValue: 'Measured by' })}</th>
                  <th>{t('measurement_book.col_status', { defaultValue: 'Status' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} data-testid="measurement-book-entry">
                    <td className="tabular-nums" dir="ltr">{e.entry_date}</td>
                    <td>{e.location ?? ''}</td>
                    <td className="text-end tabular-nums" dir="ltr">{e.number ?? ''}</td>
                    <td className="text-end tabular-nums" dir="ltr">{e.length ?? ''}</td>
                    <td className="text-end tabular-nums" dir="ltr">{e.breadth ?? ''}</td>
                    <td className="text-end tabular-nums" dir="ltr">{e.height ?? ''}</td>
                    <td className="text-end font-medium tabular-nums" dir="ltr">
                      {e.quantity}
                      {e.check_quantity != null && e.check_quantity !== e.quantity && (
                        <span className="ms-1 text-2xs text-content-tertiary">({e.check_quantity})</span>
                      )}
                    </td>
                    <td>{e.measured_by ?? ''}</td>
                    <td>
                      <StatusBadge status={e.check_status} />
                    </td>
                    <td>
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" icon={<Check size={14} />} onClick={() => doCheck(e.id, 'checked', e.quantity)}>
                          {t('measurement_book.check', { defaultValue: 'Check' })}
                        </Button>
                        <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={() => doCheck(e.id, 'disputed', e.quantity)}>
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
    </WideModal>
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
          <table className="oe-table">
            <thead>
              <tr>
                <th>{t('measurement_book.col_ordinal', { defaultValue: 'No.' })}</th>
                <th>{t('measurement_book.col_description', { defaultValue: 'Description' })}</th>
                <th className="text-end">{t('measurement_book.col_checked', { defaultValue: 'Checked' })}</th>
                <th className="text-end">{t('measurement_book.col_rate', { defaultValue: 'Unit rate' })}</th>
                <th className="text-end">{t('measurement_book.col_value', { defaultValue: 'Value to date' })}</th>
              </tr>
            </thead>
            <tbody>
              {bill.lines.map((l) => (
                <tr key={l.boq_position_id}>
                  <td className="tabular-nums" dir="ltr">{l.ordinal}</td>
                  <td>{l.description}</td>
                  <td className="text-end tabular-nums" dir="ltr">{l.checked_quantity} {l.unit}</td>
                  <td className="text-end tabular-nums" dir="ltr">{l.unit_rate}</td>
                  <td className="text-end tabular-nums" dir="ltr">{l.value_to_date}</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td colSpan={4}>{t('measurement_book.total', { defaultValue: 'Total' })}</td>
                <td className="text-end tabular-nums" dir="ltr">{bill.total_value} {bill.currency}</td>
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
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [boqFilter, setBoqFilter] = useState('');
  const [sectionFilter, setSectionFilter] = useState('');
  const allRows = useMemo(() => posQ.data ?? [], [posQ.data]);
  const boqs = useMemo(() => {
    const seen = new Map<string, string>();
    for (const p of allRows) if (p.boq_id && !seen.has(p.boq_id)) seen.set(p.boq_id, p.boq_name ?? '');
    return [...seen.entries()];
  }, [allRows]);
  const sectionOptions = useMemo(() => {
    const seen = new Map<string, { section: SectionRef; depth: number }>();
    for (const p of allRows) {
      if (boqFilter && p.boq_id !== boqFilter) continue;
      (p.sections ?? []).forEach((s, depth) => {
        if (!seen.has(s.id)) seen.set(s.id, { section: s, depth });
      });
    }
    return [...seen.values()];
  }, [allRows, boqFilter]);
  const rows = useMemo(
    () =>
      allRows.filter(
        (p) =>
          (!boqFilter || p.boq_id === boqFilter) &&
          (!sectionFilter || (p.sections ?? []).some((s) => s.id === sectionFilter)),
      ),
    [allRows, boqFilter, sectionFilter],
  );
  const percent = useMutation({
    mutationFn: (v: { id: string; percent: string }) => setPositionPercent(projectId, v.id, v.percent),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['measurement-book'] }),
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('measurement_book.save_failed', { defaultValue: 'Could not save' }),
        message: getErrorMessage(e),
      }),
  });
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
          {tab === 'positions' && allRows.length > 0 && (boqs.length > 1 || sectionOptions.length > 0) && (
            <div className="flex flex-wrap items-center gap-3" data-testid="measurement-book-filters">
              {boqs.length > 1 && (
                <select
                  className="oe-select w-auto"
                  value={boqFilter}
                  aria-label={t('measurement_book.filter_boq', { defaultValue: 'Contract (BOQ)' })}
                  onChange={(e) => {
                    setBoqFilter(e.target.value);
                    setSectionFilter('');
                  }}
                >
                  <option value="">{t('measurement_book.all_boqs', { defaultValue: 'All contracts (BOQs)' })}</option>
                  {boqs.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              )}
              {sectionOptions.length > 0 && (
                <select
                  className="oe-select w-auto"
                  value={sectionFilter}
                  aria-label={t('measurement_book.filter_section', { defaultValue: 'Section' })}
                  onChange={(e) => setSectionFilter(e.target.value)}
                >
                  <option value="">{t('measurement_book.all_sections', { defaultValue: 'All sections' })}</option>
                  {sectionOptions.map(({ section, depth }) => (
                    <option key={section.id} value={section.id}>
                      {`${'\u00a0\u00a0'.repeat(depth)}${section.ordinal} ${section.description}`.trimEnd()}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
          {tab === 'bill' ? (
            <RunningBillTab projectId={projectId} />
          ) : posQ.isLoading ? (
            <SkeletonTable rows={5} columns={6} />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Ruler size={28} />}
              title={t('measurement_book.empty_title', { defaultValue: 'No BOQ positions yet' })}
              description={t('measurement_book.empty_desc', { defaultValue: 'Add positions to a bill of quantities first, then measure them here.' })}
            />
          ) : (
            <PositionsTable
              rows={rows}
              onOpen={setSelected}
              onSetPercent={(p, v) => percent.mutate({ id: p.boq_position_id, percent: v })}
              busyId={percent.isPending ? (percent.variables?.id ?? null) : null}
            />
          )}
          {tab === 'positions' && selected && (
            <PositionDialog projectId={projectId} position={selected} onClose={() => setSelected(null)} />
          )}
        </>
      )}
    </div>
  );
}
