// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One management area: who owns it, whether it applies to the project, and
// its frame documents with the CDE revision in force, the binding badge and
// the change requests raised against them. A document gets its file here,
// goes to gate review from here and comes back to draft from here, so a gate
// that waits for a document can be cleared without leaving the page.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, FilePlus2, Lock, GitBranch, Paperclip } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  createChangeRequest,
  createDocument,
  getDocumentHistory,
  governanceErrorCode,
  governanceKeys,
  returnDocument,
  submitDocument,
  updateArea,
  type ChangeRequest,
  type ChangeRequestStatus,
  type FrameDocument,
  type GovernanceArea,
  type GovernanceGate,
  type GovernanceModel,
} from './api';
import { canAddDocument, canEditArea, canRaiseChange, documentVerdict, frozenInReview } from './access';
import { DocumentAttach } from './DocumentAttach';
import { DOCUMENT_TONE, PersonChip, ReasonedButton, ToneBadge, VerdictReason } from './GovernanceBits';
import { useInvalidateGovernance } from './hooks';
import { DOCUMENT_STATUS, catalogueName, refusalText, vocab, type KeyText, type LabelContext } from './labels';

const CR_STATUS: Record<ChangeRequestStatus, KeyText> = {
  submitted: ['governance.project.cr_status.submitted', 'Submitted'],
  approved: ['governance.project.cr_status.approved', 'Approved'],
  rejected: ['governance.project.cr_status.rejected', 'Rejected'],
  cancelled: ['governance.project.cr_status.cancelled', 'Cancelled'],
};

export const AREA_KEY_MAPS = { CR_STATUS };

export interface AreaPanelProps {
  projectId: string;
  area: GovernanceArea;
  model: GovernanceModel;
  documents: FrameDocument[];
  /** True until the project's frame documents have arrived. */
  documentsLoading?: boolean;
  /** Set when the frame documents could not be loaded, so an error never reads as an empty area. */
  documentsError?: unknown;
  onRetryDocuments?: () => void;
  changeRequests: ChangeRequest[];
  /** The project's gates, to name the gates a document type is required at. */
  gates: GovernanceGate[];
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
}

