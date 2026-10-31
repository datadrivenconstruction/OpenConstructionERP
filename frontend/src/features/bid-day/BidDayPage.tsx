// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bid day board: one screen per tender for the last hours before submission.
 *
 * Rows are trade packages, columns the quotes received for each. Every edit is
 * applied locally at once (integer-cent copy of the server maths) and replaced
 * by the server's recalculated board when it answers; the changed cells flash
 * with their delta. A stale edit comes back as a visible conflict, never a
 * silent overwrite. The suggestion is advice: the estimator chooses.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  Lock,
  Phone,
  Plus,
  Sparkles,
  Trash2,
  Unlock,
  X,
} from 'lucide-react';
import { Badge, Button, Breadcrumb, EmptyState, SkeletonTable } from '@/shared/ui';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { PresenceIndicator } from '@/features/collab_locks';
import {
  api,
  boardKey,
  useBoard,
  type Board,
  type BidQuote,
  type BidRow,
  type Channel,
  type ExclusionInput,
  type MarkupPatch,
  type PushPlan,
  type RowKind,
} from './api';
import { changedCells, countdown, parseAmount, recompute, toCents, fromCents } from './logic';

type Updater = (b: Board) => Board;

interface Conflict {
  changedBy: string;
  change: string;
}

function money(v: string | number | null | undefined, ccy: string): string {
  return formatCurrency(v ?? 0, ccy);
}

function signed(cents: number, ccy: string): string {
  const s = money(fromCents(Math.abs(cents)), ccy);
  return cents > 0 ? `+${s}` : cents < 0 ? `−${s}` : s;
}

function conflictOf(err: unknown): Conflict | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = (err.body as { detail?: { code?: string; changed_by?: string; change?: string } } | null)?.detail;
  if (!detail || detail.code !== 'stale_revision') return null;
  return { changedBy: detail.changed_by ?? '', change: detail.change ?? '' };
}

/* ── Amount cell: type a number, Enter, next row ─────────────────────── */

function focusCell(col: string, row: number) {
  const el = document.querySelector<HTMLInputElement>(`[data-bd-col="${col}"][data-bd-row="${row}"]`);
  if (el) {
    el.focus();
    el.select();
  }
}

