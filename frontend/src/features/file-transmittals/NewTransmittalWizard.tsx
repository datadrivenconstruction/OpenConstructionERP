// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// New Transmittal — 3-step wizard.
//   1. Subject + reason + notes
//   2. Pick files (accepts pre-selected rows via ``preselectedItems``)
//   3. Recipients (per-email rows; future: import from W10 lists)
//
// On finish → POST create draft → POST send → toast success.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, FileText, Mail, Send } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import { useCreateTransmittal, useSendTransmittal } from './hooks';
import type {
  FileKind,
  TransmittalCreatePayload,
  TransmittalItemPayload,
  TransmittalRecipientPayload,
  TransmittalReason,
} from './types';

// English fallbacks for the computed `files.transmittals.reason.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const TRANSMITTALS_REASON_LABELS: Record<string, string> = {
  for_review: 'For review', for_construction: 'For construction', for_approval: 'For approval',
  for_information: 'For information', for_record: 'For record'
};


export interface PreselectedItem {
  file_kind: FileKind;
  file_id: string;
  canonical_name_snapshot: string;
  file_version_snapshot?: string | null;
}

export interface NewTransmittalWizardProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Items to seed step 2 with (typically from a multi-select on the file list). */
  preselectedItems?: PreselectedItem[];
  /** Fires after a successful create+send so the parent can refresh the log. */
  onSent?: (transmittalId: string) => void;
}

type Step = 1 | 2 | 3;