function DocumentRow({
  projectId,
  doc,
  areaCode,
  catalogueId,
  labels,
  changeRequests,
  onChanged,
}: {
  projectId: string;
  doc: FrameDocument;
  areaCode: string;
  catalogueId: string;
  labels: LabelContext;
  changeRequests: ChangeRequest[];
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [crOpen, setCrOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [impact, setImpact] = useState('');
  const history = useQuery({
    queryKey: governanceKeys.history(projectId, doc.id),
    queryFn: () => getDocumentHistory(projectId, doc.id),
    enabled: open,
  });
  const submit = useMutation({
    mutationFn: () => submitDocument(projectId, doc.id),
    onSuccess: onChanged,
    onError: (err) =>
      addToast({
        type: 'error',
        // The container is attached but holds no file: say what to do, not only what failed.
        title:
          governanceErrorCode(err) === 'no_pending_revision'
            ? t('governance.project.area.submit_needs_revision', {
                defaultValue: 'This document has no file yet. Add a file, then submit it for gate review.',
              })
            : refusalText(t, err),
      }),
  });
  const giveBack = useMutation({
    mutationFn: () => returnDocument(projectId, doc.id),
    onSuccess: onChanged,
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });
  const raise = useMutation({
    mutationFn: () => createChangeRequest(projectId, doc.id, { reason: reason.trim(), impact: impact.trim() }),
    onSuccess: () => {
      setCrOpen(false);
      setReason('');
      setImpact('');
      addToast({
        type: 'success',
        title: t('governance.project.area.cr_sent', { defaultValue: 'Change request sent for approval' }),
      });
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });
  const title = catalogueName(labels, { kind: 'doc', code: doc.doc_type, catalogueId, label: doc.name });
  const editable = !doc.read_only && doc.status === 'draft';
  const inForce = history.data?.revisions.find((r) => r.in_force);
  const crs = changeRequests.filter((c) => c.document_id === doc.id);

  return (
    <li className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="area-document">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-content-primary">
          {title}
        </span>
        <ToneBadge tone={DOCUMENT_TONE[doc.status]}>{vocab(t, DOCUMENT_STATUS, doc.status)}</ToneBadge>
        {doc.status === 'binding' && (
          <span className="inline-flex items-center gap-1 text-2xs font-medium text-semantic-success" data-testid="binding-badge">
            <Lock size={12} aria-hidden />
            {t('governance.project.area.binding_hint', { defaultValue: 'Binding, changes through a change request' })}
          </span>
        )}
        {doc.read_only && (
          <span className="text-2xs text-content-tertiary">
            {t('governance.project.area.read_only', { defaultValue: 'Read-only' })}
          </span>
        )}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {t('governance.project.area.revisions', { defaultValue: 'Revisions' })}
        </Button>
      </div>
      {!doc.container_id && (
        <p className="mt-1 text-xs text-content-tertiary" data-testid="document-no-file">
          {t('governance.project.area.no_file', {
            defaultValue: 'No file yet. Attach one so this document can go to gate review.',
          })}
        </p>
      )}

      {open && (
        <div className="mt-2 rounded-md bg-surface-secondary p-2 text-xs">
          {history.isLoading && <p className="text-content-tertiary">{t('governance.project.loading', { defaultValue: 'Loading...' })}</p>}
          {history.isError && (
            <p className="flex flex-wrap items-center gap-2 text-semantic-error" role="alert">
              {getErrorMessage(history.error)}
              <Button size="sm" variant="ghost" onClick={() => history.refetch()}>
                {t('governance.project.retry', { defaultValue: 'Try again' })}
              </Button>
            </p>
          )}
          {history.data && history.data.revisions.length === 0 && (
            <p className="text-content-tertiary">
              {t('governance.project.area.no_revisions', { defaultValue: 'The container has no revision yet.' })}
            </p>
          )}
          {history.data && history.data.revisions.length > 0 && (
            <ul className="space-y-0.5">
              {history.data.revisions.map((r) => (
                <li key={r.id} className="flex flex-wrap gap-2">
                  <span className="font-mono">{r.revision_code || r.revision_number}</span>
                  <span className="text-content-secondary">{r.file_name}</span>
                  <span className="text-content-tertiary">{r.created_at ? fmtDate(r.created_at) : ''}</span>
                  {r.in_force && (
                    <span className="font-medium text-semantic-success">
                      {t('governance.project.area.in_force', { defaultValue: 'In force' })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {inForce && doc.bound_content_hash && (
            <p className="mt-1 text-2xs text-content-tertiary">
              {t('governance.project.gate.snapshot_hash', { defaultValue: 'Content hash' })}{' '}
              <span className="font-mono">{doc.bound_content_hash.slice(0, 16)}</span>
            </p>
          )}
        </div>
      )}

      {crs.length > 0 && (
        <ul className="mt-2 space-y-1">
          {crs.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 text-xs" data-testid="change-request">
              <GitBranch size={12} className="text-content-tertiary" aria-hidden />
              <span className="text-content-primary">{c.reason}</span>
              <ToneBadge tone={c.status === 'approved' ? 'success' : c.status === 'submitted' ? 'blue' : 'neutral'}>
                {vocab(t, CR_STATUS, c.status)}
              </ToneBadge>
              <span className="text-content-tertiary">{c.created_at ? fmtDate(c.created_at) : ''}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap items-start gap-2">
        {editable && !attachOpen && (
          <ReasonedButton
            size="sm"
            variant={doc.container_id ? 'ghost' : 'primary'}
            icon={<Paperclip size={13} />}
            verdict={documentVerdict(doc, 'attach')}
            onClick={() => setAttachOpen(true)}
            data-testid="document-attach-open"
          >
            {doc.container_id
              ? t('governance.project.area.add_file', { defaultValue: 'Add a new file' })
              : t('governance.project.area.attach_file', { defaultValue: 'Attach a file' })}
          </ReasonedButton>
        )}
        {editable && (
          <ReasonedButton
            size="sm"
            variant="secondary"
            verdict={documentVerdict(doc, 'submit')}
            loading={submit.isPending}
            onClick={() => submit.mutate()}
          >
            {t('governance.project.area.submit_document', { defaultValue: 'Submit for gate review' })}
          </ReasonedButton>
        )}
        {doc.status === 'in_review' && !doc.read_only && (
          <ReasonedButton
            size="sm"
            variant="secondary"
            verdict={documentVerdict(doc, 'return')}
            loading={giveBack.isPending}
            onClick={() => giveBack.mutate()}
          >
            {t('governance.project.area.return_document', { defaultValue: 'Return to draft' })}
          </ReasonedButton>
        )}
        {doc.status === 'binding' && !crOpen && (
          <ReasonedButton size="sm" variant="secondary" verdict={canRaiseChange(doc)} onClick={() => setCrOpen(true)}>
            {t('governance.project.area.raise_change', { defaultValue: 'Raise change request' })}
          </ReasonedButton>
        )}
      </div>
      {attachOpen && (
        <DocumentAttach
          projectId={projectId}
          doc={doc}
          areaCode={areaCode}
          title={title}
          onCancel={() => setAttachOpen(false)}
          onDone={() => {
            setAttachOpen(false);
            onChanged();
          }}
        />
      )}
      {crOpen && (
        <div className="mt-2 space-y-2 rounded-md bg-surface-secondary p-2">
          <textarea
            rows={2}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
            aria-label={t('governance.project.area.cr_reason', { defaultValue: 'Reason for the change (required)' })}
            placeholder={t('governance.project.area.cr_reason', { defaultValue: 'Reason for the change (required)' })}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <textarea
            rows={2}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
            aria-label={t('governance.project.area.cr_impact', { defaultValue: 'Impact on cost, time or scope' })}
            placeholder={t('governance.project.area.cr_impact', { defaultValue: 'Impact on cost, time or scope' })}
            value={impact}
            onChange={(e) => setImpact(e.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={!reason.trim()} loading={raise.isPending} onClick={() => raise.mutate()}>
              {t('governance.project.area.cr_send', { defaultValue: 'Send for approval' })}
            </Button>
            <Button size="sm" variant="ghost" disabled={raise.isPending} onClick={() => setCrOpen(false)}>
              {t('governance.project.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/**
 * Start tracking a further frame document for the area. The catalogue names
 * the document types an area may hold; the ones already tracked are left out.
 */
function AddDocument({
  projectId,
  area,
  tracked,
  gates,
  catalogueId,
  labels,
  onChanged,
}: {
  projectId: string;
  area: GovernanceArea;
  tracked: FrameDocument[];
  gates: GovernanceGate[];
  catalogueId: string;
  labels: LabelContext;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [docType, setDocType] = useState('');
  const have = new Set(tracked.map((d) => d.doc_type));
  // The server says which types are held; the list on screen covers a document added a moment ago.
  const offered = (area.document_types ?? []).filter((d) => !d.tracked && !have.has(d.code));
  const add = useMutation({
    mutationFn: () => createDocument(projectId, { area_id: area.id, doc_type: docType }),
    onSuccess: () => {
      setDocType('');
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });
  const gateName = (code: string) => {
    const gate = gates.find((g) => g.code === code && !g.historic);
    return catalogueName(labels, { kind: 'gate', code, catalogueId, label: gate?.name });
  };

  // A server that does not list the area's document types gives nothing to offer, and nothing to claim.
  if (!area.document_types) return null;
  if (offered.length === 0) {
    return (
      <p className="mt-3 text-xs text-content-tertiary" data-testid="add-document-none">
        {area.document_types.length === 0
          ? t('governance.project.area.no_document_types', {
              defaultValue: 'The phase model names no frame document type for this area.',
            })
          : t('governance.project.area.all_documents_tracked', {
              defaultValue: 'Every frame document the phase model names for this area is tracked.',
            })}
      </p>
    );
  }
  const chosen = offered.find((d) => d.code === docType);
  return (
    <div className="mt-3 rounded-lg border border-dashed border-border-light p-3" data-testid="add-document">
      <p className="mb-2 text-xs font-semibold text-content-secondary">
        {t('governance.project.area.add_document_title', { defaultValue: 'Track another frame document' })}
      </p>
      <div className="flex flex-wrap items-start gap-2">
        <select
          aria-label={t('governance.project.area.document_type', { defaultValue: 'Document type' })}
          className="min-w-[14rem] rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary"
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
        >
          <option value="">{t('governance.project.area.choose_document_type', { defaultValue: 'Choose a document type' })}</option>
          {offered.map((d) => (
            <option key={d.code} value={d.code}>
              {catalogueName(labels, { kind: 'doc', code: d.code, catalogueId, label: d.name })}
            </option>
          ))}
        </select>
        <ReasonedButton
          size="sm"
          variant="secondary"
          icon={<FilePlus2 size={13} />}
          verdict={canAddDocument(area)}
          disabled={!docType}
          loading={add.isPending}
          onClick={() => add.mutate()}
          data-testid="add-document-send"
        >
          {t('governance.project.area.add_document', { defaultValue: 'Add document' })}
        </ReasonedButton>
      </div>
      {chosen && (
        <p className="mt-2 text-xs text-content-tertiary">
          {chosen.required_at_gates.length > 0
            ? t('governance.project.area.required_at', {
                defaultValue: 'Required at: {{gates}}',
                gates: fmtList(chosen.required_at_gates.map(gateName)),
              })
            : t('governance.project.area.not_required', { defaultValue: 'Optional: no gate requires it.' })}
        </p>
      )}
    </div>
  );
}

export function AreaPanel({
  projectId,
  area,
  model,
  documents,
  documentsLoading = false,
  documentsError = null,
  onRetryDocuments,
  changeRequests,
  gates,
  labels,
  personName,
  onBack,
}: AreaPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const invalidate = useInvalidateGovernance(projectId);
  const verdict = canEditArea(model);
  const [naRationale, setNaRationale] = useState(area.na_rationale);
  const catalogueId = model.catalogue_id;
  const name = catalogueName(labels, {
    kind: 'area',
    code: area.code,
    catalogueId,
    label: area.name,
    override: area.name_override,
  });

  const patch = useMutation({
    mutationFn: (body: Parameters<typeof updateArea>[2]) => updateArea(projectId, area.id, body),
    onSuccess: invalidate,
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });

  const docs = documents.filter((d) => d.area_id === area.id);
  const canOfferDocument = (area.document_types ?? []).some((d) => !d.tracked);
  const applicableVerdict = verdict ?? frozenInReview(gates);
  const ownerLabel = (id: string | null) =>
    id ? personName(id) ?? t('governance.project.unknown_person', { defaultValue: 'Project member' }) : null;

  return (
    <div className="space-y-5" data-testid="area-panel">
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>
          {t('governance.project.back_to_matrix', { defaultValue: 'Back to matrix' })}
        </Button>
        <h2 className="text-lg font-semibold text-content-primary">{name}</h2>
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        {(['owner_user_id', 'deputy_user_id'] as const).map((field) => (
          <div key={field} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
            <p className="mb-2 text-xs font-semibold text-content-secondary">
              {field === 'owner_user_id'
                ? t('governance.project.area.owner', { defaultValue: 'Owner' })
                : t('governance.project.area.deputy', { defaultValue: 'Deputy' })}
            </p>
            <div className="mb-2">
              {field === 'deputy_user_id' && !area.deputy_user_id ? (
                <span className="text-xs text-content-tertiary">
                  {t('governance.project.area.no_deputy', { defaultValue: 'No deputy' })}
                </span>
              ) : (
                <PersonChip name={ownerLabel(area[field])} />
              )}
            </div>
            {verdict ? (
              <ReasonedButton size="sm" variant="secondary" verdict={verdict}>
                {t('governance.project.area.assign', { defaultValue: 'Assign' })}
              </ReasonedButton>
            ) : (
              <div className={clsx('space-y-2', patch.isPending && 'pointer-events-none opacity-60')}>
                {/* The picker reports an empty value as soon as somebody types to search, so only a
                    chosen person is saved here; taking the person off is its own button. */}
                <ProjectPeopleSelect
                  key={`${field}:${area[field] ?? ''}`}
                  projectId={projectId}
                  value=""
                  onChange={(userId) => {
                    if (userId && userId !== area[field]) {
                      patch.mutate(field === 'owner_user_id' ? { owner_user_id: userId } : { deputy_user_id: userId });
                    }
                  }}
                  placeholder={t('governance.project.area.choose_person', { defaultValue: 'Choose a project member' })}
                />
                {area[field] && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={patch.isPending}
                    onClick={() => patch.mutate(field === 'owner_user_id' ? { owner_user_id: null } : { deputy_user_id: null })}
                    data-testid={`unassign-${field}`}
                  >
                    {field === 'owner_user_id'
                      ? t('governance.project.area.remove_owner', { defaultValue: 'Remove the owner' })
                      : t('governance.project.area.remove_deputy', { defaultValue: 'Remove the deputy' })}
                  </Button>
                )}
              </div>
            )}
          </div>
        ))}
      </section>
      {area.owner_user_id === null && (
        <p className="text-xs text-content-secondary">
          {t('governance.project.area.owner_explainer', {
            defaultValue: 'The owner confirms readiness at each gate. Changing the owner resets this area on gates not yet decided.',
          })}
        </p>
      )}

      <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
        <label className="flex items-center gap-2 text-sm font-medium text-content-primary">
          <input
            type="checkbox"
            checked={area.applicable}
            disabled={!!applicableVerdict || patch.isPending || (area.applicable && !naRationale.trim())}
            onChange={(e) =>
              patch.mutate(e.target.checked ? { applicable: true } : { applicable: false, na_rationale: naRationale.trim() })
            }
          />
          {t('governance.project.area.applicable', { defaultValue: 'Applies to this project' })}
        </label>
        <textarea
          rows={2}
          className="mt-2 w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
          aria-label={t('governance.project.area.na_rationale', {
            defaultValue: 'Why the area does not apply (required to switch it off)',
          })}
          placeholder={t('governance.project.area.na_rationale', {
            defaultValue: 'Why the area does not apply (required to switch it off)',
          })}
          value={naRationale}
          disabled={!!verdict || !area.applicable}
          onChange={(e) => setNaRationale(e.target.value)}
        />
        <VerdictReason verdict={applicableVerdict} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {t('governance.project.area.documents_title', { defaultValue: 'Frame documents' })}
        </h3>
        {documentsLoading ? (
          <p className="text-sm text-content-tertiary" data-testid="area-documents-loading">
            {t('governance.project.loading', { defaultValue: 'Loading...' })}
          </p>
        ) : documentsError ? (
          <p className="flex flex-wrap items-center gap-2 text-sm text-semantic-error" role="alert" data-testid="area-documents-error">
            {t('governance.project.area.documents_failed', { defaultValue: 'The frame documents could not be loaded.' })}{' '}
            {getErrorMessage(documentsError)}
            {onRetryDocuments && (
              <Button size="sm" variant="ghost" onClick={onRetryDocuments}>
                {t('governance.project.retry', { defaultValue: 'Try again' })}
              </Button>
            )}
          </p>
        ) : docs.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="area-no-documents">
            {canOfferDocument
              ? t('governance.project.area.no_documents_yet', {
                  defaultValue:
                    'No frame document is tracked for this area yet. Add the first one below, then attach its file and submit it for gate review.',
                })
              : t('governance.project.area.no_documents_tracked', {
                  defaultValue: 'No frame document is tracked for this area yet.',
                })}
          </p>
        ) : (
          <ul className="space-y-2">
            {docs.map((d) => (
              <DocumentRow
                key={d.id}
                projectId={projectId}
                doc={d}
                areaCode={area.code}
                catalogueId={catalogueId}
                labels={labels}
                changeRequests={changeRequests}
                onChanged={invalidate}
              />
            ))}
          </ul>
        )}
        {!documentsLoading && !documentsError && (
        <AddDocument
          projectId={projectId}
          area={area}
          tracked={docs}
          gates={gates}
          catalogueId={catalogueId}
          labels={labels}
          onChanged={invalidate}
        />
        )}
      </section>
    </div>
  );
}
