// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Haul tickets: one row per truck load to or from site.
 * Tabs: tickets, daily summary, haulier invoices, weighbridge import. Verified tickets feed position actuals.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { FileDown, Plus, Truck, Upload } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  acceptInvoice,
  commitImport,
  createTicket,
  deleteTicket,
  downloadDisposalRegister,
  downloadTicketPdf,
  fetchInvoices,
  fetchSummary,
  fetchTickets,
  previewImport,
  reconcileInvoice,
  transitionTicket,
  type GroupBy,
  type HaulType,
  type ImportPreview,
  type RateBasis,
  type Ticket,
  type TicketStatus,
  type Unit,
} from './api';
import { NEXT_STATUS, STATUS_VARIANT, netTonnes, totalsOf } from './model';
import { fmtFixed } from '@/shared/lib/formatters';

type Tab = 'tickets' | 'summary' | 'invoices' | 'import';

const HAUL_TYPES: HaulType[] = ['earthworks', 'aggregates', 'concrete', 'asphalt', 'waste', 'other'];
const STATUSES: TicketStatus[] = ['issued', 'loaded', 'delivered', 'verified', 'invoiced', 'rejected'];
const GROUPS: GroupBy[] = ['day', 'haulier', 'material', 'haul_type'];
const INPUT = 'rounded border border-border bg-surface-primary px-2 py-1 text-sm';

function useLabels() {
  const { t } = useTranslation();
  const status: Record<TicketStatus, string> = {
    issued: t('haul.status_issued', { defaultValue: 'Issued' }),
    loaded: t('haul.status_loaded', { defaultValue: 'Loaded' }),
    delivered: t('haul.status_delivered', { defaultValue: 'Delivered' }),
    verified: t('haul.status_verified', { defaultValue: 'Verified' }),
    invoiced: t('haul.status_invoiced', { defaultValue: 'Invoiced' }),
    rejected: t('haul.status_rejected', { defaultValue: 'Rejected' }),
  };
  const haulType: Record<HaulType, string> = {
    earthworks: t('haul.type_earthworks', { defaultValue: 'Earthworks' }),
    aggregates: t('haul.type_aggregates', { defaultValue: 'Aggregates' }),
    concrete: t('haul.type_concrete', { defaultValue: 'Concrete' }),
    asphalt: t('haul.type_asphalt', { defaultValue: 'Asphalt' }),
    waste: t('haul.type_waste', { defaultValue: 'Waste and spoil' }),
    other: t('haul.type_other', { defaultValue: 'Other' }),
  };
  const group: Record<GroupBy, string> = {
    day: t('haul.group_day', { defaultValue: 'Day' }),
    haulier: t('haul.group_haulier', { defaultValue: 'Haulier' }),
    material: t('haul.group_material', { defaultValue: 'Material' }),
    haul_type: t('haul.group_haul_type', { defaultValue: 'Haul type' }),
  };
  return { status, haulType, group };
}

export function HaulTicketsPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [tab, setTab] = useState<Tab>('tickets');

  const tabs: { id: Tab; label: string }[] = [
    { id: 'tickets', label: t('haul.tab_tickets', { defaultValue: 'Tickets' }) },
    { id: 'summary', label: t('haul.tab_summary', { defaultValue: 'Summary' }) },
    { id: 'invoices', label: t('haul.tab_invoices', { defaultValue: 'Haulier invoices' }) },
    { id: 'import', label: t('haul.tab_import', { defaultValue: 'Weighbridge import' }) },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        srTitle={t('haul.title', { defaultValue: 'Haul tickets' })}
        subtitle={t('haul.subtitle', {
          defaultValue: 'Every truck load to or from site, weighed, signed and checked against the haulier invoice.',
        })}
        actions={
          projectId ? (
            <Button variant="secondary" size="sm" onClick={() => void downloadDisposalRegister(projectId)}>
              <FileDown size={14} className="mr-1" />
              {t('haul.disposal_register', { defaultValue: 'Disposal register' })}
            </Button>
          ) : undefined
        }
      />
      {!projectId ? (
        <EmptyState
          icon={<Truck size={28} />}
          title={t('haul.no_project_title', { defaultValue: 'Pick a project first' })}
          description={t('haul.no_project_desc', { defaultValue: 'Haul tickets belong to one project.' })}
        />
      ) : (
        <>
          <div role="tablist" className="flex gap-1 border-b border-border">
            {tabs.map((x) => (
              <button
                key={x.id}
                role="tab"
                type="button"
                aria-selected={tab === x.id}
                onClick={() => setTab(x.id)}
                className={clsx(
                  'px-3 py-2 text-sm',
                  tab === x.id ? 'border-b-2 border-oe-blue font-medium' : 'text-content-secondary',
                )}
              >
                {x.label}
              </button>
            ))}
          </div>
          {tab === 'tickets' && <TicketsTab projectId={projectId} />}
          {tab === 'summary' && <SummaryTab projectId={projectId} />}
          {tab === 'invoices' && <InvoicesTab projectId={projectId} />}
          {tab === 'import' && <ImportTab projectId={projectId} />}
        </>
      )}
    </div>
  );
}