const REASON_CODES: TransmittalReason[] = [
  'for_review',
  'for_construction',
  'for_approval',
  'for_information',
  'for_record',
];

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function NewTransmittalWizard({
  open,
  onClose,
  projectId,
  preselectedItems,
  onSent,
}: NewTransmittalWizardProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const createMutation = useCreateTransmittal();
  const sendMutation = useSendTransmittal();

  const [step, setStep] = useState<Step>(1);
  const [subject, setSubject] = useState('');
  const [reason, setReason] = useState<TransmittalReason>('for_review');
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<TransmittalItemPayload[]>([]);
  const [recipients, setRecipients] = useState<TransmittalRecipientPayload[]>([]);
  const [recipientDraft, setRecipientDraft] = useState({
    email: '',
    display_name: '',
    role: '',
  });

  // Reset wizard state every time it opens.
  useEffect(() => {
    if (!open) return;
    setStep(1);
    setSubject('');
    setReason('for_review');
    setNotes('');
    setItems(
      (preselectedItems ?? []).map((p, idx) => ({
        file_kind: p.file_kind,
        file_id: p.file_id,
        canonical_name_snapshot: p.canonical_name_snapshot,
        file_version_snapshot: p.file_version_snapshot ?? null,
        sort_order: idx,
      })),
    );
    setRecipients([]);
    setRecipientDraft({ email: '', display_name: '', role: '' });
  }, [open, preselectedItems]);

  const busy = createMutation.isPending || sendMutation.isPending;

  const canAdvance = useMemo(() => {
    if (step === 1) return subject.trim().length > 0 && REASON_CODES.includes(reason);
    if (step === 2) return items.length > 0;
    if (step === 3) return recipients.length > 0;
    return false;
  }, [step, subject, reason, items, recipients]);

  function addRecipient() {
    const email = recipientDraft.email.trim().toLowerCase();
    if (!isValidEmail(email)) {
      addToast({
        type: 'error',
        title: t('files.transmittals.invalid_email', {
          defaultValue: 'Enter a valid email address',
        }),
      });
      return;
    }
    if (recipients.some((r) => r.email.toLowerCase() === email)) {
      addToast({
        type: 'warning',
        title: t('files.transmittals.duplicate_recipient', {
          defaultValue: 'Recipient already in list',
        }),
      });
      return;
    }
    setRecipients((prev) => [
      ...prev,
      {
        email,
        display_name: recipientDraft.display_name.trim() || null,
        role: recipientDraft.role.trim() || null,
      },
    ]);
    setRecipientDraft({ email: '', display_name: '', role: '' });
  }

  function removeRecipient(idx: number) {
    setRecipients((prev) => prev.filter((_, i) => i !== idx));
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleFinish() {
    const payload: TransmittalCreatePayload = {
      project_id: projectId,
      subject: subject.trim(),
      reason_code: reason,
      notes: notes.trim() || null,
      items,
      recipients,
    };
    try {
      const draft = await createMutation.mutateAsync(payload);
      const sent = await sendMutation.mutateAsync(draft.id);
      addToast({
        type: 'success',
        title: t('files.transmittals.sent_title', {
          defaultValue: 'Transmittal {{number}} sent',
          number: sent.number,
        }),
      });
      onSent?.(sent.id);
      onClose();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.transmittals.send_failed', {
          defaultValue: 'Failed to send transmittal',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  const reasonLabel = (code: TransmittalReason): string =>
    t(`files.transmittals.reason.${code}`, {
      defaultValue: TRANSMITTALS_REASON_LABELS[code] ?? code
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' '),
    });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('files.transmittals.wizard.title', {
        defaultValue: 'New Transmittal',
      })}
      subtitle={t('files.transmittals.wizard.subtitle', {
        defaultValue: 'Step {{step}} of 3',
        step,
      })}
      size="lg"
      busy={busy}
      footer={
        <div className="flex items-center gap-2 w-full justify-between">
          <div className="flex gap-1">
            {([1, 2, 3] as Step[]).map((n) => (
              <span
                key={n}
                className={clsx(
                  'h-1.5 w-8 rounded-full transition-colors',
                  step >= n ? 'bg-oe-blue' : 'bg-border-light',
                )}
                aria-hidden
              />
            ))}
          </div>
          <div className="flex gap-2">
            {step > 1 && (
              <Button
                variant="secondary"
                onClick={() => setStep((s) => (s === 1 ? 1 : ((s - 1) as Step)))}
                disabled={busy}
              >
                {t('common.back', { defaultValue: 'Back' })}
              </Button>
            )}
            {step < 3 && (
              <Button
                variant="primary"
                onClick={() => setStep((s) => (s === 3 ? 3 : ((s + 1) as Step)))}
                disabled={!canAdvance || busy}
              >
                {t('common.next', { defaultValue: 'Next' })}
              </Button>
            )}
            {step === 3 && (
              <Button
                variant="primary"
                onClick={handleFinish}
                disabled={!canAdvance || busy}
                loading={busy}
                icon={<Send size={14} />}
              >
                {t('files.transmittals.send', { defaultValue: 'Send' })}
              </Button>
            )}
          </div>
        </div>
      }
    >
      {step === 1 && (
        <WideModalSection
          title={t('files.transmittals.wizard.step1', {
            defaultValue: 'Subject & reason',
          })}
          columns={2}
        >
          <WideModalField
            label={t('files.transmittals.subject', { defaultValue: 'Subject' })}
            required
            span={2}
          >
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={255}
              className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
              placeholder={t('files.transmittals.subject_placeholder', {
                defaultValue: 'e.g. Issue for review - package R1',
              })}
            />
          </WideModalField>

          <WideModalField
            label={t('files.transmittals.reason', { defaultValue: 'Reason' })}
            required
          >
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value as TransmittalReason)}
              className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
            >
              {REASON_CODES.map((code) => (
                <option key={code} value={code}>
                  {reasonLabel(code)}
                </option>
              ))}
            </select>
          </WideModalField>

          <WideModalField
            label={t('files.transmittals.notes', {
              defaultValue: 'Notes (optional)',
            })}
            span={2}
          >
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              maxLength={4000}
              className="px-3 py-2 rounded-md border border-border bg-surface-primary text-sm resize-y"
              placeholder={t('files.transmittals.notes_placeholder', {
                defaultValue: 'Anything the recipients should know.',
              })}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {step === 2 && (
        <WideModalSection
          title={t('files.transmittals.wizard.step2', {
            defaultValue: 'Files',
          })}
          description={t('files.transmittals.wizard.step2_help', {
            defaultValue:
              'These files will be referenced on the cover sheet. Files were pre-selected from the list - review and remove if needed.',
          })}
          columns={1}
        >
          {items.length === 0 ? (
            <p className="text-sm text-content-tertiary py-6 text-center border border-dashed border-border rounded-md">
              {t('files.transmittals.no_items', {
                defaultValue:
                  'No files selected. Close this wizard, select files on the list, then click "Send transmittal" again.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light border border-border-light rounded-md">
              {items.map((it, idx) => (
                <li
                  key={`${it.file_kind}-${it.file_id}-${idx}`}
                  className="flex items-center gap-3 px-3 py-2"
                >
                  <FileText size={16} className="text-content-tertiary shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {it.canonical_name_snapshot}
                    </p>
                    <p className="text-xs text-content-tertiary">
                      {it.file_kind}
                      {it.file_version_snapshot
                        ? ` · v${it.file_version_snapshot}`
                        : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeItem(idx)}
                    className="text-content-tertiary hover:text-semantic-error transition-colors"
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </WideModalSection>
      )}

      {step === 3 && (
        <WideModalSection
          title={t('files.transmittals.wizard.step3', {
            defaultValue: 'Recipients',
          })}
          description={t('files.transmittals.wizard.step3_help', {
            defaultValue:
              'Each recipient will be issued a single-use acknowledgement link.',
          })}
          columns={1}
        >
          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] gap-2 items-end">
            <div className="flex flex-col">
              <label className="text-xs text-content-secondary mb-1">
                {t('files.transmittals.recipient_email', {
                  defaultValue: 'Email',
                })}
              </label>
              <input
                type="email"
                value={recipientDraft.email}
                onChange={(e) =>
                  setRecipientDraft((prev) => ({ ...prev, email: e.target.value }))
                }
                className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
                placeholder="user@example.com"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-xs text-content-secondary mb-1">
                {t('files.transmittals.recipient_name', {
                  defaultValue: 'Display name',
                })}
              </label>
              <input
                type="text"
                value={recipientDraft.display_name}
                onChange={(e) =>
                  setRecipientDraft((prev) => ({
                    ...prev,
                    display_name: e.target.value,
                  }))
                }
                className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-xs text-content-secondary mb-1">
                {t('files.transmittals.recipient_role', {
                  defaultValue: 'Role',
                })}
              </label>
              <input
                type="text"
                value={recipientDraft.role}
                onChange={(e) =>
                  setRecipientDraft((prev) => ({ ...prev, role: e.target.value }))
                }
                className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
              />
            </div>
            <Button
              variant="secondary"
              onClick={addRecipient}
              icon={<Plus size={14} />}
              disabled={busy}
            >
              {t('common.add', { defaultValue: 'Add' })}
            </Button>
          </div>

          {recipients.length === 0 ? (
            <p className="text-sm text-content-tertiary py-4 mt-2 text-center border border-dashed border-border rounded-md">
              {t('files.transmittals.no_recipients', {
                defaultValue: 'No recipients yet. Add at least one to send.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light border border-border-light rounded-md mt-2">
              {recipients.map((r, idx) => (
                <li
                  key={r.email}
                  className="flex items-center gap-3 px-3 py-2"
                >
                  <Mail size={16} className="text-content-tertiary shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {r.display_name || r.email}
                    </p>
                    <p className="text-xs text-content-tertiary">
                      {r.email}
                      {r.role ? ` · ${r.role}` : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRecipient(idx)}
                    className="text-content-tertiary hover:text-semantic-error transition-colors"
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </WideModalSection>
      )}
    </WideModal>
  );
}
