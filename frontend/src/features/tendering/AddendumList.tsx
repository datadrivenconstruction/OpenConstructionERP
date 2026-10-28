// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Addendum panel for a tender package — mirrors integrated 5D estimating
 * suite and construction CDE platform mid-tender clarifications. Lists
 * revisions oldest → newest, exposes a
 * "Publish" action on drafts, and surfaces a bidder ack chip for each
 * record so the buyer can see at a glance who has acknowledged what.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  Megaphone,
  Plus,
  Send,
  CheckCircle2,
  Clock,
  Check,
  Trash2,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import {
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { formatDateValue, getIntlLocale, fmtList } from '@/shared/lib/formatters';
import { TenderTimeline } from './TenderTimeline';
import {
  type Addendum,
  type AddendumBoqChange,
  type AddendumDocumentChange,
  type BoqChangeOp,
  type Recipient,
  getAddendaValidation,
  listRecipients,
  type BidderSummary,
  acknowledgeAddendum,
  createAddendum,
  listAddenda,
  listPackageBidders,
  publishAddendum,
} from './api';

interface Props {
  packageId: string;
}

function formatDate(value: string | null): string {
  if (!value) return '';
  try {
    return new Intl.DateTimeFormat(getIntlLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

interface BoqDraftRow {
  op: BoqChangeOp;
  ordinal: string;
  description: string;
  unit: string;
  quantity_before: string;
  quantity_after: string;
}

interface DocDraftRow {
  drawing_number: string;
  title: string;
  revision: string;
}

const emptyBoqRow = (): BoqDraftRow => ({
  op: 'change',
  ordinal: '',
  description: '',
  unit: '',
  quantity_before: '',
  quantity_after: '',
});

const miniCls =
  'h-8 w-full min-w-0 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 disabled:opacity-40';

function patchRow<T>(set: (fn: (rows: T[]) => T[]) => void, index: number, patch: Partial<T>) {
  set((rows) => rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
}

function toBoqChange(r: BoqDraftRow): AddendumBoqChange {
  return {
    op: r.op,
    ordinal: r.ordinal.trim(),
    description: r.description.trim(),
    unit: r.unit.trim(),
    ...(r.op !== 'add' && r.quantity_before.trim() ? { quantity_before: r.quantity_before.trim() } : {}),
    ...(r.op !== 'delete' && r.quantity_after.trim() ? { quantity_after: r.quantity_after.trim() } : {}),
  };
}

const OP_TONE: Record<BoqChangeOp, string> = {
  add: 'text-semantic-success',
  change: 'text-semantic-warning',
  delete: 'text-semantic-error',
};

/** What the addendum changes: BOQ diff, moved deadline, documents. Rendered only for the parts present. */
export function AddendumChanges({ addendum }: { addendum: Addendum }) {
  const { t } = useTranslation();
  const boq = addendum.boq_changes ?? [];
  const docs = addendum.document_changes ?? [];
  const opLabel: Record<BoqChangeOp, string> = {
    add: t('tendering.addendum.op_add', { defaultValue: 'Add' }),
    change: t('tendering.addendum.op_change', { defaultValue: 'Change' }),
    delete: t('tendering.addendum.op_delete', { defaultValue: 'Delete' }),
  };
  const qty = (v: number | string | null | undefined) => (v === null || v === undefined || v === '' ? '-' : String(v));
  const movedDeadline = addendum.new_deadline
    ? t('tendering.addendum.deadline_moved', {
        defaultValue: 'Deadline moved: {{from}} to {{to}}',
        from: addendum.previous_deadline ? formatDateValue(addendum.previous_deadline, { dateStyle: 'medium' }) : '-',
        to: formatDateValue(addendum.new_deadline, { dateStyle: 'medium' }),
      })
    : '';
  if (!boq.length && !docs.length && !movedDeadline) return null;
  return (
    <div className="mt-2 space-y-2" data-testid="addendum-changes">
      {movedDeadline && (
        <p className="text-xs font-medium text-semantic-warning" data-testid="addendum-deadline-moved">
          {movedDeadline}
        </p>
      )}
      {boq.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
              {t('tendering.addendum.boq_changes', { defaultValue: 'Bill of quantities changes' })}
            </span>
            {addendum.boq_revision_no != null && (
              <Badge variant="blue" size="sm">
                {t('tendering.addendum.boq_revision', { defaultValue: 'BOQ rev {{n}}', n: addendum.boq_revision_no })}
              </Badge>
            )}
          </div>
          <table className="w-full text-xs" data-testid="addendum-boq-diff">
            <tbody>
              {boq.map((c, i) => (
                <tr key={`${c.ordinal}-${i}`} data-op={c.op} className="border-t border-border-light">
                  <td className={`py-1 pr-2 font-medium ${OP_TONE[c.op]}`}>{opLabel[c.op]}</td>
                  <td className="py-1 pr-2 tabular-nums text-content-secondary">{c.ordinal}</td>
                  <td className="py-1 pr-2 text-content-primary">{c.description}</td>
                  <td className="py-1 pr-2 text-content-tertiary">{c.unit}</td>
                  <td className="py-1 text-right tabular-nums text-content-primary">
                    {qty(c.quantity_before)} {'->'} {qty(c.quantity_after)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {docs.length > 0 && (
        <ul className="space-y-0.5 text-xs" data-testid="addendum-documents">
          {docs.map((d, i) => (
            <li key={`${d.drawing_number ?? ''}-${i}`} className="flex flex-wrap items-center gap-2 text-content-secondary">
              <FileText size={11} />
              {d.drawing_number && <span className="tabular-nums">{d.drawing_number}</span>}
              <span className="text-content-primary">{d.title}</span>
              {d.revision && <span>{d.revision}</span>}
              {d.superseded && (
                <Badge variant="warning" size="sm">
                  {t('tendering.addendum.superseded', { defaultValue: 'Superseded' })}
                </Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CreateAddendumDialog({
  packageId,
  onClose,
  onCreated,
}: {
  packageId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [newDeadline, setNewDeadline] = useState('');
  const [boqRows, setBoqRows] = useState<BoqDraftRow[]>([]);
  const [docRows, setDocRows] = useState<DocDraftRow[]>([]);

  const mutation = useMutation({
    mutationFn: () => {
      const boq_changes = boqRows.filter((r) => r.ordinal.trim()).map(toBoqChange);
      const document_changes = docRows
        .filter((r) => r.title.trim() || r.drawing_number.trim())
        .map<AddendumDocumentChange>((r) => ({
          drawing_number: r.drawing_number.trim(),
          title: r.title.trim() || r.drawing_number.trim(),
          revision: r.revision.trim(),
        }));
      return createAddendum(packageId, {
        title,
        body,
        ...(boq_changes.length ? { boq_changes } : {}),
        ...(document_changes.length ? { document_changes } : {}),
        ...(newDeadline ? { new_deadline: newDeadline } : {}),
      });
    },
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('tendering.addendum.created', {
          defaultValue: 'Addendum created',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.addendum.new', 'New Addendum')}
      size="lg"
      busy={mutation.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {t('tendering.addendum.create', 'Create Addendum')}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('tendering.addendum.title_label', 'Title')}
          required
        >
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder={t('tendering.addendum.title_placeholder', {
              defaultValue: 'e.g. Rebar grade clarification',
            })}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField label={t('tendering.addendum.body_label', 'Body')}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('tendering.addendum.body_placeholder', {
              defaultValue:
                'Detailed explanation of the clarification, change, or addition...',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('tendering.addendum.new_deadline', { defaultValue: 'New deadline (optional)' })}
        >
          <input
            type="date"
            value={newDeadline}
            onChange={(e) => setNewDeadline(e.target.value)}
            className={fieldCls}
            data-testid="addendum-new-deadline"
          />
        </WideModalField>
        <WideModalField label={t('tendering.addendum.boq_changes', { defaultValue: 'Bill of quantities changes' })}>
          <div className="space-y-2">
            {boqRows.map((row, i) => (
              <div key={i} className="grid grid-cols-[88px_80px_1fr_64px_80px_80px_32px] gap-1.5" data-testid="boq-draft-row">
                <select
                  value={row.op}
                  onChange={(e) => patchRow(setBoqRows, i, { op: e.target.value as BoqChangeOp })}
                  className={miniCls}
                  aria-label={t('tendering.addendum.op', { defaultValue: 'Change type' })}
                >
                  <option value="add">{t('tendering.addendum.op_add', { defaultValue: 'Add' })}</option>
                  <option value="change">{t('tendering.addendum.op_change', { defaultValue: 'Change' })}</option>
                  <option value="delete">{t('tendering.addendum.op_delete', { defaultValue: 'Delete' })}</option>
                </select>
                <input
                  className={miniCls}
                  value={row.ordinal}
                  onChange={(e) => patchRow(setBoqRows, i, { ordinal: e.target.value })}
                  placeholder={t('tendering.addendum.ordinal', { defaultValue: 'Pos.' })}
                  aria-label={t('tendering.addendum.ordinal', { defaultValue: 'Pos.' })}
                />
                <input
                  className={miniCls}
                  value={row.description}
                  onChange={(e) => patchRow(setBoqRows, i, { description: e.target.value })}
                  placeholder={t('tendering.addendum.description', { defaultValue: 'Description' })}
                  aria-label={t('tendering.addendum.description', { defaultValue: 'Description' })}
                />
                <input
                  className={miniCls}
                  value={row.unit}
                  onChange={(e) => patchRow(setBoqRows, i, { unit: e.target.value })}
                  placeholder={t('tendering.addendum.unit', { defaultValue: 'Unit' })}
                  aria-label={t('tendering.addendum.unit', { defaultValue: 'Unit' })}
                />
                <input
                  className={miniCls}
                  inputMode="decimal"
                  value={row.quantity_before}
                  disabled={row.op === 'add'}
                  onChange={(e) => patchRow(setBoqRows, i, { quantity_before: e.target.value })}
                  placeholder={t('tendering.addendum.qty_before', { defaultValue: 'Qty before' })}
                  aria-label={t('tendering.addendum.qty_before', { defaultValue: 'Qty before' })}
                />
                <input
                  className={miniCls}
                  inputMode="decimal"
                  value={row.quantity_after}
                  disabled={row.op === 'delete'}
                  onChange={(e) => patchRow(setBoqRows, i, { quantity_after: e.target.value })}
                  placeholder={t('tendering.addendum.qty_after', { defaultValue: 'Qty after' })}
                  aria-label={t('tendering.addendum.qty_after', { defaultValue: 'Qty after' })}
                />
                <button
                  type="button"
                  className="flex h-8 items-center justify-center text-content-tertiary hover:text-semantic-error"
                  onClick={() => setBoqRows((rows) => rows.filter((_, j) => j !== i))}
                  aria-label={t('common.remove', { defaultValue: 'Remove' })}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={13} />}
              onClick={() => setBoqRows((rows) => [...rows, emptyBoqRow()])}
            >
              {t('tendering.addendum.add_boq_row', { defaultValue: 'Add position change' })}
            </Button>
          </div>
        </WideModalField>
        <WideModalField label={t('tendering.addendum.documents', { defaultValue: 'Changed documents' })}>
          <div className="space-y-2">
            {docRows.map((row, i) => (
              <div key={i} className="grid grid-cols-[120px_1fr_80px_32px] gap-1.5">
                <input
                  className={miniCls}
                  value={row.drawing_number}
                  onChange={(e) => patchRow(setDocRows, i, { drawing_number: e.target.value })}
                  placeholder={t('tendering.addendum.drawing_number', { defaultValue: 'Drawing no.' })}
                  aria-label={t('tendering.addendum.drawing_number', { defaultValue: 'Drawing no.' })}
                />
                <input
                  className={miniCls}
                  value={row.title}
                  onChange={(e) => patchRow(setDocRows, i, { title: e.target.value })}
                  placeholder={t('tendering.addendum.doc_title', { defaultValue: 'Document title' })}
                  aria-label={t('tendering.addendum.doc_title', { defaultValue: 'Document title' })}
                />
                <input
                  className={miniCls}
                  value={row.revision}
                  onChange={(e) => patchRow(setDocRows, i, { revision: e.target.value })}
                  placeholder={t('tendering.addendum.doc_revision', { defaultValue: 'Revision' })}
                  aria-label={t('tendering.addendum.doc_revision', { defaultValue: 'Revision' })}
                />
                <button
                  type="button"
                  className="flex h-8 items-center justify-center text-content-tertiary hover:text-semantic-error"
                  onClick={() => setDocRows((rows) => rows.filter((_, j) => j !== i))}
                  aria-label={t('common.remove', { defaultValue: 'Remove' })}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={13} />}
              onClick={() => setDocRows((rows) => [...rows, { drawing_number: '', title: '', revision: '' }])}
            >
              {t('tendering.addendum.add_document', { defaultValue: 'Add document' })}
            </Button>
          </div>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/** "N of M acknowledged" plus the firms still outstanding. */
export function PendingFirms({ addendum, recipients }: { addendum: Addendum; recipients: Recipient[] }) {
  const { t } = useTranslation();
  const pendingIds = addendum.pending_recipient_ids ?? [];
  const total = recipients.length || pendingIds.length;
  const acked = Math.max(total - pendingIds.length, 0);
  const names = pendingIds.map((id) => recipients.find((r) => r.id === id)?.company_name ?? id.slice(0, 8));
  return (
    <div className="mt-2 text-xs" data-testid="addendum-pending">
      <span className="font-medium text-content-secondary">
        {t('tendering.addendum.n_of_m_acknowledged', {
          defaultValue: '{{n}} of {{m}} acknowledged',
          n: acked,
          m: total,
        })}
      </span>
      {names.length > 0 && (
        <span className="ml-2 text-semantic-warning">
          {t('tendering.addendum.pending_firms', { defaultValue: 'Waiting for: {{names}}', names: fmtList(names) })}
        </span>
      )}
    </div>
  );
}

/** Addenda validation: one line per rule, failures first. */
export function AddendaValidationPanel({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['tendering-addenda-validation', packageId],
    queryFn: () => getAddendaValidation(packageId),
  });
  if (!data || data.results.length === 0) return null;
  const sorted = [...data.results].sort((a, b) => Number(a.passed) - Number(b.passed));
  return (
    <Card padding="none" className="px-4 py-3" data-testid="addenda-validation">
      <h5 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <ShieldCheck size={13} />
        {t('tendering.addendum.validation', { defaultValue: 'Addenda checks' })}
      </h5>
      <ul className="space-y-1.5">
        {sorted.map((r, i) => (
          <li key={`${r.rule_id}-${r.element_ref ?? i}`} className="flex items-start gap-2 text-xs" data-passed={r.passed ? 'true' : 'false'}>
            {r.passed ? (
              <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-semantic-success" />
            ) : (
              <AlertTriangle
                size={13}
                className={`mt-0.5 shrink-0 ${r.severity === 'warning' ? 'text-semantic-warning' : 'text-semantic-error'}`}
              />
            )}
            <span className="text-content-primary">
              {r.message}
              {!r.passed && r.suggestion && <span className="ml-1 text-content-tertiary">{r.suggestion}</span>}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AddendumRow({
  addendum,
  onPublish,
  publishing,
  bidders,
  recipients,
  onAcknowledge,
  acknowledging,
}: {
  addendum: Addendum;
  onPublish: () => void;
  publishing: boolean;
  bidders: BidderSummary[];
  recipients: Recipient[];
  onAcknowledge: (bidderId: string) => void;
  acknowledging: boolean;
}) {
  const { t } = useTranslation();
  const isPublished = addendum.published_at !== null;
  const ackCount = addendum.acknowledged_by.length;

  // Bidders who have NOT yet acknowledged this addendum — the acknowledge
  // control is only meaningful for those (and only once the addendum is
  // published; a draft cannot be acknowledged, mirroring the backend guard).
  const ackedIds = new Set(addendum.acknowledged_by.map((a) => a.bidder_id));
  const pendingBidders = bidders.filter((b) => !ackedIds.has(b.id));
  const [picking, setPicking] = useState(false);

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
          <Megaphone size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-content-primary">
              {t('tendering.addendum.revision', {
                defaultValue: 'Rev {{n}}',
                n: addendum.revision_no,
              })}
            </span>
            <span className="text-sm text-content-primary truncate">
              {addendum.title}
            </span>
            {isPublished ? (
              <Badge variant="success" size="sm">
                {t('tendering.addendum.published', 'Published')}
              </Badge>
            ) : (
              <Badge variant="neutral" size="sm">
                {t('tendering.addendum.draft', 'Draft')}
              </Badge>
            )}
          </div>
          {addendum.body && (
            <p className="mt-1 text-xs text-content-secondary line-clamp-2">
              {addendum.body}
            </p>
          )}
          <AddendumChanges addendum={addendum} />
          <div className="mt-2 flex items-center flex-wrap gap-3 text-xs text-content-tertiary">
            {isPublished ? (
              <span className="inline-flex items-center gap-1">
                <Clock size={11} />
                {t('tendering.addendum.published_at', {
                  defaultValue: 'Published {{when}}',
                  when: formatDate(addendum.published_at),
                })}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1">
                <Clock size={11} />
                {formatDate(addendum.created_at)}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 size={11} />
              {t('tendering.addendum.acks', {
                defaultValue: '{{n}} acknowledgement(s)',
                n: ackCount,
              })}
            </span>
          </div>
          {isPublished && addendum.pending_recipient_ids !== undefined && (
            <PendingFirms addendum={addendum} recipients={recipients} />
          )}
          {ackCount > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {addendum.acknowledged_by.map((entry) => {
                const company = bidders.find(
                  (b) => b.id === entry.bidder_id,
                )?.company_name;
                return (
                  <span
                    key={`${entry.bidder_id}-${entry.acknowledged_at}`}
                    className="inline-flex items-center gap-1 rounded-full bg-semantic-success-bg/40 px-2 py-0.5 text-[10px] font-medium text-semantic-success"
                  >
                    <CheckCircle2 size={10} />
                    {company || entry.bidder_id.slice(0, 8)}
                  </span>
                );
              })}
            </div>
          )}

          {/* Acknowledge control — only for a published addendum that still has
              bidders who have not acknowledged it. Records the ack on behalf of
              the chosen bidder via POST /addenda/{id}/acknowledge/. */}
          {isPublished && pendingBidders.length > 0 && (
            <div className="mt-2">
              {!picking ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Check size={13} />}
                  onClick={() => setPicking(true)}
                >
                  {t('tendering.addendum.acknowledge', {
                    defaultValue: 'Acknowledge',
                  })}
                </Button>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-content-tertiary">
                    {t('tendering.addendum.acknowledge_as', {
                      defaultValue: 'Acknowledge as:',
                    })}
                  </span>
                  {pendingBidders.map((b) => (
                    <Button
                      key={b.id}
                      variant="secondary"
                      size="sm"
                      icon={<Check size={12} />}
                      loading={acknowledging}
                      onClick={() => {
                        onAcknowledge(b.id);
                        setPicking(false);
                      }}
                    >
                      {b.company_name}
                    </Button>
                  ))}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPicking(false)}
                  >
                    {t('common.cancel', 'Cancel')}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
        {!isPublished && (
          <Button
            variant="primary"
            size="sm"
            icon={<Send size={13} />}
            loading={publishing}
            onClick={onPublish}
          >
            {t('tendering.addendum.publish', 'Publish')}
          </Button>
        )}
      </div>
    </Card>
  );
}

export function AddendumList({ packageId }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);

  const {
    data: addenda,
    isLoading,
  } = useQuery({
    queryKey: ['tendering-addenda', packageId],
    queryFn: () => listAddenda(packageId),
  });

  // Bidders for this package — needed to record an acknowledgement against a
  // specific bidder and to label ack chips with company names.
  const { data: bidders } = useQuery({
    queryKey: ['tendering-package-bidders', packageId],
    queryFn: () => listPackageBidders(packageId),
  });

  const { data: recipients } = useQuery({
    queryKey: ['tendering-recipients', packageId],
    queryFn: () => listRecipients(packageId),
  });

  const publishMutation = useMutation({
    mutationFn: (addendumId: string) => publishAddendum(addendumId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['tendering-addenda', packageId],
      });
      queryClient.invalidateQueries({ queryKey: ['tendering-timeline', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-addenda-validation', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
      addToast({
        type: 'success',
        title: t('tendering.addendum.published_toast', {
          defaultValue: 'Addendum published',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const acknowledgeMutation = useMutation({
    mutationFn: ({
      addendumId,
      bidderId,
    }: {
      addendumId: string;
      bidderId: string;
    }) => acknowledgeAddendum(addendumId, bidderId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['tendering-addenda', packageId],
      });
      addToast({
        type: 'success',
        title: t('tendering.addendum.acknowledged_toast', {
          defaultValue: 'Acknowledgement recorded',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const handleCreated = () => {
    queryClient.invalidateQueries({
      queryKey: ['tendering-addenda', packageId],
    });
  };

  return (
    <div className="mt-4 space-y-3">
      <TenderTimeline packageId={packageId} />
      <AddendaValidationPanel packageId={packageId} />
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
          <Megaphone size={16} className="text-oe-blue" />
          {t('tendering.addendum.title', 'Addenda')}
        </h4>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => setShowCreate(true)}
        >
          {t('tendering.addendum.new', 'New Addendum')}
        </Button>
      </div>

      {isLoading ? (
        <Skeleton height={80} className="w-full" rounded="md" />
      ) : !addenda || addenda.length === 0 ? (
        <Card className="py-10">
          <EmptyState
            icon={<FileText size={28} strokeWidth={1.5} />}
            title={t('tendering.addendum.empty_title', {
              defaultValue: 'No addenda yet',
            })}
            description={t('tendering.addendum.empty_desc', {
              defaultValue:
                'Mid-tender clarifications go here. Bidders acknowledge each addendum before submitting.',
            })}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {addenda.map((addendum) => (
            <AddendumRow
              key={addendum.id}
              addendum={addendum}
              onPublish={() => publishMutation.mutate(addendum.id)}
              publishing={
                publishMutation.isPending &&
                publishMutation.variables === addendum.id
              }
              bidders={bidders ?? []}
              recipients={recipients ?? []}
              onAcknowledge={(bidderId) =>
                acknowledgeMutation.mutate({
                  addendumId: addendum.id,
                  bidderId,
                })
              }
              acknowledging={
                acknowledgeMutation.isPending &&
                acknowledgeMutation.variables?.addendumId === addendum.id
              }
            />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateAddendumDialog
          packageId={packageId}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