function useActionError() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return (e: unknown) =>
    addToast({ type: 'error', title: t('haul.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) });
}

function TicketsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const labels = useLabels();
  const onError = useActionError();
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [adding, setAdding] = useState(false);

  const list = useQuery({
    queryKey: ['haul', 'tickets', projectId, status, q],
    queryFn: () => fetchTickets(projectId, { status: status || undefined, q: q || undefined }),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['haul'] });
  const move = useMutation({
    mutationFn: (a: { id: string; to: TicketStatus }) => transitionTicket(a.id, a.to),
    onSuccess: () => void refresh(),
    onError,
  });
  const remove = useMutation({ mutationFn: deleteTicket, onSuccess: () => void refresh(), onError });

  const items = list.data?.items ?? [];
  const totals = totalsOf(items);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={INPUT}
          aria-label={t('haul.filter_status', { defaultValue: 'Status' })}
        >
          <option value="">{t('haul.all_statuses', { defaultValue: 'All statuses' })}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {labels.status[s]}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className={INPUT}
          placeholder={t('haul.search', { defaultValue: 'Ticket, plate, haulier' })}
          aria-label={t('haul.search', { defaultValue: 'Ticket, plate, haulier' })}
        />
        <span className="ml-auto text-sm text-content-secondary">
          {t('haul.totals', {
            defaultValue: '{{count}} tickets, {{qty}} counted, {{amount}} amount',
            count: items.length,
            qty: fmtFixed(totals.quantity, 2),
            amount: fmtFixed(totals.amount, 2),
          })}
        </span>
        <Button size="sm" onClick={() => setAdding((v) => !v)}>
          <Plus size={14} className="mr-1" />
          {t('haul.new_ticket', { defaultValue: 'New ticket' })}
        </Button>
      </div>

      {adding && <NewTicketForm projectId={projectId} onDone={() => { setAdding(false); void refresh(); }} />}

      {list.isError ? (
        <p role="alert" className="text-sm text-semantic-error">{getErrorMessage(list.error)}</p>
      ) : items.length === 0 && !list.isLoading ? (
        <EmptyState
          icon={<Truck size={28} />}
          title={t('haul.empty_title', { defaultValue: 'No tickets yet' })}
          description={t('haul.empty_desc', { defaultValue: 'Add a ticket or import the weighbridge export.' })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-content-tertiary">
                <th className="py-1 pr-3">{t('haul.col_number', { defaultValue: 'Ticket' })}</th>
                <th className="pr-3">{t('haul.col_date', { defaultValue: 'Date' })}</th>
                <th className="pr-3">{t('haul.col_material', { defaultValue: 'Material' })}</th>
                <th className="pr-3">{t('haul.col_haulier', { defaultValue: 'Haulier' })}</th>
                <th className="pr-3 text-right">{t('haul.col_net', { defaultValue: 'Net t' })}</th>
                <th className="pr-3 text-right">{t('haul.col_amount', { defaultValue: 'Amount' })}</th>
                <th className="pr-3">{t('haul.col_status', { defaultValue: 'Status' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <TicketRow
                  key={r.id}
                  row={r}
                  statusLabel={labels.status[r.status]}
                  onMove={(to) => move.mutate({ id: r.id, to })}
                  onDelete={() => remove.mutate(r.id)}
                  statusLabels={labels.status}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TicketRow(props: {
  row: Ticket;
  statusLabel: string;
  statusLabels: Record<TicketStatus, string>;
  onMove: (to: TicketStatus) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const { row: r } = props;
  const warnings = r.findings.filter((f) => f.severity !== 'info');
  return (
    <tr className="border-b border-border-light align-top">
      <td className="py-1 pr-3">
        {r.ticket_number || '-'}
        {warnings.length > 0 && (
          <ul className="text-xs text-semantic-warning">
            {warnings.map((f) => (
              <li key={`${f.rule_id}-${f.message}`}>{f.message}</li>
            ))}
          </ul>
        )}
      </td>
      <td className="pr-3">{r.ticket_date}</td>
      <td className="pr-3">{r.material_name || '-'}</td>
      <td className="pr-3">{r.haulier_name || '-'}</td>
      <td className="pr-3 text-right tabular-nums">{r.net_t ?? '-'}</td>
      <td className="pr-3 text-right tabular-nums">{r.amount}</td>
      <td className="pr-3">
        <Badge variant={STATUS_VARIANT[r.status]}>{props.statusLabel}</Badge>
      </td>
      <td className="whitespace-nowrap text-right">
        {NEXT_STATUS[r.status].map((to) => (
          <Button key={to} variant="ghost" size="sm" onClick={() => props.onMove(to)}>
            {props.statusLabels[to]}
          </Button>
        ))}
        <Button variant="ghost" size="sm" onClick={() => void downloadTicketPdf(r.id, r.ticket_number)}>
          {t('haul.pdf', { defaultValue: 'PDF' })}
        </Button>
        {r.status !== 'invoiced' && (
          <Button variant="ghost" size="sm" onClick={props.onDelete}>
            {t('haul.delete', { defaultValue: 'Delete' })}
          </Button>
        )}
      </td>
    </tr>
  );
}

function NewTicketForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const labels = useLabels();
  const onError = useActionError();
  const [f, setF] = useState({
    ticket_number: '',
    haul_type: 'aggregates' as HaulType,
    material_name: '',
    origin: '',
    destination: '',
    haulier_name: '',
    plate: '',
    unit: 't' as Unit,
    gross: '',
    tare: '',
    loads: '1',
    rate: '',
    rate_basis: 't' as RateBasis,
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((p) => ({ ...p, [k]: e.target.value }));
  const net = netTonnes(f.gross, f.tare);
  const tareTooHigh = f.gross !== '' && f.tare !== '' && net === null;

  const save = useMutation({
    mutationFn: () =>
      createTicket({
        project_id: projectId,
        ticket_number: f.ticket_number,
        haul_type: f.haul_type,
        material_name: f.material_name,
        origin: f.origin,
        destination: f.destination,
        haulier_name: f.haulier_name,
        plate: f.plate,
        unit: f.unit,
        gross_t: f.gross || null,
        tare_t: f.tare || null,
        loads: Number(f.loads) || 1,
        rate: f.rate || null,
        rate_basis: f.rate_basis,
      }),
    onSuccess: onDone,
    onError,
  });

  const field = (k: keyof typeof f, label: string, props: { type?: string; w?: string } = {}) => (
    <label className={clsx('flex flex-col gap-1 text-xs text-content-secondary', props.w)}>
      {label}
      <input type={props.type ?? 'text'} value={f[k]} onChange={set(k)} className={INPUT} />
    </label>
  );

  return (
    <Card className="space-y-3 p-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {field('ticket_number', t('haul.col_number', { defaultValue: 'Ticket' }))}
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('haul.f_type', { defaultValue: 'Haul type' })}
          <select value={f.haul_type} onChange={set('haul_type')} className={INPUT}>
            {HAUL_TYPES.map((h) => (
              <option key={h} value={h}>
                {labels.haulType[h]}
              </option>
            ))}
          </select>
        </label>
        {field('material_name', t('haul.col_material', { defaultValue: 'Material' }))}
        {field('haulier_name', t('haul.col_haulier', { defaultValue: 'Haulier' }))}
        {field('origin', t('haul.f_origin', { defaultValue: 'From' }))}
        {field('destination', t('haul.f_destination', { defaultValue: 'To' }))}
        {field('plate', t('haul.f_plate', { defaultValue: 'Plate' }))}
        {field('loads', t('haul.f_loads', { defaultValue: 'Loads' }), { type: 'number' })}
        {field('gross', t('haul.f_gross', { defaultValue: 'Gross t' }), { type: 'number' })}
        {field('tare', t('haul.f_tare', { defaultValue: 'Tare t' }), { type: 'number' })}
        {field('rate', t('haul.f_rate', { defaultValue: 'Rate' }), { type: 'number' })}
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('haul.f_rate_basis', { defaultValue: 'Rate per' })}
          <select value={f.rate_basis} onChange={set('rate_basis')} className={INPUT}>
            <option value="t">{t('haul.basis_t', { defaultValue: 'tonne' })}</option>
            <option value="m3">{t('haul.basis_m3', { defaultValue: 'cubic metre' })}</option>
            <option value="load">{t('haul.basis_load', { defaultValue: 'load' })}</option>
            <option value="hour">{t('haul.basis_hour', { defaultValue: 'hour' })}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('haul.f_unit', { defaultValue: 'Counted in' })}
          <select value={f.unit} onChange={set('unit')} className={INPUT}>
            <option value="t">{t('haul.basis_t', { defaultValue: 'tonne' })}</option>
            <option value="m3">{t('haul.basis_m3', { defaultValue: 'cubic metre' })}</option>
            <option value="load">{t('haul.basis_load', { defaultValue: 'load' })}</option>
          </select>
        </label>
      </div>
      <div className="flex items-center gap-3 text-sm">
        <span>{t('haul.net_preview', { defaultValue: 'Net: {{net}} t', net: net ?? '-' })}</span>
        {tareTooHigh && (
          <span role="alert" className="text-semantic-error">
            {t('haul.tare_exceeds_gross', { defaultValue: 'Tare is above gross' })}
          </span>
        )}
        <Button className="ml-auto" size="sm" disabled={save.isPending || tareTooHigh} onClick={() => save.mutate()}>
          {t('haul.save', { defaultValue: 'Save ticket' })}
        </Button>
      </div>
    </Card>
  );
}

function SummaryTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const labels = useLabels();
  const [groupBy, setGroupBy] = useState<GroupBy>('day');
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const q = useQuery({
    queryKey: ['haul', 'summary', projectId, groupBy, verifiedOnly],
    queryFn: () => fetchSummary(projectId, groupBy, verifiedOnly),
  });
  const rows = q.data?.rows ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as GroupBy)}
          className={INPUT}
          aria-label={t('haul.group_by', { defaultValue: 'Group by' })}
        >
          {GROUPS.map((g) => (
            <option key={g} value={g}>
              {labels.group[g]}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} />
          {t('haul.verified_only', { defaultValue: 'Verified tickets only' })}
        </label>
      </div>
      {rows.length === 0 && !q.isLoading ? (
        <EmptyState icon={<Truck size={28} />} title={t('haul.empty_title', { defaultValue: 'No tickets yet' })} />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-content-tertiary">
              <th className="py-1">{labels.group[groupBy]}</th>
              <th className="text-right">{t('haul.sum_tickets', { defaultValue: 'Tickets' })}</th>
              <th className="text-right">{t('haul.f_loads', { defaultValue: 'Loads' })}</th>
              <th className="text-right">{t('haul.sum_tonnes', { defaultValue: 'Tonnes' })}</th>
              <th className="text-right">{t('haul.sum_volume', { defaultValue: 'm3' })}</th>
              <th className="text-right">{t('haul.col_amount', { defaultValue: 'Amount' })}</th>
            </tr>
          </thead>
          <tbody>
            {[...rows, ...(q.data ? [q.data.totals] : [])].map((r, i, all) => (
              <tr key={`${r.key}-${i}`} className={clsx('border-b border-border-light', i === all.length - 1 && 'font-medium')}>
                <td className="py-1">{i === all.length - 1 ? t('haul.sum_total', { defaultValue: 'Total' }) : r.label}</td>
                <td className="text-right tabular-nums">{r.tickets}</td>
                <td className="text-right tabular-nums">{r.loads}</td>
                <td className="text-right tabular-nums">{r.tonnes}</td>
                <td className="text-right tabular-nums">{r.volume_m3}</td>
                <td className="text-right tabular-nums">{r.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function InvoicesTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const onError = useActionError();
  const list = useQuery({ queryKey: ['haul', 'invoices', projectId], queryFn: () => fetchInvoices(projectId) });
  const done = () => void qc.invalidateQueries({ queryKey: ['haul'] });
  const reconcile = useMutation({ mutationFn: reconcileInvoice, onSuccess: done, onError });
  const accept = useMutation({ mutationFn: acceptInvoice, onSuccess: done, onError });
  const items = list.data ?? [];

  if (items.length === 0 && !list.isLoading) {
    return (
      <EmptyState
        icon={<Truck size={28} />}
        title={t('haul.inv_empty_title', { defaultValue: 'No haulier invoices' })}
        description={t('haul.inv_empty_desc', {
          defaultValue: 'Add an invoice to compare its lines with the verified tickets.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3">
      {items.map((inv) => (
        <Card key={inv.id} className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium">
              {inv.haulier_name} / {inv.invoice_number}
            </span>
            <span className="text-sm tabular-nums">
              {inv.total} {inv.currency}
            </span>
            <Badge variant={inv.status === 'accepted' ? 'success' : 'neutral'}>{inv.status}</Badge>
            <span className="ml-auto flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => reconcile.mutate(inv.id)}>
                {t('haul.inv_reconcile', { defaultValue: 'Reconcile' })}
              </Button>
              <Button size="sm" onClick={() => accept.mutate(inv.id)}>
                {t('haul.inv_accept', { defaultValue: 'Accept' })}
              </Button>
            </span>
          </div>
          {inv.findings.length > 0 && (
            <ul className="text-sm text-semantic-warning">
              {inv.findings.map((f) => (
                <li key={`${f.rule_id}-${f.message}`}>{f.message}</li>
              ))}
            </ul>
          )}
        </Card>
      ))}
    </div>
  );
}

function ImportTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const onError = useActionError();
  const [file, setFile] = useState<File | null>(null);
  const [kg, setKg] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  const doPreview = useMutation({
    mutationFn: () => previewImport(projectId, file as File, undefined, kg),
    onSuccess: setPreview,
    onError,
  });
  const doCommit = useMutation({
    mutationFn: () => commitImport(projectId, file as File, preview?.mapping ?? {}, kg),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('haul.imported', {
          defaultValue: '{{created}} tickets imported, {{skipped}} duplicates skipped',
          created: r.created,
          skipped: r.skipped_duplicates,
        }),
      });
      setPreview(null);
      setFile(null);
      void qc.invalidateQueries({ queryKey: ['haul'] });
    },
    onError,
  });

  return (
    <div className="space-y-3">
      <p className="text-sm text-content-secondary">
        {t('haul.import_hint', {
          defaultValue: 'Upload the weighbridge CSV or Excel export. Columns are matched by name; duplicates are skipped.',
        })}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPreview(null);
          }}
          aria-label={t('haul.import_file', { defaultValue: 'Weighbridge file' })}
        />
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={kg} onChange={(e) => setKg(e.target.checked)} />
          {t('haul.weights_in_kg', { defaultValue: 'Weights are in kilograms' })}
        </label>
        <Button variant="secondary" size="sm" disabled={!file || doPreview.isPending} onClick={() => doPreview.mutate()}>
          <Upload size={14} className="mr-1" />
          {t('haul.preview', { defaultValue: 'Preview' })}
        </Button>
      </div>
      {preview && (
        <Card className="space-y-2 p-3">
          <p className="text-sm">
            {t('haul.preview_summary', {
              defaultValue: '{{total}} rows, {{dups}} already imported',
              total: preview.total,
              dups: preview.duplicates,
            })}
          </p>
          <Button size="sm" disabled={doCommit.isPending || preview.total === 0} onClick={() => doCommit.mutate()}>
            {t('haul.commit', { defaultValue: 'Import tickets' })}
          </Button>
        </Card>
      )}
    </div>
  );
}
