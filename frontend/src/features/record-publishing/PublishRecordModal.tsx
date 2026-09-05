// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PublishRecordModal — one-tap "publish a record and distribute it".
//
// Reusable across record kinds (daily site diary first, meetings and
// inspections next): the caller passes the source kind + id, the modal
// collects recipients (typed in, or pulled from a saved distribution list),
// then calls POST /api/v1/record-publishing/publish/. On success it turns
// into a hand-off panel that lists, per recipient, the acknowledgement link
// and the no-login record download link to forward.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Send,
  Plus,
  Trash2,
  Copy,
  Check,
  Download,
  ListChecks,
  CheckCircle2,
} from 'lucide-react';

import { Button, Badge, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchDistributionLists } from '@/features/file-distribution/api';
import {
  publishRecord,
  downloadPublishedRecord,
  type RecordKind,
  type PublishRecordResponse,
  type PublishedRecipientOut,
} from './api';

interface RecipientRow {
  email: string;
  display_name: string;
  role: string;
}

// Recipient roles mirror the distribution-member roles so a diary published to
// a saved list keeps the same intent labels the list was built with.
const ROLE_OPTIONS: { value: string; labelKey: string; fallback: string }[] = [
  { value: '', labelKey: 'record_publishing.role_unset', fallback: 'No role' },
  {
    value: 'for_review',
    labelKey: 'record_publishing.role_for_review',
    fallback: 'For review',
  },
  { value: 'fyi', labelKey: 'record_publishing.role_fyi', fallback: 'For information' },
  {
    value: 'for_construction',
    labelKey: 'record_publishing.role_for_construction',
    fallback: 'For construction',
  },
];

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function emptyRow(): RecipientRow {
  return { email: '', display_name: '', role: '' };
}

export interface PublishRecordModalProps {
  sourceKind: RecordKind;
  sourceId: string;
  projectId: string;
  /** Short human label for the record, shown in the modal subtitle. */
  subjectHint?: string;
  onClose: () => void;
  /** Fired after a successful publish so the caller can refresh its data. */
  onPublished?: (result: PublishRecordResponse) => void;
}

