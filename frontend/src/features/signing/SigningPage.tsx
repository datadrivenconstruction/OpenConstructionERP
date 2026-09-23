// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  FileSignature,
  Plus,
  Search,
  ChevronRight,
  Pencil,
  Trash2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  Download,
  Loader2,
  UserCheck,
  UserX,
  UserCircle,
  ExternalLink,
  X as XIcon,
} from 'lucide-react';
import {
  Button,
  Badge,
  EmptyState,
  DateDisplay,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import {
  fetchSigningSessions,
  fetchSigningManifest,
  fetchExpiringCerts,
  createSigningSession,
  updateSigningSession,
  deleteSigningSession,
  attestSigningSession,
  declineSigningSession,
  downloadSigningManifest,
  type SigningSession,
  type SigningSessionStatus,
  type SigningCapability,
  type SignatoryEntry,
  type CreateSigningSessionPayload,
  type UpdateSigningSessionPayload,
  type AttestationCreatePayload,
  type DeclineCreatePayload,
} from './api';
import { signingGuide } from './signingGuide';
import { fmtList } from '@/shared/lib/formatters';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const CAPABILITIES: SigningCapability[] = [
  'qualified_electronic',
  'advanced_electronic',
  'simple_electronic',
  'digital_certificate',
];

const CAPABILITY_LABELS: Record<SigningCapability, string> = {
  qualified_electronic: 'Qualified electronic',
  advanced_electronic: 'Advanced electronic',
  simple_electronic: 'Simple electronic',
  digital_certificate: 'Digital certificate',
};

const STATUS_ORDER: SigningSessionStatus[] = [
  'draft',
  'awaiting_signatures',
  'partially_signed',
  'fully_signed',
  'declined',
  'expired',
];

const STATUS_LABELS: Record<SigningSessionStatus, string> = {
  draft: 'Draft',
  awaiting_signatures: 'Awaiting signatures',
  partially_signed: 'Partially signed',
  fully_signed: 'Fully signed',
  declined: 'Declined',
  expired: 'Expired',
};

const SETTABLE_STATUSES: SigningSessionStatus[] = ['draft', 'awaiting_signatures'];

function statusVariant(s: SigningSessionStatus): 'neutral' | 'blue' | 'warning' | 'success' | 'error' {
  switch (s) {
    case 'draft':
      return 'neutral';
    case 'awaiting_signatures':
      return 'blue';
    case 'partially_signed':
      return 'warning';
    case 'fully_signed':
      return 'success';
    case 'declined':
      return 'error';
    case 'expired':
      return 'error';
    default:
      return 'neutral';
  }
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create / edit session modal ──────────────────────────────────────── */

interface SessionFormData {
  document_ref: string;
  document_content_hash: string;
  provider_capability: SigningCapability;
  expires_at: string;
  status: SigningSessionStatus;
  signatories: SignatoryEntry[];
}

const EMPTY_FORM: SessionFormData = {
  document_ref: '',
  document_content_hash: '',
  provider_capability: 'simple_electronic',
  expires_at: '',
  status: 'draft',
  signatories: [],
};

function sessionToForm(s: SigningSession): SessionFormData {
  return {
    document_ref: s.document_ref,
    document_content_hash: s.document_content_hash,
    provider_capability: s.provider_capability,
    expires_at: s.expires_at ? s.expires_at.slice(0, 10) : '',
    status: SETTABLE_STATUSES.includes(s.status) ? s.status : 'draft',
    signatories: s.signatory_map.map((e) => ({ ...e })),
  };
}

function SessionFormModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
}: {
  onClose: () => void;
  onSubmit: (data: SessionFormData) => void;
  isPending: boolean;
  initialData?: SessionFormData | null;
  isEdit?: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<SessionFormData>(initialData ?? EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof SessionFormData>(key: K, value: SessionFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const addSignatory = () =>
    setForm((prev) => ({
      ...prev,
      signatories: [...prev.signatories, { name: '', role: '', required: true }],
    }));

  const updateSignatory = (idx: number, patch: Partial<SignatoryEntry>) =>
    setForm((prev) => ({
      ...prev,
      signatories: prev.signatories.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
    }));

  const removeSignatory = (idx: number) =>
    setForm((prev) => ({
      ...prev,
      signatories: prev.signatories.filter((_, i) => i !== idx),
    }));

  const docRefError = touched && form.document_ref.trim().length === 0;
  const hashError = touched && form.document_content_hash.trim().length === 0;
  const roles = form.signatories.map((s) => s.role.trim()).filter(Boolean);
  const rolesDuplicate = new Set(roles).size !== roles.length;
  const canSubmit =
    form.document_ref.trim().length > 0 &&
    form.document_content_hash.trim().length > 0 &&
    !rolesDuplicate;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="lg"
      title={
        isEdit
          ? t('signing.edit_session', { defaultValue: 'Edit Signing Session' })
          : t('signing.new_session', { defaultValue: 'New Signing Session' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <Loader2 size={16} className="mr-1.5 animate-spin shrink-0" />
            ) : !isEdit ? (
              <Plus size={16} className="mr-1.5 shrink-0" />
            ) : null}
            <span>
              {isEdit
                ? t('signing.save_session', { defaultValue: 'Save Changes' })
                : t('signing.create_session', { defaultValue: 'Create Session' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('signing.section_document', { defaultValue: 'Document' })}
        columns={2}
      >
        <WideModalField
          label={t('signing.field_document_ref', { defaultValue: 'Document reference' })}
          required
          span={2}
          htmlFor="sign-doc-ref"
          error={
            docRefError
              ? t('signing.document_ref_required', { defaultValue: 'Document reference is required' })
              : undefined
          }
        >
          <input
            id="sign-doc-ref"
            value={form.document_ref}
            onChange={(e) => {
              set('document_ref', e.target.value);
              setTouched(true);
            }}
            placeholder={t('signing.document_ref_placeholder', {
              defaultValue: 'e.g. Contract-2026-014.pdf',
            })}
            className={clsx(inputCls, docRefError && 'border-semantic-error')}
          />
        </WideModalField>

        <WideModalField
          label={t('signing.field_content_hash', { defaultValue: 'Content hash (sha256)' })}
          required
          span={2}
          htmlFor="sign-content-hash"
          hint={t('signing.hint_content_hash', {
            defaultValue: 'The hash of the exact file being issued for signature.',
          })}
          error={
            hashError
              ? t('signing.content_hash_required', { defaultValue: 'Content hash is required' })
              : undefined
          }
        >
          <input
            id="sign-content-hash"
            value={form.document_content_hash}
            onChange={(e) => {
              set('document_content_hash', e.target.value);
              setTouched(true);
            }}
            placeholder="e.g. 9f86d081884c7d659a2feaa0c55ad015..."
            className={clsx(inputCls, 'font-mono text-xs', hashError && 'border-semantic-error')}
          />
        </WideModalField>

        <WideModalField label={t('signing.field_capability', { defaultValue: 'Required capability' })}>
          <select
            value={form.provider_capability}
            onChange={(e) => set('provider_capability', e.target.value as SigningCapability)}
            className={inputCls}
          >
            {CAPABILITIES.map((c) => (
              <option key={c} value={c}>
                {t(`signing.capability_${c}`, { defaultValue: CAPABILITY_LABELS[c] })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('signing.field_expires_at', { defaultValue: 'Expires' })}>
          <input
            type="date"
            value={form.expires_at}
            onChange={(e) => set('expires_at', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('signing.field_status', { defaultValue: 'Initial status' })}
          span={2}
          hint={t('signing.hint_status', {
            defaultValue: 'Only draft and awaiting signatures can be set directly; the rest are derived.',
          })}
        >
          <select
            value={form.status}
            onChange={(e) => set('status', e.target.value as SigningSessionStatus)}
            className={inputCls}
          >
            {SETTABLE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`signing.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('signing.section_signatories', { defaultValue: 'Signatories' })}
      >
        <WideModalField
          span={2}
          hint={
            rolesDuplicate
              ? t('signing.roles_must_be_unique', { defaultValue: 'Roles must be unique within a session.' })
              : t('signing.hint_signatories', {
                  defaultValue: 'Everyone expected to sign. Uncheck Required for an optional signatory.',
                })
          }
        >
          <div className="space-y-2">
            {form.signatories.map((sig, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  value={sig.name}
                  onChange={(e) => updateSignatory(idx, { name: e.target.value })}
                  placeholder={t('signing.signatory_name_placeholder', { defaultValue: 'Name' })}
                  className={clsx(inputCls, 'flex-1')}
                />
                <input
                  value={sig.role}
                  onChange={(e) => updateSignatory(idx, { role: e.target.value })}
                  placeholder={t('signing.signatory_role_placeholder', { defaultValue: 'Role' })}
                  className={clsx(inputCls, 'w-40')}
                />
                <label className="flex shrink-0 items-center gap-1.5 text-xs text-content-tertiary">
                  <input
                    type="checkbox"
                    checked={sig.required ?? true}
                    onChange={(e) => updateSignatory(idx, { required: e.target.checked })}
                    className="accent-oe-blue"
                  />
                  {t('signing.required', { defaultValue: 'Required' })}
                </label>
                <button
                  type="button"
                  onClick={() => removeSignatory(idx)}
                  className="shrink-0 rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-950/30"
                  aria-label={t('common.remove', { defaultValue: 'Remove' })}
                >
                  <XIcon size={14} />
                </button>
              </div>
            ))}
            <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={addSignatory}>
              {t('signing.add_signatory', { defaultValue: 'Add signatory' })}
            </Button>
          </div>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Attest / decline modals ──────────────────────────────────────────── */

function AttestModal({
  session,
  prefill,
  onClose,
  onSubmit,
  isPending,
}: {
  session: SigningSession;
  prefill?: SignatoryEntry | null;
  onClose: () => void;
  onSubmit: (data: AttestationCreatePayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(prefill?.name ?? '');
  const [role, setRole] = useState(prefill?.role ?? '');
  const [contentHash, setContentHash] = useState(session.document_content_hash);
  const [certSubject, setCertSubject] = useState('');
  const [certValidUntil, setCertValidUntil] = useState('');
  const [notes, setNotes] = useState('');
  const [touched, setTouched] = useState(false);

  const canSubmit = name.trim().length > 0 && role.trim().length > 0 && contentHash.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      signatory_name: name.trim(),
      signatory_role: role.trim(),
      content_hash: contentHash.trim(),
      cert_subject: certSubject.trim() || null,
      cert_valid_until: certValidUntil || null,
      notes,
    });
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="md"
      title={t('signing.attest_title', { defaultValue: 'Record Attestation' })}
      subtitle={session.document_ref}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <Loader2 size={16} className="mr-1.5 animate-spin shrink-0" />
            ) : (
              <CheckCircle2 size={16} className="mr-1.5 shrink-0" />
            )}
            {t('signing.attest_action', { defaultValue: 'Record signature' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('signing.field_signatory_name', { defaultValue: 'Signatory name' })}
          required
          error={
            touched && !name.trim()
              ? t('signing.name_required', { defaultValue: 'Name is required' })
              : undefined
          }
        >
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </WideModalField>
        <WideModalField
          label={t('signing.field_signatory_role', { defaultValue: 'Role' })}
          required
          error={
            touched && !role.trim()
              ? t('signing.role_required', { defaultValue: 'Role is required' })
              : undefined
          }
        >
          <input value={role} onChange={(e) => setRole(e.target.value)} className={inputCls} />
        </WideModalField>
        <WideModalField
          label={t('signing.field_content_hash_signed', { defaultValue: 'Content hash signed' })}
          span={2}
          required
          hint={t('signing.hint_content_hash_signed', {
            defaultValue: 'Defaults to the session’s current hash; change only if this signature was made against an earlier version.',
          })}
        >
          <input
            value={contentHash}
            onChange={(e) => setContentHash(e.target.value)}
            className={clsx(inputCls, 'font-mono text-xs')}
          />
        </WideModalField>
        <WideModalField
          label={t('signing.field_cert_subject', { defaultValue: 'Certificate subject' })}
          hint={t('signing.hint_optional', { defaultValue: 'Optional descriptive metadata only.' })}
        >
          <input value={certSubject} onChange={(e) => setCertSubject(e.target.value)} className={inputCls} />
        </WideModalField>
        <WideModalField label={t('signing.field_cert_valid_until', { defaultValue: 'Certificate valid until' })}>
          <input
            type="date"
            value={certValidUntil}
            onChange={(e) => setCertValidUntil(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('signing.field_notes', { defaultValue: 'Notes' })} span={2}>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={textareaCls} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function DeclineModal({
  session,
  prefill,
  onClose,
  onSubmit,
  isPending,
}: {
  session: SigningSession;
  prefill?: SignatoryEntry | null;
  onClose: () => void;
  onSubmit: (data: DeclineCreatePayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(prefill?.name ?? '');
  const [role, setRole] = useState(prefill?.role ?? '');
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);

  const canSubmit = name.trim().length > 0 && role.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({ signatory_name: name.trim(), signatory_role: role.trim(), reason });
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="sm"
      title={t('signing.decline_title', { defaultValue: 'Record Decline' })}
      subtitle={session.document_ref}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="danger"
            onClick={handleSubmit}
            disabled={isPending || !canSubmit}
          >
            {isPending ? (
              <Loader2 size={16} className="mr-1.5 animate-spin shrink-0" />
            ) : (
              <XCircle size={16} className="mr-1.5 shrink-0" />
            )}
            {t('signing.decline_action', { defaultValue: 'Record decline' })}
          </Button>
        </>
      }
    >
      <WideModalSection>
        <WideModalField
          label={t('signing.field_signatory_name', { defaultValue: 'Signatory name' })}
          required
          error={
            touched && !name.trim()
              ? t('signing.name_required', { defaultValue: 'Name is required' })
              : undefined
          }
        >
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </WideModalField>
        <WideModalField
          label={t('signing.field_signatory_role', { defaultValue: 'Role' })}
          required
          error={
            touched && !role.trim()
              ? t('signing.role_required', { defaultValue: 'Role is required' })
              : undefined
          }
        >
          <input value={role} onChange={(e) => setRole(e.target.value)} className={inputCls} />
        </WideModalField>
        <WideModalField label={t('signing.field_reason', { defaultValue: 'Reason' })}>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className={textareaCls} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Session row ───────────────────────────────────────────────────────── */

function signerStatus(
  session: SigningSession,
  entry: SignatoryEntry,
): 'signed' | 'declined' | 'stale' | 'pending' {
  const sig = session.signatures.find(
    (s) => s.signatory_role === entry.role && s.signatory_name === entry.name,
  );
  if (!sig) return 'pending';
  if (sig.status === 'declined') return 'declined';
  return sig.stale ? 'stale' : 'signed';
}

const SessionRow = React.memo(function SessionRow({
  session,
  onEdit,
  onDelete,
  onAttest,
  onDecline,
  onDownloadManifest,
  manifestPending,
}: {
  session: SigningSession;
  onEdit: (s: SigningSession) => void;
  onDelete: (s: SigningSession) => void;
  onAttest: (s: SigningSession, prefill?: SignatoryEntry) => void;
  onDecline: (s: SigningSession, prefill?: SignatoryEntry) => void;
  onDownloadManifest: (s: SigningSession) => void;
  manifestPending: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const hasStale = session.signatures.some((s) => s.stale);
  const progressLabel = `${session.signed_count}/${session.required_count || session.signatory_map.length}`;

  // A session names the capability it REQUIRES and, separately, the one the
  // resolved provider actually DELIVERED. Core ships a single provider, which
  // performs no cryptography and delivers simple_electronic, and the registry
  // falls back to it for any capability no adapter has claimed. So a session
  // requiring a qualified signature gets less than it asked for, and a row
  // that showed the requirement alone read as a claim it had been met.
  const capabilityLabel = (code: string) =>
    t(`signing.capability_${code}`, {
      defaultValue: CAPABILITY_LABELS[code as SigningCapability] ?? code,
    });
  const requiredCapabilityLabel = capabilityLabel(session.provider_capability);
  // Never `delivered ?? required`: null means no derivation recorded one, and
  // borrowing the requirement to fill the gap manufactures exactly the claim
  // this field exists to stop making.
  const deliveredCapabilityLabel = session.delivered_capability
    ? capabilityLabel(session.delivered_capability)
    : t('signing.capability_not_recorded', { defaultValue: 'Not recorded' });
  // Null counts as a shortfall too: unrecorded is not "as required".
  const capabilityShortfall = session.delivered_capability !== session.provider_capability;
  const requiredFieldLabel = t('signing.field_capability', { defaultValue: 'Required capability' });
  const deliveredFieldLabel = t('signing.field_delivered_capability', {
    defaultValue: 'Delivered capability',
  });

  return (
    <div className="border-b border-border-light last:border-b-0">
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
      >
        <ChevronRight
          size={14}
          className={clsx('text-content-tertiary transition-transform shrink-0', expanded && 'rotate-90')}
        />
        <FileSignature size={15} className="shrink-0 text-content-tertiary" />
        <Link
          to={`/files?q=${encodeURIComponent(session.document_ref)}`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-sm text-content-primary truncate flex-1 min-w-0 hover:text-oe-blue hover:underline"
          title={t('signing.open_document', {
            defaultValue: 'Find "{{ref}}" in Project Files',
            ref: session.document_ref,
          })}
        >
          <span className="truncate">{session.document_ref}</span>
          <ExternalLink size={11} className="shrink-0 opacity-60" aria-hidden="true" />
        </Link>

        {/* The requirement, and beside it what was actually delivered whenever
            that is something else. The shortfall badge follows the same idiom
            as the stale one below it: a field is stated, a discrepancy is
            flagged. The title carries the pair labelled, so two capability
            names sitting side by side are never ambiguous. */}
        <span
          className="hidden md:inline-flex items-center gap-1 shrink-0"
          title={
            capabilityShortfall
              ? `${requiredFieldLabel}: ${requiredCapabilityLabel}\n${deliveredFieldLabel}: ${deliveredCapabilityLabel}`
              : `${requiredFieldLabel}: ${requiredCapabilityLabel}`
          }
        >
          <Badge variant="neutral" size="sm">
            {requiredCapabilityLabel}
          </Badge>
          {capabilityShortfall && (
            <Badge variant="warning" size="sm">
              <AlertTriangle size={11} className="mr-1" />
              {deliveredCapabilityLabel}
            </Badge>
          )}
        </span>

        <Badge variant={statusVariant(session.status)} size="sm" className="shrink-0">
          {t(`signing.status_${session.status}`, { defaultValue: STATUS_LABELS[session.status] })}
        </Badge>

        {hasStale && (
          <Badge variant="warning" size="sm" className="shrink-0">
            <AlertTriangle size={11} className="mr-1" />
            {t('signing.stale_badge', { defaultValue: 'Stale' })}
          </Badge>
        )}

        <span className="hidden sm:flex items-center gap-1 text-xs text-content-tertiary tabular-nums w-14 justify-end shrink-0">
          <UserCheck size={12} />
          {progressLabel}
        </span>

        <span className="hidden lg:block text-xs text-content-tertiary w-24 shrink-0">
          <DateDisplay value={session.expires_at} className="text-xs" />
        </span>
      </div>

      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Both values, always, whether or not they agree. The requirement is
              what was asked for; the delivered capability is what the platform
              could actually produce, and it is the one a reader needs to see
              before treating this session as legal evidence. */}
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <div className="flex items-center gap-1.5">
              <dt className="text-content-tertiary">{requiredFieldLabel}</dt>
              <dd className="text-content-secondary">{requiredCapabilityLabel}</dd>
            </div>
            <div className="flex items-center gap-1.5">
              <dt className="text-content-tertiary">{deliveredFieldLabel}</dt>
              <dd className={capabilityShortfall ? 'text-semantic-warning' : 'text-content-secondary'}>
                {deliveredCapabilityLabel}
              </dd>
            </div>
          </dl>

          <div className="rounded-lg bg-surface-secondary p-3 space-y-1.5">
            <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('signing.label_content_hash', { defaultValue: 'Content hash' })}
            </p>
            <p className="text-xs font-mono text-content-secondary break-all">
              {session.document_content_hash}
            </p>
          </div>

          <div>
            <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary mb-1.5">
              {t('signing.label_signatories', { defaultValue: 'Signatories' })}
            </p>
            {session.signatory_map.length === 0 ? (
              <p className="text-xs text-content-quaternary">
                {t('signing.no_signatories', { defaultValue: 'No signatories added yet.' })}
              </p>
            ) : (
              <ul className="space-y-1.5">
                {session.signatory_map.map((entry, idx) => {
                  const state = signerStatus(session, entry);
                  return (
                    <li
                      key={`${entry.role}-${idx}`}
                      className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
                    >
                      {state === 'signed' && <UserCheck size={14} className="shrink-0 text-semantic-success" />}
                      {state === 'declined' && <UserX size={14} className="shrink-0 text-semantic-error" />}
                      {state === 'stale' && <AlertTriangle size={14} className="shrink-0 text-semantic-warning" />}
                      {state === 'pending' && <UserCircle size={14} className="shrink-0 text-content-quaternary" />}
                      <span className="text-sm text-content-primary">{entry.name || entry.role}</span>
                      <span className="text-xs text-content-tertiary">{entry.role}</span>
                      {entry.required === false && (
                        <Badge variant="neutral" size="sm">
                          {t('signing.optional', { defaultValue: 'Optional' })}
                        </Badge>
                      )}
                      <Badge
                        variant={
                          state === 'signed'
                            ? 'success'
                            : state === 'declined'
                              ? 'error'
                              : state === 'stale'
                                ? 'warning'
                                : 'neutral'
                        }
                        size="sm"
                        className="ml-auto"
                      >
                        {t(`signing.signer_state_${state}`, {
                          defaultValue:
                            state === 'signed'
                              ? 'Signed'
                              : state === 'declined'
                                ? 'Declined'
                                : state === 'stale'
                                  ? 'Stale - re-sign needed'
                                  : 'Pending',
                        })}
                      </Badge>
                      {(state === 'pending' || state === 'stale') && (
                        <div className="flex items-center gap-1.5">
                          <Button
                            variant="secondary"
                            size="sm"
                            icon={<CheckCircle2 size={12} />}
                            onClick={(e) => {
                              e.stopPropagation();
                              onAttest(session, entry);
                            }}
                          >
                            {t('signing.attest_action', { defaultValue: 'Record signature' })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-semantic-error"
                            icon={<XCircle size={12} />}
                            onClick={(e) => {
                              e.stopPropagation();
                              onDecline(session, entry);
                            }}
                          >
                            {t('signing.decline_action', { defaultValue: 'Record decline' })}
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              variant="secondary"
              size="sm"
              icon={
                manifestPending ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />
              }
              disabled={manifestPending}
              onClick={(e) => {
                e.stopPropagation();
                onDownloadManifest(session);
              }}
            >
              {t('signing.download_manifest', { defaultValue: 'Download manifest' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(session);
              }}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
              icon={<Trash2 size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(session);
              }}
            >
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Stale + expiring-certs side panels ───────────────────────────────── */

function StalePanel({ sessions }: { sessions: SigningSession[] }) {
  const { t } = useTranslation();
  const staleSessions = sessions.filter((s) => s.signatures.some((sig) => sig.stale));

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <AlertTriangle size={15} className="text-semantic-warning" />
        {t('signing.stale_panel_title', { defaultValue: 'Stale signatures' })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('signing.stale_panel_desc', {
          defaultValue: 'These signatures were made against an earlier version of the document and need a re-sign.',
        })}
      </p>
      {staleSessions.length === 0 ? (
        <p className="mt-3 text-xs text-content-quaternary">
          {t('signing.stale_panel_empty', { defaultValue: 'Nothing stale right now.' })}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {staleSessions.map((s) => (
            <li key={s.id} className="rounded-lg border border-border-light bg-surface-secondary/40 p-2.5">
              <p className="text-xs font-medium text-content-primary truncate">{s.document_ref}</p>
              <p className="mt-0.5 text-2xs text-content-tertiary">
                {fmtList(s.signatures
                  .filter((sig) => sig.stale)
                  .map((sig) => sig.signatory_name))}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExpiringCertsPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data: flags = [], isLoading } = useQuery({
    queryKey: ['signing-expiring-certs', projectId],
    queryFn: () => fetchExpiringCerts(projectId, 30),
    enabled: !!projectId,
  });

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <ShieldAlert size={15} className="text-semantic-warning" />
        {t('signing.certs_panel_title', { defaultValue: 'Expiring certificates' })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('signing.certs_panel_desc', {
          defaultValue: 'Recorded certificate metadata expired or expiring within 30 days.',
        })}
      </p>
      {isLoading ? (
        <div className="mt-3 h-16 animate-pulse rounded-lg bg-surface-secondary" />
      ) : flags.length === 0 ? (
        <p className="mt-3 text-xs text-content-quaternary">
          {t('signing.certs_panel_empty', { defaultValue: 'No certificates expiring soon.' })}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {flags.map((f) => (
            <li
              key={f.signature_id}
              className="flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-secondary/40 p-2.5"
            >
              <div className="min-w-0">
                <p className="text-xs font-medium text-content-primary truncate">{f.signatory_name}</p>
                <p className="text-2xs text-content-tertiary truncate">{f.cert_subject || f.signatory_role}</p>
              </div>
              <Badge variant={f.expired ? 'error' : 'warning'} size="sm" className="shrink-0">
                {f.expired
                  ? t('signing.cert_expired', { defaultValue: 'Expired' })
                  : t('signing.cert_expiring_in', { defaultValue: '{{count}}d left', count: f.days_until_expiry })}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function SigningPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useActiveProjectId();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingSession, setEditingSession] = useState<SigningSession | null>(null);
  const [attestTarget, setAttestTarget] = useState<{ session: SigningSession; prefill?: SignatoryEntry } | null>(
    null,
  );
  const [declineTarget, setDeclineTarget] = useState<{ session: SigningSession; prefill?: SignatoryEntry } | null>(
    null,
  );
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<SigningSessionStatus | ''>('');
  const [capabilityFilter, setCapabilityFilter] = useState<SigningCapability | ''>('');
  const [manifestPendingId, setManifestPendingId] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  const {
    data: sessions = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['signing-sessions', projectId, statusFilter, capabilityFilter],
    queryFn: () =>
      fetchSigningSessions({
        project_id: projectId,
        status: statusFilter || undefined,
        capability: capabilityFilter || undefined,
      }),
    enabled: !!projectId,
  });

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter(
      (s) =>
        s.document_ref.toLowerCase().includes(q) ||
        s.document_content_hash.toLowerCase().includes(q) ||
        s.signatory_map.some((e) => e.name.toLowerCase().includes(q) || e.role.toLowerCase().includes(q)),
    );
  }, [sessions, searchQuery]);

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['signing-sessions'] });
    qc.invalidateQueries({ queryKey: ['signing-expiring-certs'] });
  }, [qc]);

  const onMutationError = useCallback(
    (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
    [addToast, t],
  );

  const createMut = useMutation({
    mutationFn: (data: CreateSigningSessionPayload) => createSigningSession(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({ type: 'success', title: t('signing.created', { defaultValue: 'Session created' }) });
    },
    onError: onMutationError,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateSigningSessionPayload }) =>
      updateSigningSession(id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingSession(null);
      addToast({ type: 'success', title: t('signing.updated', { defaultValue: 'Session updated' }) });
    },
    onError: onMutationError,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSigningSession(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('signing.deleted', { defaultValue: 'Session deleted' }) });
    },
    onError: onMutationError,
  });

  const attestMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: AttestationCreatePayload }) => attestSigningSession(id, data),
    onSuccess: () => {
      invalidateAll();
      setAttestTarget(null);
      addToast({ type: 'success', title: t('signing.attested', { defaultValue: 'Signature recorded' }) });
    },
    onError: onMutationError,
  });

  const declineMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: DeclineCreatePayload }) => declineSigningSession(id, data),
    onSuccess: () => {
      invalidateAll();
      setDeclineTarget(null);
      addToast({ type: 'success', title: t('signing.declined_toast', { defaultValue: 'Decline recorded' }) });
    },
    onError: onMutationError,
  });

  // Only two statuses are caller-settable; the rest are server-derived. Narrow
  // the form value so it never tries to push a derived status through the API.
  const settableStatus = (
    s: SigningSessionStatus,
  ): 'draft' | 'awaiting_signatures' | undefined =>
    s === 'draft' || s === 'awaiting_signatures' ? s : undefined;

  const buildCreatePayload = (form: SessionFormData): CreateSigningSessionPayload => ({
    project_id: projectId,
    document_ref: form.document_ref.trim(),
    document_content_hash: form.document_content_hash.trim(),
    provider_capability: form.provider_capability,
    signatory_map: form.signatories.filter((s) => s.name.trim() && s.role.trim()),
    expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
    status: settableStatus(form.status),
  });

  const buildUpdatePayload = (form: SessionFormData): UpdateSigningSessionPayload => ({
    document_ref: form.document_ref.trim(),
    document_content_hash: form.document_content_hash.trim(),
    provider_capability: form.provider_capability,
    signatory_map: form.signatories.filter((s) => s.name.trim() && s.role.trim()),
    expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
    status: settableStatus(form.status),
  });

  /**
   * The body of an edit save: only the fields the user actually changed.
   *
   * Sending the whole form back rewrites fields the user never opened with the
   * values they held when this list was last read, undoing anyone else's edit
   * to them without a word. The update route dumps with `exclude_unset=True`,
   * so a field left out of the body is left alone in the database.
   *
   * `base` has to come from `sessionToForm`, the same function that seeds the
   * modal, so both sides have been through the same date slicing and status
   * narrowing and an untouched field always compares equal.
   */
  const buildUpdatePatch = (
    form: SessionFormData,
    base: SessionFormData,
  ): UpdateSigningSessionPayload => {
    const full = buildUpdatePayload(form);
    const patch: UpdateSigningSessionPayload = {};
    if (form.document_ref !== base.document_ref) patch.document_ref = full.document_ref;
    if (form.document_content_hash !== base.document_content_hash) {
      patch.document_content_hash = full.document_content_hash;
    }
    if (form.provider_capability !== base.provider_capability) {
      patch.provider_capability = full.provider_capability;
    }
    if (form.expires_at !== base.expires_at) patch.expires_at = full.expires_at;
    if (form.status !== base.status) patch.status = full.status;
    // Compared by content, not identity: `sessionToForm` copies every entry, so
    // a reference test would resend the whole signatory list on every save.
    if (JSON.stringify(form.signatories) !== JSON.stringify(base.signatories)) {
      patch.signatory_map = full.signatory_map;
    }
    return patch;
  };

  const handleDelete = async (session: SigningSession) => {
    const ok = await confirm({
      title: t('signing.confirm_delete_title', { defaultValue: 'Delete signing session?' }),
      message: t('signing.confirm_delete_message', {
        defaultValue: 'This removes "{{ref}}" and its recorded attestations. This cannot be undone.',
        ref: session.document_ref,
      }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate(session.id);
  };

  const handleDownloadManifest = async (session: SigningSession) => {
    setManifestPendingId(session.id);
    try {
      const manifest = await fetchSigningManifest(session.id);
      downloadSigningManifest(session, manifest);
    } catch (e) {
      onMutationError(e as Error);
    } finally {
      setManifestPendingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        srTitle={t('signing.title', { defaultValue: 'E-Signature Registry' })}
        subtitle={t('signing.subtitle', {
          defaultValue: 'Track who must sign, who signed or declined, and whether certificates are still valid.',
        })}
        actions={
          <div className="flex items-center gap-2">
            <ModuleGuideButton content={signingGuide} />
            <Button
              variant="primary"
              icon={<Plus size={15} />}
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
            >
              {t('signing.new_session', { defaultValue: 'New Signing Session' })}
            </Button>
          </div>
        }
      />

      {!projectId ? (
        <EmptyState
          icon={<FileSignature size={28} />}
          title={t('signing.no_project_title', { defaultValue: 'No project selected' })}
          description={t('signing.no_project_desc', {
            defaultValue: 'Pick a project to see its signing sessions.',
          })}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-3">
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[12rem]">
                <Search
                  size={14}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
                />
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('signing.search_placeholder', {
                    defaultValue: 'Search by document, hash or signatory...',
                  })}
                  className={clsx(inputCls, 'pl-8')}
                />
              </div>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as SigningSessionStatus | '')}
                className={clsx(inputCls, 'w-auto')}
              >
                <option value="">{t('signing.all_statuses', { defaultValue: 'All statuses' })}</option>
                {STATUS_ORDER.map((s) => (
                  <option key={s} value={s}>
                    {t(`signing.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
                  </option>
                ))}
              </select>
              <select
                value={capabilityFilter}
                onChange={(e) => setCapabilityFilter(e.target.value as SigningCapability | '')}
                className={clsx(inputCls, 'w-auto')}
              >
                <option value="">{t('signing.all_capabilities', { defaultValue: 'All capabilities' })}</option>
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>
                    {t(`signing.capability_${c}`, { defaultValue: CAPABILITY_LABELS[c] })}
                  </option>
                ))}
              </select>
            </div>

            {/* List */}
            {isLoading ? (
              <SkeletonTable rows={5} />
            ) : isError ? (
              <RecoveryCard error={error} onRetry={() => refetch()} />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<ShieldCheck size={28} />}
                title={t('signing.empty_title', { defaultValue: 'No signing sessions yet' })}
                description={t('signing.empty_desc', {
                  defaultValue: 'Open a session against a project document to start tracking attestations.',
                })}
                action={{
                  label: t('signing.new_session', { defaultValue: 'New Signing Session' }),
                  onClick: () => setShowCreateModal(true),
                }}
              />
            ) : (
              <div className="rounded-xl border border-border-light bg-surface-primary">
                {filtered.map((session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    onEdit={(s) => setEditingSession(s)}
                    onDelete={handleDelete}
                    onAttest={(s, prefill) => setAttestTarget({ session: s, prefill })}
                    onDecline={(s, prefill) => setDeclineTarget({ session: s, prefill })}
                    onDownloadManifest={handleDownloadManifest}
                    manifestPending={manifestPendingId === session.id}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <StalePanel sessions={sessions} />
            <ExpiringCertsPanel projectId={projectId} />
          </div>
        </div>
      )}

      {showCreateModal && (
        <SessionFormModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={(form) => createMut.mutate(buildCreatePayload(form))}
          isPending={createMut.isPending}
        />
      )}

      {editingSession && (
        <SessionFormModal
          isEdit
          initialData={sessionToForm(editingSession)}
          onClose={() => setEditingSession(null)}
          onSubmit={(form) =>
            // Rebuild the baseline the modal was seeded from, so the save
            // carries only what the user actually edited.
            updateMut.mutate({
              id: editingSession.id,
              data: buildUpdatePatch(form, sessionToForm(editingSession)),
            })
          }
          isPending={updateMut.isPending}
        />
      )}

      {attestTarget && (
        <AttestModal
          session={attestTarget.session}
          prefill={attestTarget.prefill}
          onClose={() => setAttestTarget(null)}
          onSubmit={(data) => attestMut.mutate({ id: attestTarget.session.id, data })}
          isPending={attestMut.isPending}
        />
      )}

      {declineTarget && (
        <DeclineModal
          session={declineTarget.session}
          prefill={declineTarget.prefill}
          onClose={() => setDeclineTarget(null)}
          onSubmit={(data) => declineMut.mutate({ id: declineTarget.session.id, data })}
          isPending={declineMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