function AmountInput({
  value,
  currency,
  col,
  row,
  disabled,
  label,
  onCommit,
}: {
  value: string;
  currency: string;
  col: string;
  row: number;
  disabled?: boolean;
  label: string;
  onCommit: (v: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parsed = parseAmount(draft);
    setDraft(null);
    if (parsed !== null && toCents(parsed) !== toCents(value)) onCommit(parsed);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === 'ArrowDown') {
      e.preventDefault();
      commit();
      focusCell(col, row + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      commit();
      focusCell(col, row - 1);
    } else if (e.key === 'Escape') {
      setDraft(null);
      (e.target as HTMLInputElement).blur();
    }
  };
  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      data-bd-col={col}
      data-bd-row={row}
      disabled={disabled}
      value={draft ?? money(value, currency)}
      onFocus={(e) => {
        setDraft(value);
        requestAnimationFrame(() => e.target.select());
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={onKey}
      className="w-full rounded border border-transparent bg-transparent px-1.5 py-1 text-right tabular-nums text-content-primary hover:border-border-light focus:border-oe-blue focus:bg-surface-primary focus:outline-none disabled:cursor-not-allowed"
    />
  );
}

function Flash({ cents, currency }: { cents: number | undefined; currency: string }) {
  if (cents === undefined || cents === 0) return null;
  return (
    <span
      className={clsx(
        'ml-1 rounded px-1 text-2xs font-semibold tabular-nums animate-pulse',
        cents < 0 ? 'bg-semantic-success-bg text-semantic-success' : 'bg-semantic-error-bg text-semantic-error',
      )}
    >
      {signed(cents, currency)}
    </span>
  );
}

/* ── Totals bar, markups, countdown ──────────────────────────────────── */

function DeadlineCountdown({ deadline }: { deadline: string | null }) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const c = countdown(deadline, now);
  if (!c) {
    return <span className="text-xs text-content-tertiary">{t('bid_day.no_deadline', { defaultValue: 'No deadline set on the tender' })}</span>;
  }
  const hh = String(c.hours).padStart(2, '0');
  const mm = String(c.minutes).padStart(2, '0');
  const ss = String(c.seconds).padStart(2, '0');
  const urgent = !c.overdue && c.totalMs < 3 * 3_600_000;
  return (
    <div
      className={clsx(
        'flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm font-semibold tabular-nums',
        c.overdue ? 'bg-semantic-error-bg text-semantic-error' : urgent ? 'bg-semantic-warning-bg text-semantic-warning' : 'bg-surface-secondary text-content-primary',
      )}
      aria-live="off"
      title={deadline ?? ''}
    >
      <Clock size={14} />
      {c.overdue
        ? t('bid_day.deadline_passed', { defaultValue: 'Deadline passed {{d}}d {{h}}:{{m}} ago', d: c.days, h: hh, m: mm })
        : t('bid_day.deadline_in', { defaultValue: '{{d}}d {{h}}:{{m}}:{{s}} to deadline', d: c.days, h: hh, m: mm, s: ss })}
    </div>
  );
}

function Figure({ label, value, accent, children }: { label: string; value: string; accent?: boolean; children?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className={clsx('tabular-nums', accent ? 'text-2xl font-bold text-content-primary' : 'text-base font-semibold text-content-primary')}>
        {value}
        {children}
      </div>
    </div>
  );
}

function MarkupInput({
  label,
  value,
  disabled,
  onCommit,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onCommit: (v: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? value;
  const commit = (v: string) => {
    setDraft(null);
    const parsed = parseAmount(v);
    if (parsed !== null && Number(parsed) !== Number(value)) onCommit(parsed);
  };
  return (
    <label className="flex items-center gap-2 text-xs text-content-secondary">
      <span className="w-16">{label}</span>
      <input
        type="range"
        min={0}
        max={25}
        step={0.5}
        disabled={disabled}
        value={Number(shown) || 0}
        aria-label={label}
        onChange={(e) => setDraft(e.target.value)}
        onMouseUp={(e) => commit((e.target as HTMLInputElement).value)}
        onTouchEnd={(e) => commit((e.target as HTMLInputElement).value)}
        onKeyUp={(e) => commit((e.target as HTMLInputElement).value)}
        className="w-28 accent-oe-blue"
      />
      <input
        type="text"
        inputMode="decimal"
        disabled={disabled}
        value={shown}
        aria-label={label}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && commit((e.target as HTMLInputElement).value)}
        className="w-14 rounded border border-border-light bg-surface-primary px-1.5 py-0.5 text-right tabular-nums"
      />
      <span>%</span>
    </label>
  );
}

/* ── Quote editor (exclusions and plugs) ─────────────────────────────── */

function QuoteEditor({
  quote,
  currency,
  disabled,
  onSave,
  onDelete,
  onClose,
}: {
  quote: BidQuote;
  currency: string;
  disabled: boolean;
  onSave: (patch: { vendor: string; note: string; exclusions: ExclusionInput[] }) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [vendor, setVendor] = useState(quote.vendor);
  const [note, setNote] = useState(quote.note);
  const [rows, setRows] = useState<ExclusionInput[]>(() => quote.exclusions.map((x) => ({ ...x })));
  const set = (i: number, patch: Partial<ExclusionInput>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const plugs = rows.reduce((a, r) => a + (r.status === 'plugged' ? toCents(r.plug_amount) : 0), 0);
  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border-light bg-surface-elevated shadow-xl"
      role="dialog"
      aria-label={t('bid_day.quote_details', { defaultValue: 'Quote details' })}
    >
      <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
        <h2 className="text-sm font-semibold text-content-primary">{t('bid_day.quote_details', { defaultValue: 'Quote details' })}</h2>
        <button type="button" onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} className="text-content-tertiary hover:text-content-primary">
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3 text-sm">
        <label className="block">
          <span className="text-xs text-content-secondary">{t('bid_day.vendor', { defaultValue: 'Vendor' })}</span>
          <input value={vendor} disabled={disabled} onChange={(e) => setVendor(e.target.value)} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5" />
        </label>
        <div className="grid grid-cols-2 gap-2 text-xs text-content-secondary">
          <div>
            {t('bid_day.as_quoted', { defaultValue: 'As quoted' })}
            <div className="text-sm font-semibold tabular-nums text-content-primary">{money(quote.as_quoted, currency)}</div>
            {quote.currency && quote.currency !== currency && (
              <div className="tabular-nums">
                {money(quote.amount, quote.currency)} × {quote.fx_rate}
              </div>
            )}
          </div>
          <div>
            {t('bid_day.adjusted', { defaultValue: 'Adjusted' })}
            <div className="text-sm font-semibold tabular-nums text-content-primary">{money(fromCents(toCents(quote.as_quoted) + plugs), currency)}</div>
          </div>
        </div>
        {quote.source_amount && toCents(quote.source_amount) !== toCents(quote.amount) && (
          <p className="text-xs text-content-tertiary">
            {t('bid_day.source_amount', { defaultValue: 'Originally received as {{amount}}', amount: money(quote.source_amount, quote.currency) })}
          </p>
        )}
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-semibold text-content-secondary">{t('bid_day.exclusions', { defaultValue: 'Exclusions and scope gaps' })}</span>
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={12} />}
              disabled={disabled}
              onClick={() => setRows((rs) => [...rs, { text: '', status: 'open', plug_amount: '0' }])}
            >
              {t('bid_day.add_exclusion', { defaultValue: 'Add' })}
            </Button>
          </div>
          {rows.length === 0 && (
            <p className="text-xs text-content-tertiary">{t('bid_day.no_exclusions', { defaultValue: 'No exclusions noted. The quote covers the full scope.' })}</p>
          )}
          <ul className="space-y-2">
            {rows.map((r, i) => (
              <li key={r.id ?? `n${i}`} className="rounded border border-border-light p-2">
                <div className="flex gap-2">
                  <input
                    value={r.text}
                    disabled={disabled}
                    placeholder={t('bid_day.exclusion_placeholder', { defaultValue: 'What the quote leaves out' })}
                    onChange={(e) => set(i, { text: e.target.value })}
                    className="flex-1 rounded border border-border-light bg-surface-primary px-2 py-1"
                  />
                  <button type="button" disabled={disabled} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} aria-label={t('common.remove', { defaultValue: 'Remove' })} className="text-content-tertiary hover:text-semantic-error">
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-xs">
                  <select
                    value={r.status}
                    disabled={disabled}
                    onChange={(e) => set(i, { status: e.target.value as ExclusionInput['status'] })}
                    className="rounded border border-border-light bg-surface-primary px-1.5 py-1"
                  >
                    <option value="open">{t('bid_day.excl_open', { defaultValue: 'Open, not resolved' })}</option>
                    <option value="plugged">{t('bid_day.excl_plugged', { defaultValue: 'Plugged with an amount' })}</option>
                    <option value="included">{t('bid_day.excl_included', { defaultValue: 'Confirmed included' })}</option>
                  </select>
                  {r.status === 'plugged' && (
                    <input
                      inputMode="decimal"
                      value={r.plug_amount}
                      disabled={disabled}
                      aria-label={t('bid_day.plug_amount', { defaultValue: 'Plug amount' })}
                      onChange={(e) => set(i, { plug_amount: e.target.value })}
                      className="w-28 rounded border border-border-light bg-surface-primary px-1.5 py-1 text-right tabular-nums"
                    />
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
        <label className="block">
          <span className="text-xs text-content-secondary">{t('bid_day.note', { defaultValue: 'Note' })}</span>
          <textarea value={note} disabled={disabled} onChange={(e) => setNote(e.target.value)} rows={3} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5" />
        </label>
      </div>
      <div className="flex items-center justify-between border-t border-border-light px-4 py-3">
        {quote.source === 'late' || quote.source === 'manual' ? (
          <Button variant="danger" size="sm" icon={<Trash2 size={14} />} disabled={disabled} onClick={onDelete}>
            {t('bid_day.delete_quote', { defaultValue: 'Remove quote' })}
          </Button>
        ) : (
          <span className="text-2xs text-content-tertiary">{t('bid_day.from_bid_management', { defaultValue: 'Received through tendering' })}</span>
        )}
        <Button
          variant="primary"
          size="sm"
          disabled={disabled}
          onClick={() =>
            onSave({
              vendor,
              note,
              exclusions: rows
                .filter((r) => r.text.trim())
                .map((r) => ({ ...r, plug_amount: parseAmount(r.plug_amount) ?? '0' })),
            })
          }
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </aside>
  );
}

/* ── Late quote form ─────────────────────────────────────────────────── */

function LateQuoteForm({
  rowName,
  currency,
  onSubmit,
  onCancel,
}: {
  rowName: string;
  currency: string;
  onSubmit: (body: { vendor: string; amount: string; currency: string; channel: Channel; note: string; exclusions: ExclusionInput[] }) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [vendor, setVendor] = useState('');
  const [amount, setAmount] = useState('');
  const [ccy, setCcy] = useState(currency);
  const [channel, setChannel] = useState<Channel>('phone');
  const [note, setNote] = useState('');
  const [excl, setExcl] = useState('');
  const parsed = parseAmount(amount);
  const ok = vendor.trim() !== '' && parsed !== null;
  const submit = () => {
    if (!ok || parsed === null) return;
    onSubmit({
      vendor: vendor.trim(),
      amount: parsed,
      currency: ccy.trim().toUpperCase(),
      channel,
      note,
      exclusions: excl
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
        .map((text) => ({ text, status: 'open' as const, plug_amount: '0' })),
    });
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true">
      <form
        className="w-full max-w-md space-y-3 rounded-xl bg-surface-elevated p-5 shadow-xl"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <h2 className="text-sm font-semibold text-content-primary">
          {t('bid_day.late_quote_title', { defaultValue: 'Late quote for {{row}}', row: rowName })}
        </h2>
        <div className="grid grid-cols-3 gap-2">
          <label className="col-span-3 text-xs text-content-secondary">
            {t('bid_day.vendor', { defaultValue: 'Vendor' })}
            <input autoFocus value={vendor} onChange={(e) => setVendor(e.target.value)} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm" />
          </label>
          <label className="col-span-2 text-xs text-content-secondary">
            {t('bid_day.amount', { defaultValue: 'Amount' })}
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-right text-sm tabular-nums" />
          </label>
          <label className="text-xs text-content-secondary">
            {t('bid_day.currency', { defaultValue: 'Currency' })}
            <input value={ccy} maxLength={3} onChange={(e) => setCcy(e.target.value)} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm uppercase" />
          </label>
        </div>
        <fieldset className="flex gap-3 text-xs text-content-secondary">
          <legend className="sr-only">{t('bid_day.channel', { defaultValue: 'Received by' })}</legend>
          {(['phone', 'email', 'other'] as Channel[]).map((c) => (
            <label key={c} className="flex items-center gap-1">
              <input type="radio" name="channel" checked={channel === c} onChange={() => setChannel(c)} />
              {t(`bid_day.channel_${c}`, { defaultValue: c === 'phone' ? 'Phone' : c === 'email' ? 'Email' : 'Other' })}
            </label>
          ))}
        </fieldset>
        <label className="block text-xs text-content-secondary">
          {t('bid_day.late_exclusions', { defaultValue: 'Exclusions, one per line' })}
          <textarea value={excl} onChange={(e) => setExcl(e.target.value)} rows={2} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs text-content-secondary">
          {t('bid_day.note', { defaultValue: 'Note' })}
          <input value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm" />
        </label>
        <p className="text-2xs text-content-tertiary">{t('bid_day.late_time_hint', { defaultValue: 'The time received is recorded as now.' })}</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" type="button" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={!ok}>
            {t('bid_day.add_quote', { defaultValue: 'Add quote' })}
          </Button>
        </div>
      </form>
    </div>
  );
}

/* ── Page ────────────────────────────────────────────────────────────── */

const REASONS: Record<string, string> = {
  lowest_adjusted: 'lowest adjusted price',
  single_quote: 'only one quote',
  competitive: 'three or more quotes',
  clear_gap: 'clear gap to the next',
  close_call: 'close to the next',
  open_exclusions: 'has open exclusions',
  plugged_scope: 'scope gaps plugged',
};

export function BidDayPage() {
  const { t } = useTranslation();
  const { tenderId } = useParams<{ tenderId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { data: board, isLoading, error, refetch } = useBoard(tenderId);
  const key = boardKey(tenderId ?? '');

  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [lateFor, setLateFor] = useState<BidRow | null>(null);
  const [freezeOpen, setFreezeOpen] = useState(false);
  const [freezeNote, setFreezeNote] = useState('');
  const [newRow, setNewRow] = useState<{ name: string; kind: RowKind; plug: string } | null>(null);
  const [push, setPush] = useState<{ snapshotId: string; plan: PushPlan } | null>(null);
  const [busy, setBusy] = useState(false);

  // Flash every figure that moved, with its delta, for a few seconds.
  const prevRef = useRef<Board | undefined>(undefined);
  const [flash, setFlash] = useState<Map<string, number>>(new Map());
  useEffect(() => {
    if (!board) return undefined;
    const diff = changedCells(prevRef.current, board);
    prevRef.current = board;
    if (diff.size === 0) return undefined;
    setFlash(diff);
    const id = window.setTimeout(() => setFlash(new Map()), 2600);
    return () => window.clearTimeout(id);
  }, [board]);

  const run = useCallback(
    async (optimistic: Updater | null, call: (b: Board) => Promise<Board>) => {
      const prev = qc.getQueryData<Board>(key);
      if (!prev) return;
      if (optimistic) qc.setQueryData<Board>(key, recompute(optimistic(prev)));
      try {
        const next = await call(prev);
        qc.setQueryData<Board>(key, next);
        setConflict(null);
      } catch (err) {
        qc.setQueryData<Board>(key, prev);
        const c = conflictOf(err);
        if (c) {
          setConflict(c);
          void refetch();
        } else {
          addToast({ type: 'error', title: t('bid_day.save_failed', { defaultValue: 'Change not saved' }), message: getErrorMessage(err) });
        }
      }
    },
    [qc, key, refetch, addToast, t],
  );

  const frozen = board?.status === 'frozen';
  const ccy = board?.currency ?? '';
  const maxQuotes = useMemo(() => Math.max(1, ...(board?.rows.map((r) => r.quotes.length) ?? [1])), [board]);
  const findingsByRef = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of board?.findings ?? []) if (f.element_ref) m.set(f.element_ref, (m.get(f.element_ref) ?? 0) + 1);
    return m;
  }, [board]);

  if (isLoading) return <SkeletonTable rows={6} columns={5} />;
  if (error || !board) {
    return (
      <EmptyState
        title={t('bid_day.load_failed', { defaultValue: 'The bid day board could not be opened' })}
        description={getErrorMessage(error)}
      />
    );
  }

  const editingQuote = editing ? board.rows.flatMap((r) => r.quotes).find((q) => q.id === editing) : undefined;
  const tot = board.totals;
  const errors = board.findings.filter((f) => f.severity === 'error');
  const warnings = board.findings.filter((f) => f.severity !== 'error');
  const deltaSnap = tot.delta_vs_snapshot === null ? null : toCents(tot.delta_vs_snapshot);

  const setQuoteAmount = (row: BidRow, q: BidQuote, amount: string) =>
    run(
      (b) => ({ ...b, rows: b.rows.map((r) => (r.id !== row.id ? r : { ...r, quotes: r.quotes.map((x) => (x.id === q.id ? { ...x, amount } : x)) })) }),
      (b) => api.updateQuote(b.id, q.id, { amount, rev: q.rev }),
    );
  const setPlug = (row: BidRow, plug: string) =>
    run(
      (b) => ({ ...b, rows: b.rows.map((r) => (r.id === row.id ? { ...r, plug_amount: plug } : r)) }),
      (b) => api.updateRow(b.id, row.id, { plug_amount: plug, rev: row.rev }),
    );
  const choose = (row: BidRow, quoteId: string | null) =>
    run(
      (b) => ({ ...b, rows: b.rows.map((r) => (r.id === row.id ? { ...r, chosen_quote_id: quoteId } : r)) }),
      (b) => api.choose(b.id, row.id, quoteId, row.rev),
    );
  const setMarkup = (field: 'overhead_pct' | 'risk_pct' | 'profit_pct', v: string) =>
    run(
      (b) => ({ ...b, [field]: v }),
      (b) => {
        const patch: MarkupPatch = { rev: b.markup_rev };
        patch[field] = v;
        return api.setMarkups(b.id, patch);
      },
    );

  const doFreeze = async () => {
    setBusy(true);
    try {
      const next = await api.freeze(board.id, freezeNote);
      qc.setQueryData<Board>(key, next);
      setFreezeOpen(false);
      setFreezeNote('');
      addToast({ type: 'success', title: t('bid_day.frozen_toast', { defaultValue: 'Bid frozen and recorded as submitted' }) });
    } catch (err) {
      addToast({ type: 'error', title: t('bid_day.freeze_failed', { defaultValue: 'Not submitted' }), message: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const previewPush = async (snapshotId: string) => {
    try {
      setPush({ snapshotId, plan: await api.push(board.id, snapshotId, true) });
    } catch (err) {
      addToast({ type: 'error', title: t('bid_day.push_failed', { defaultValue: 'Could not prepare the estimate update' }), message: getErrorMessage(err) });
    }
  };
  const applyPush = async () => {
    if (!push) return;
    setBusy(true);
    try {
      await api.push(board.id, push.snapshotId, false);
      setPush(null);
      void refetch();
      addToast({ type: 'success', title: t('bid_day.pushed_toast', { defaultValue: 'Chosen quotes written into the estimate' }) });
    } catch (err) {
      addToast({ type: 'error', title: t('bid_day.push_failed', { defaultValue: 'Could not prepare the estimate update' }), message: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-content space-y-4 pb-16">
      <Breadcrumb
        items={[
          { label: t('tendering.title', { defaultValue: 'Tendering' }), to: '/tendering' },
          { label: board.tender_name },
          { label: t('bid_day.title', { defaultValue: 'Bid day' }) },
        ]}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-content-primary">
            {t('bid_day.heading', { defaultValue: 'Bid day: {{name}}', name: board.tender_name })}
          </h1>
          {frozen ? (
            <Badge variant="purple">{t('bid_day.status_frozen', { defaultValue: 'Submitted' })}</Badge>
          ) : (
            <Badge variant="blue">{t('bid_day.status_open', { defaultValue: 'Live' })}</Badge>
          )}
          <PresenceIndicator entityType="tender_package" entityId={board.tender_id} />
        </div>
        <DeadlineCountdown deadline={board.deadline} />
      </div>

      {conflict && (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-semantic-warning bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
          <div className="flex-1">
            {t('bid_day.conflict', {
              defaultValue: 'Not saved: {{who}} changed this first ({{change}}). The board now shows their figure; enter yours again if it should still apply.',
              who: conflict.changedBy || t('bid_day.someone', { defaultValue: 'someone else' }),
              change: conflict.change,
            })}
          </div>
          <button type="button" onClick={() => setConflict(null)} aria-label={t('common.close', { defaultValue: 'Close' })}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Totals stay in view while the estimator scrolls the packages. */}
      <section className="sticky top-0 z-30 rounded-xl border border-border-light bg-surface-elevated/95 p-4 shadow-sm backdrop-blur">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
          <Figure label={t('bid_day.direct_cost', { defaultValue: 'Direct cost' })} value={money(tot.direct, ccy)} />
          <Figure label={t('bid_day.markup', { defaultValue: 'Markup' })} value={money(tot.markup, ccy)} />
          <Figure label={t('bid_day.bid_total', { defaultValue: 'Bid total' })} value={money(tot.bid_total, ccy)} accent>
            <Flash cents={flash.get('total')} currency={ccy} />
          </Figure>
          <Figure
            label={t('bid_day.vs_snapshot', { defaultValue: 'Since last submission' })}
            value={deltaSnap === null ? t('bid_day.no_snapshot', { defaultValue: 'none yet' }) : signed(deltaSnap, ccy)}
          />
          <Figure label={t('bid_day.estimate', { defaultValue: 'Estimate' })} value={money(tot.estimate_total, ccy)} />
          <Figure label={t('bid_day.vs_estimate', { defaultValue: 'Direct vs estimate' })} value={signed(toCents(tot.vs_estimate), ccy)} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border-light pt-3">
          <MarkupInput label={t('bid_day.overhead', { defaultValue: 'Overhead' })} value={board.overhead_pct} disabled={frozen} onCommit={(v) => setMarkup('overhead_pct', v)} />
          <MarkupInput label={t('bid_day.risk', { defaultValue: 'Risk' })} value={board.risk_pct} disabled={frozen} onCommit={(v) => setMarkup('risk_pct', v)} />
          <MarkupInput label={t('bid_day.profit', { defaultValue: 'Profit' })} value={board.profit_pct} disabled={frozen} onCommit={(v) => setMarkup('profit_pct', v)} />
          <div className="ml-auto flex gap-2">
            {frozen ? (
              <Button variant="secondary" size="sm" icon={<Unlock size={14} />} onClick={() => run(null, (b) => api.reopen(b.id))}>
                {t('bid_day.reopen', { defaultValue: 'Reopen for a revised bid' })}
              </Button>
            ) : (
              <Button variant="primary" size="sm" icon={<Lock size={14} />} onClick={() => setFreezeOpen(true)}>
                {t('bid_day.freeze', { defaultValue: 'Freeze and submit' })}
              </Button>
            )}
          </div>
        </div>
      </section>

      {(errors.length > 0 || warnings.length > 0) && (
        <section className="rounded-lg border border-border-light bg-surface-primary p-3">
          <h2 className="mb-1 text-xs font-semibold text-content-secondary">
            {t('bid_day.checks', { defaultValue: 'Checks: {{errors}} to fix, {{warnings}} to review', errors: errors.length, warnings: warnings.length })}
          </h2>
          <ul className="max-h-32 space-y-0.5 overflow-y-auto text-xs">
            {[...errors, ...warnings].map((f, i) => (
              <li key={`${f.rule_id}-${i}`} className={clsx('flex items-start gap-1.5', f.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary')}>
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                {t(`bid_day.rule.${f.rule_id}`, { defaultValue: f.message, ...f.details })}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_18rem]">
        <section className="overflow-x-auto rounded-xl border border-border-light bg-surface-primary">
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="bg-surface-secondary text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">{t('bid_day.col_package', { defaultValue: 'Package' })}</th>
                <th className="w-36 px-3 py-2 text-right">{t('bid_day.col_estimate', { defaultValue: 'Estimate (plug)' })}</th>
                {Array.from({ length: maxQuotes }, (_, i) => (
                  <th key={i} className="w-48 px-3 py-2">{t('bid_day.col_quote', { defaultValue: 'Quote {{n}}', n: i + 1 })}</th>
                ))}
                <th className="w-40 px-3 py-2 text-right">{t('bid_day.col_in_bid', { defaultValue: 'In bid' })}</th>
              </tr>
            </thead>
            <tbody>
              {board.rows.map((row, ri) => (
                <tr key={row.id} className="border-t border-border-light align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium text-content-primary">{row.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1 text-2xs text-content-tertiary">
                      {t(`bid_day.kind_${row.kind}`, { defaultValue: row.kind === 'material' ? 'Material' : row.kind === 'other' ? 'Other' : 'Subcontract' })}
                      {(findingsByRef.get(row.id) ?? 0) > 0 && <AlertTriangle size={11} className="text-semantic-warning" />}
                    </div>
                    {row.suggestion && !row.suggestion.is_chosen && (
                      <div className="mt-1.5 rounded bg-surface-secondary px-2 py-1 text-2xs text-content-secondary">
                        <span className="inline-flex items-center gap-1 font-medium text-content-primary">
                          <Sparkles size={11} />
                          {t('bid_day.suggested', {
                            defaultValue: 'Suggested: {{vendor}} ({{pct}}% sure)',
                            vendor: row.suggestion.vendor,
                            pct: Math.round(row.suggestion.confidence * 100),
                          })}
                        </span>
                        <div>
                          {row.suggestion.reasons.map((r) => t(`bid_day.reason_${r}`, { defaultValue: REASONS[r] ?? r })).join(', ')}
                        </div>
                        {!frozen && (
                          <button type="button" className="mt-0.5 font-medium text-oe-blue hover:underline" onClick={() => choose(row, row.suggestion?.quote_id ?? null)}>
                            {t('bid_day.use_suggestion', { defaultValue: 'Choose this quote' })}
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <AmountInput
                      value={row.plug_amount}
                      currency={ccy}
                      col="plug"
                      row={ri}
                      disabled={frozen}
                      label={t('bid_day.plug_for', { defaultValue: 'Estimate figure for {{row}}', row: row.name })}
                      onCommit={(v) => setPlug(row, v)}
                    />
                    {row.chosen_quote_id && (
                      <button type="button" disabled={frozen} onClick={() => choose(row, null)} className="mt-1 block w-full text-right text-2xs text-content-tertiary hover:text-oe-blue">
                        {t('bid_day.use_estimate', { defaultValue: 'Use estimate figure' })}
                      </button>
                    )}
                  </td>
                  {Array.from({ length: maxQuotes }, (_, qi) => {
                    const q = row.quotes[qi];
                    if (!q) {
                      return (
                        <td key={qi} className="px-2 py-2">
                          {qi === row.quotes.length && !frozen && (
                            <button type="button" onClick={() => setLateFor(row)} className="flex w-full items-center justify-center gap-1 rounded border border-dashed border-border-light px-2 py-3 text-xs text-content-tertiary hover:border-oe-blue hover:text-oe-blue">
                              <Phone size={12} />
                              {t('bid_day.add_late_quote', { defaultValue: 'Late quote' })}
                            </button>
                          )}
                        </td>
                      );
                    }
                    const suggested = row.suggestion?.quote_id === q.id;
                    const differs = q.adjusted !== q.as_quoted;
                    return (
                      <td key={q.id} className="px-2 py-2">
                        <div className={clsx('rounded-lg border p-1.5', q.is_chosen ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-oe-blue' : 'border-border-light')}>
                          <div className="flex items-center justify-between gap-1">
                            <button type="button" onClick={() => setEditing(q.id)} className="truncate text-left text-xs font-medium text-content-primary hover:underline" title={q.vendor}>
                              {q.vendor}
                            </button>
                            <div className="flex shrink-0 items-center gap-1">
                              {suggested && <Sparkles size={11} className="text-oe-blue" aria-label={t('bid_day.suggested_short', { defaultValue: 'Suggested' })} />}
                              {q.channel !== 'portal' && <Badge variant="neutral" size="sm">{t(`bid_day.channel_${q.channel}`, { defaultValue: q.channel })}</Badge>}
                            </div>
                          </div>
                          <AmountInput
                            value={q.amount}
                            currency={q.currency || ccy}
                            col={`q${qi}`}
                            row={ri}
                            disabled={frozen}
                            label={t('bid_day.amount_for', { defaultValue: '{{vendor}} amount for {{row}}', vendor: q.vendor, row: row.name })}
                            onCommit={(v) => setQuoteAmount(row, q, v)}
                          />
                          <div className="flex items-center justify-between gap-1 px-1.5 text-2xs">
                            <span className={clsx('tabular-nums', differs ? 'text-content-secondary' : 'text-content-tertiary')}>
                              {differs
                                ? t('bid_day.adjusted_value', { defaultValue: 'adjusted {{v}}', v: money(q.adjusted, ccy) })
                                : t('bid_day.like_for_like', { defaultValue: 'as quoted' })}
                              <Flash cents={flash.get(`quote:${q.id}`)} currency={ccy} />
                            </span>
                            {q.open_exclusions > 0 && (
                              <button type="button" onClick={() => setEditing(q.id)} className="text-semantic-warning hover:underline">
                                {t('bid_day.open_excl_count', { defaultValue: '{{count}} open', count: q.open_exclusions })}
                              </button>
                            )}
                          </div>
                          {!frozen && !q.is_chosen && (
                            <button type="button" onClick={() => choose(row, q.id)} className="mt-1 w-full rounded px-1.5 py-0.5 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10">
                              {t('bid_day.choose', { defaultValue: 'Choose' })}
                            </button>
                          )}
                          {q.is_chosen && (
                            <div className="mt-1 flex items-center justify-center gap-1 text-2xs font-semibold text-oe-blue">
                              <CheckCircle2 size={11} />
                              {t('bid_day.chosen', { defaultValue: 'In the bid' })}
                            </div>
                          )}
                        </div>
                        {qi === row.quotes.length - 1 && qi === maxQuotes - 1 && !frozen && (
                          <button type="button" onClick={() => setLateFor(row)} className="mt-1 flex w-full items-center justify-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue">
                            <Plus size={11} />
                            {t('bid_day.add_late_quote', { defaultValue: 'Late quote' })}
                          </button>
                        )}
                      </td>
                    );
                  })}
                  <td className="px-3 py-2 text-right">
                    <div className="font-semibold tabular-nums text-content-primary">
                      {money(row.value, ccy)}
                    </div>
                    <Flash cents={flash.get(`row:${row.id}`)} currency={ccy} />
                    {toCents(row.delta_vs_plug) !== 0 && (
                      <div className={clsx('text-2xs tabular-nums', toCents(row.delta_vs_plug) < 0 ? 'text-semantic-success' : 'text-semantic-error')}>
                        {t('bid_day.vs_plug', { defaultValue: '{{d}} vs estimate', d: signed(toCents(row.delta_vs_plug), ccy) })}
                      </div>
                    )}
                    {!row.bid_package_id && row.quotes.length === 0 && !frozen && (
                      <button type="button" onClick={() => run(null, (b) => api.deleteRow(b.id, row.id))} className="mt-1 text-2xs text-content-tertiary hover:text-semantic-error">
                        {t('bid_day.remove_row', { defaultValue: 'Remove' })}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {board.rows.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-content-tertiary">
              {t('bid_day.empty', { defaultValue: 'No packages yet. Add bid packages to this tender, or add a scope here.' })}
            </p>
          )}
          {!frozen && (
            <div className="border-t border-border-light px-3 py-2">
              {newRow ? (
                <form
                  className="flex flex-wrap items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const plug = parseAmount(newRow.plug || '0') ?? '0';
                    if (!newRow.name.trim()) return;
                    void run(null, (b) => api.addRow(b.id, { name: newRow.name.trim(), kind: newRow.kind, plug_amount: plug }));
                    setNewRow(null);
                  }}
                >
                  <input autoFocus value={newRow.name} placeholder={t('bid_day.scope_name', { defaultValue: 'Scope, e.g. Ready-mix concrete' })} onChange={(e) => setNewRow({ ...newRow, name: e.target.value })} className="flex-1 rounded border border-border-light bg-surface-primary px-2 py-1 text-sm" />
                  <select value={newRow.kind} onChange={(e) => setNewRow({ ...newRow, kind: e.target.value as RowKind })} className="rounded border border-border-light bg-surface-primary px-1.5 py-1 text-sm">
                    <option value="subcontract">{t('bid_day.kind_subcontract', { defaultValue: 'Subcontract' })}</option>
                    <option value="material">{t('bid_day.kind_material', { defaultValue: 'Material' })}</option>
                    <option value="other">{t('bid_day.kind_other', { defaultValue: 'Other' })}</option>
                  </select>
                  <input inputMode="decimal" value={newRow.plug} placeholder={t('bid_day.col_estimate', { defaultValue: 'Estimate (plug)' })} onChange={(e) => setNewRow({ ...newRow, plug: e.target.value })} className="w-32 rounded border border-border-light bg-surface-primary px-2 py-1 text-right text-sm" />
                  <Button variant="primary" size="sm" type="submit">{t('bid_day.add_scope', { defaultValue: 'Add scope' })}</Button>
                  <Button variant="ghost" size="sm" type="button" onClick={() => setNewRow(null)}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
                </form>
              ) : (
                <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => setNewRow({ name: '', kind: 'material', plug: '' })}>
                  {t('bid_day.add_scope', { defaultValue: 'Add scope' })}
                </Button>
              )}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border border-border-light bg-surface-primary p-3">
            <h2 className="mb-2 text-xs font-semibold text-content-secondary">{t('bid_day.change_log', { defaultValue: 'Change log' })}</h2>
            {board.events.length === 0 ? (
              <p className="text-xs text-content-tertiary">{t('bid_day.no_changes', { defaultValue: 'No changes yet.' })}</p>
            ) : (
              <ol className="max-h-96 space-y-1.5 overflow-y-auto text-xs">
                {board.events.map((e) => (
                  <li key={e.id} className="leading-snug">
                    <span className="tabular-nums text-content-tertiary">
                      {new Date(e.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>{' '}
                    <span className="text-content-primary">{e.message}</span>
                    {e.user_name && <span className="text-content-tertiary"> · {e.user_name}</span>}
                    {toCents(e.delta) !== 0 && (
                      <span className={clsx('ml-1 tabular-nums', toCents(e.delta) < 0 ? 'text-semantic-success' : 'text-semantic-error')}>
                        {signed(toCents(e.delta), ccy)}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section className="rounded-xl border border-border-light bg-surface-primary p-3">
            <h2 className="mb-2 text-xs font-semibold text-content-secondary">{t('bid_day.submissions', { defaultValue: 'Submitted bids' })}</h2>
            {board.snapshots.length === 0 ? (
              <p className="text-xs text-content-tertiary">{t('bid_day.no_submissions', { defaultValue: 'Nothing submitted yet. "Freeze and submit" records exactly what goes in.' })}</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {board.snapshots.map((s) => (
                  <li key={s.id} className="rounded border border-border-light p-2">
                    <div className="font-semibold tabular-nums text-content-primary">{money(s.bid_total, s.currency)}</div>
                    <div className="text-content-tertiary">
                      {new Date(s.created_at).toLocaleString()} {s.submitted_by_name && `· ${s.submitted_by_name}`}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <Button variant="ghost" size="sm" icon={<Download size={12} />} onClick={() => void api.exportSnapshot(board.id, s.id, 'pdf')}>PDF</Button>
                      <Button variant="ghost" size="sm" icon={<Download size={12} />} onClick={() => void api.exportSnapshot(board.id, s.id, 'xlsx')}>Excel</Button>
                      <Button variant="ghost" size="sm" onClick={() => void previewPush(s.id)}>
                        {s.pushed_at ? t('bid_day.pushed_again', { defaultValue: 'Push to estimate again' }) : t('bid_day.push', { defaultValue: 'Push to estimate' })}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>

      {editingQuote && (
        <QuoteEditor
          key={`${editingQuote.id}-${editingQuote.rev}`}
          quote={editingQuote}
          currency={ccy}
          disabled={frozen}
          onClose={() => setEditing(null)}
          onDelete={() => {
            setEditing(null);
            void run(null, (b) => api.deleteQuote(b.id, editingQuote.id));
          }}
          onSave={(patch) => {
            setEditing(null);
            void run(
              (b) => ({
                ...b,
                rows: b.rows.map((r) => ({
                  ...r,
                  quotes: r.quotes.map((x) =>
                    x.id === editingQuote.id
                      ? { ...x, vendor: patch.vendor, note: patch.note, exclusions: patch.exclusions.map((e, i) => ({ id: e.id ?? `n${i}`, ...e })) }
                      : x,
                  ),
                })),
              }),
              (b) => api.updateQuote(b.id, editingQuote.id, { ...patch, rev: editingQuote.rev }),
            );
          }}
        />
      )}

      {lateFor && (
        <LateQuoteForm
          rowName={lateFor.name}
          currency={ccy}
          onCancel={() => setLateFor(null)}
          onSubmit={(body) => {
            const row = lateFor;
            setLateFor(null);
            void run(null, (b) => api.addQuote(b.id, row.id, body));
          }}
        />
      )}

      {freezeOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md space-y-3 rounded-xl bg-surface-elevated p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-content-primary">{t('bid_day.freeze_title', { defaultValue: 'Freeze and submit this bid?' })}</h2>
            <p className="text-sm text-content-secondary">
              {t('bid_day.freeze_body', {
                defaultValue: 'A permanent record of the chosen quotes, adjustments, markups and the total of {{total}} is stored with your name and the time. The board is locked until reopened.',
                total: money(tot.bid_total, ccy),
              })}
            </p>
            {errors.length > 0 && (
              <p className="text-xs text-semantic-error">{t('bid_day.freeze_blocked', { defaultValue: 'Fix the checks marked red first.' })}</p>
            )}
            <textarea value={freezeNote} onChange={(e) => setFreezeNote(e.target.value)} rows={2} placeholder={t('bid_day.freeze_note', { defaultValue: 'Note, e.g. submitted through the client portal' })} className="w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm" />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setFreezeOpen(false)}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
              <Button variant="primary" size="sm" icon={<Lock size={14} />} loading={busy} disabled={errors.length > 0} onClick={() => void doFreeze()}>
                {t('bid_day.freeze', { defaultValue: 'Freeze and submit' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {push && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true">
          <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl bg-surface-elevated p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-content-primary">{t('bid_day.push_title', { defaultValue: 'Write chosen quotes into the estimate' })}</h2>
            <p className="mt-1 text-xs text-content-secondary">
              {t('bid_day.push_body', { defaultValue: 'Each chosen quote, adjusted for plugged scope, is spread over its package positions in proportion to their current totals. Nothing is written until you confirm.' })}
            </p>
            <div className="mt-3 flex-1 overflow-y-auto">
              {push.plan.lines.length === 0 ? (
                <p className="text-sm text-content-tertiary">{t('bid_day.push_nothing', { defaultValue: 'No chosen quote is linked to estimate positions.' })}</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-left text-content-tertiary">
                    <tr>
                      <th className="py-1">{t('bid_day.col_package', { defaultValue: 'Package' })}</th>
                      <th>{t('bid_day.position', { defaultValue: 'Position' })}</th>
                      <th className="text-right">{t('bid_day.old_total', { defaultValue: 'Now' })}</th>
                      <th className="text-right">{t('bid_day.new_total', { defaultValue: 'New' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {push.plan.lines.map((l) => (
                      <tr key={l.position_id} className="border-t border-border-light">
                        <td className="py-1">{l.row}</td>
                        <td>{l.ordinal} {l.description}</td>
                        <td className="text-right tabular-nums">{money(l.old_total, ccy)}</td>
                        <td className="text-right tabular-nums font-medium">{money(l.new_total, ccy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {push.plan.skipped.length > 0 && (
                <p className="mt-2 text-2xs text-content-tertiary">
                  {t('bid_day.push_skipped', { defaultValue: 'Not linked to positions, left as is: {{list}}', list: push.plan.skipped.join(', ') })}
                </p>
              )}
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setPush(null)}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
              <Button variant="primary" size="sm" loading={busy} disabled={push.plan.lines.length === 0} onClick={() => void applyPush()}>
                {t('bid_day.push_confirm', { defaultValue: 'Write into estimate' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      <p className="text-center text-2xs text-content-tertiary">
        <Link to="/tendering" className="hover:underline">{t('bid_day.back', { defaultValue: 'Back to tendering' })}</Link>
      </p>
    </div>
  );
}