export function PublishRecordModal({
  sourceKind,
  sourceId,
  projectId,
  subjectHint,
  onClose,
  onPublished,
}: PublishRecordModalProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [rows, setRows] = useState<RecipientRow[]>([emptyRow()]);
  const [notes, setNotes] = useState('');
  const [result, setResult] = useState<PublishRecordResponse | null>(null);

  // Saved distribution lists let a user drop a whole named group in at once.
  // We expand the members into visible rows (rather than sending a hidden
  // list id) so the sender always sees exactly who will receive the record.
  const listsQ = useQuery({
    queryKey: ['distribution-lists', projectId],
    queryFn: () => fetchDistributionLists(projectId),
    enabled: !!projectId,
  });

  const validRecipients = useMemo(
    () =>
      rows
        .map((r) => ({
          email: r.email.trim(),
          display_name: r.display_name.trim(),
          role: r.role,
        }))
        .filter((r) => EMAIL_RE.test(r.email)),
    [rows],
  );

  const publishMut = useMutation({
    mutationFn: () =>
      publishRecord({
        source_kind: sourceKind,
        source_id: sourceId,
        recipients: validRecipients.map((r) => ({
          email: r.email,
          display_name: r.display_name || undefined,
          role: r.role || undefined,
        })),
        notes: notes.trim() || undefined,
        locale: i18n.language || undefined,
      }),
    onSuccess: (res) => {
      setResult(res);
      addToast({
        type: 'success',
        title: t('record_publishing.published_toast', {
          defaultValue: 'Published and distributed to {{count}} recipient(s)',
          count: res.recipient_count,
        }),
      });
      onPublished?.(res);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const addRow = () => setRows((prev) => [...prev, emptyRow()]);
  const removeRow = (idx: number) =>
    setRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  const patchRow = (idx: number, patch: Partial<RecipientRow>) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const addListMembers = (listId: string) => {
    const list = listsQ.data?.items.find((l) => l.id === listId);
    if (!list) return;
    setRows((prev) => {
      const seen = new Set(
        prev.map((r) => r.email.trim().toLowerCase()).filter(Boolean),
      );
      const additions: RecipientRow[] = [];
      for (const m of list.members) {
        const key = m.email.trim().toLowerCase();
        if (!key || seen.has(key)) continue;
        seen.add(key);
        additions.push({
          email: m.email,
          display_name: m.display_name ?? '',
          role: typeof m.role === 'string' ? m.role : '',
        });
      }
      if (additions.length === 0) return prev;
      // Drop a single leading empty row so the list does not start with a gap.
      const base = prev.length === 1 && !prev[0]?.email.trim() ? [] : prev;
      return [...base, ...additions];
    });
  };

  const downloadMut = useMutation({
    mutationFn: () =>
      downloadPublishedRecord(
        result!.transmittal_id,
        result!.record_filename,
      ),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* ── Success / hand-off panel ─────────────────────────────────────────── */
  if (result) {
    return (
      <WideModal
        open
        onClose={onClose}
        size="xl"
        title={t('record_publishing.done_title', {
          defaultValue: 'Record published',
        })}
        subtitle={t('record_publishing.done_subtitle', {
          defaultValue:
            'Issued as transmittal {{number}}. Each recipient can open the record and acknowledge it without logging in.',
          number: result.transmittal_number,
        })}
        footer={
          <Button variant="primary" onClick={onClose}>
            {t('common.done', { defaultValue: 'Done' })}
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-semantic-success/30 bg-semantic-success-bg/30 px-4 py-3">
            <CheckCircle2 size={18} className="text-semantic-success" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{result.subject}</p>
              <p className="text-xs text-content-tertiary">
                {result.record_filename}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => downloadMut.mutate()}
              loading={downloadMut.isPending}
            >
              {t('record_publishing.download_pdf', { defaultValue: 'Download PDF' })}
            </Button>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-secondary">
              {t('record_publishing.recipients_heading', {
                defaultValue: 'Recipients',
              })}
            </h3>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {result.recipients.map((r) => (
                <RecipientResultRow key={r.email} recipient={r} />
              ))}
            </ul>
            <p className="mt-2 text-xs text-content-tertiary">
              {t('record_publishing.forward_hint', {
                defaultValue:
                  'Copy each acknowledgement link into your own email, or send the record link so a recipient can download the PDF directly.',
              })}
            </p>
          </div>
        </div>
      </WideModal>
    );
  }

  /* ── Compose panel ────────────────────────────────────────────────────── */
  const lists = listsQ.data?.items ?? [];

  return (
    <WideModal
      open
      onClose={onClose}
      busy={publishMut.isPending}
      size="xl"
      title={t('record_publishing.publish_title', {
        defaultValue: 'Publish and distribute',
      })}
      subtitle={
        subjectHint
          ? t('record_publishing.publish_subtitle_named', {
              defaultValue:
                'Turn "{{name}}" into a signed PDF and send it as an acknowledged transmittal in one step.',
              name: subjectHint,
            })
          : t('record_publishing.publish_subtitle', {
              defaultValue:
                'Turn this record into a signed PDF and send it as an acknowledged transmittal in one step.',
            })
      }
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={publishMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={<Send size={14} />}
            onClick={() => publishMut.mutate()}
            loading={publishMut.isPending}
            disabled={validRecipients.length === 0}
          >
            {t('record_publishing.publish_action', {
              defaultValue: 'Publish and distribute',
            })}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {lists.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2.5">
            <ListChecks size={15} className="text-content-tertiary" />
            <span className="text-sm text-content-secondary">
              {t('record_publishing.add_from_list', {
                defaultValue: 'Add a saved distribution list',
              })}
            </span>
            <select
              className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              value=""
              onChange={(e) => {
                if (e.target.value) addListMembers(e.target.value);
                e.target.value = '';
              }}
              aria-label={t('record_publishing.add_from_list', {
                defaultValue: 'Add a saved distribution list',
              })}
            >
              <option value="">
                {t('record_publishing.choose_list', { defaultValue: 'Choose…' })}
              </option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.members.length})
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
              {t('record_publishing.recipients_heading', {
                defaultValue: 'Recipients',
              })}
            </h3>
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={14} />}
              onClick={addRow}
            >
              {t('record_publishing.add_recipient', {
                defaultValue: 'Add recipient',
              })}
            </Button>
          </div>

          <div className="space-y-2">
            {rows.map((row, idx) => (
              <div
                key={idx}
                className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto] sm:items-center"
              >
                <input
                  type="email"
                  inputMode="email"
                  autoComplete="off"
                  placeholder={t('record_publishing.email_placeholder', {
                    defaultValue: 'name@company.com',
                  })}
                  value={row.email}
                  onChange={(e) => patchRow(idx, { email: e.target.value })}
                  className={inputCls}
                  aria-label={t('record_publishing.email_label', {
                    defaultValue: 'Recipient email',
                  })}
                />
                <input
                  type="text"
                  placeholder={t('record_publishing.name_placeholder', {
                    defaultValue: 'Name (optional)',
                  })}
                  value={row.display_name}
                  onChange={(e) =>
                    patchRow(idx, { display_name: e.target.value })
                  }
                  className={inputCls}
                  aria-label={t('record_publishing.name_label', {
                    defaultValue: 'Recipient name',
                  })}
                />
                <select
                  value={row.role}
                  onChange={(e) => patchRow(idx, { role: e.target.value })}
                  className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('record_publishing.role_label', {
                    defaultValue: 'Recipient role',
                  })}
                >
                  {ROLE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(o.labelKey, { defaultValue: o.fallback })}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => removeRow(idx)}
                  disabled={rows.length <= 1}
                  aria-label={t('record_publishing.remove_recipient', {
                    defaultValue: 'Remove recipient',
                  })}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-content-tertiary"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <label
            htmlFor="record-publish-notes"
            className="mb-1.5 block text-xs font-medium text-content-primary"
          >
            {t('record_publishing.notes_label', {
              defaultValue: 'Cover note (optional)',
            })}
          </label>
          <textarea
            id="record-publish-notes"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t('record_publishing.notes_placeholder', {
              defaultValue: 'A short line that appears on the transmittal cover sheet.',
            })}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
      </div>
    </WideModal>
  );
}

/* ── Per-recipient result row ─────────────────────────────────────────────── */

function RecipientResultRow({
  recipient,
}: {
  recipient: PublishedRecipientOut;
}) {
  const { t } = useTranslation();
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {recipient.display_name || recipient.email}
        </p>
        {recipient.display_name && (
          <p className="truncate text-xs text-content-tertiary">
            {recipient.email}
          </p>
        )}
      </div>
      {recipient.role && (
        <Badge variant="neutral" size="sm">
          {t(`record_publishing.role_${recipient.role}`, {
            defaultValue: recipient.role.replace(/_/g, ' '),
          })}
        </Badge>
      )}
      <div className="flex items-center gap-1.5">
        <CopyLinkButton
          url={recipient.record_url}
          label={t('record_publishing.copy_record_link', {
            defaultValue: 'Record link',
          })}
        />
        <CopyLinkButton
          url={recipient.acknowledge_url}
          label={t('record_publishing.copy_ack_link', {
            defaultValue: 'Acknowledge link',
          })}
        />
      </div>
    </li>
  );
}

function CopyLinkButton({ url, label }: { url: string; label: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    // Recipient links are host-relative; forward the absolute URL.
    const absolute =
      typeof window !== 'undefined' ? window.location.origin + url : url;
    try {
      await navigator.clipboard.writeText(absolute);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      addToast({
        type: 'error',
        title: t('record_publishing.copy_failed', {
          defaultValue: 'Could not copy the link',
        }),
      });
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue"
    >
      {copied ? (
        <Check size={12} className="text-semantic-success" />
      ) : (
        <Copy size={12} />
      )}
      {copied ? t('common.copied', { defaultValue: 'Copied' }) : label}
    </button>
  );
}
