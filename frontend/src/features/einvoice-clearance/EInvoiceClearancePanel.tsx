// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * E-invoice Clearance — what a tax authority actually answered about an invoice.
 *
 * The module is a state machine, so the screen is arranged around one: a
 * document's status is the first thing on the row, and the acts offered under
 * it are exactly the ones that state leaves open. The two irreversible ones
 * cost a confirmation, and the two that need a sentence from the operator get a
 * form before that confirmation rather than a prompt inside it.
 *
 * The screen's whole vocabulary — the statuses, the country registry, the
 * installed adapters — is read from /meta rather than written down here, so a
 * country added to the backend registry appears without a frontend change.
 *
 * Two shapes of the contract drive the layout more than anything else. A
 * rejection is a **200** carrying the authority's own code and words, so the
 * success branch of every submission has to ask what came back. And a refusal
 * carries **findings** naming the field that blocked it, which `getErrorMessage`
 * drops on the floor — so a refused act renders the findings, not just a toast.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Ban,
  Building2,
  Download,
  FileText,
  History,
  Landmark,
  Pencil,
  Plus,
  Receipt,
  Send,
  ShieldCheck,
  Trash2,
} from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { ClearanceDocumentForm } from './ClearanceDocumentForm';
import { ClearanceRegistrationForm } from './ClearanceRegistrationForm';
import {
  type ClearanceDocument,
  type ClearanceEvent,
  type ClearanceFinding,
  type ClearanceMeta,
  type ClearanceProfile,
  type CountryRegime,
  type DocumentCreateBody,
  type ProfileWriteBody,
  type ResolveBody,
  cancelDocument,
  createDocument,
  createProfile,
  deleteProfile,
  fetchDocumentPayload,
  getMeta,
  listDocumentEvents,
  listDocuments,
  listProfiles,
  resolveDocument,
  submitDocument,
  updateProfile,
  validateDocument,
} from './api';
import {
  availableActions,
  countryRegime,
  findingsFromError,
  isInDoubt,
  onlyWarnings,
  severityVariant,
  statusVariant,
} from './documentStatus';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

// English fallbacks for the computed `einvoice_clearance.event.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const CLEARANCE_EVENT_LABELS: Record<string, string> = {
  created: 'Created', updated: 'Updated', validated: 'Validated', queued: 'Queued', submitted: 'Submitted',
  cleared: 'Cleared', reported: 'Reported', delivered: 'Delivered', rejected: 'Rejected',
  cancelled: 'Cancelled', note: 'Note'
};


export function EInvoiceClearancePanel() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  const metaQuery = useQuery({
    queryKey: ['einvoice-clearance', 'meta'],
    queryFn: getMeta,
    staleTime: 5 * 60 * 1000,
  });

  const documentsQuery = useQuery({
    queryKey: ['einvoice-clearance', 'documents', activeProjectId, statusFilter],
    queryFn: () =>
      listDocuments({
        projectId: activeProjectId as string,
        status: statusFilter || undefined,
      }),
    enabled: !!activeProjectId,
  });

  const profilesQuery = useQuery({
    queryKey: ['einvoice-clearance', 'profiles'],
    queryFn: () => listProfiles(),
    staleTime: 5 * 60 * 1000,
  });

  // Above the early return, with every other hook. React counts hooks per
  // render and the no-project branch below returns before this line, so a hook
  // placed after it is called on one branch and not the other.
  const [creating, setCreating] = useState(false);
  const panelToast = useToastStore((s) => s.addToast);

  const createDocOnce = useSingleFlight();
  const createDoc = useMutation({
    mutationFn: (body: DocumentCreateBody) => createDocument(body),
    onSuccess: (result) => {
      setCreating(false);
      setSelectedId(result.document.id);
      panelToast({
        type: result.findings.length > 0 ? 'warning' : 'success',
        title: t('einvoice_clearance.document_created', { defaultValue: 'Document prepared' }),
        // The server checks on the way in. Saying how many things it found is
        // the difference between a document that is ready and one that is not.
        message:
          result.findings.length > 0
            ? t('einvoice_clearance.document_created_findings', {
                defaultValue: 'The country check named {{count}} thing to fix before sending.',
                count: result.findings.length,
              })
            : undefined,
      });
      void queryClient.invalidateQueries({ queryKey: ['einvoice-clearance'] });
    },
    onError: (err) => {
      panelToast({
        type: 'error',
        title: t('einvoice_clearance.document_create_failed', {
          defaultValue: 'The document was not prepared',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  if (!activeProjectId) {
    return (
      <EmptyState
        icon={<Landmark className="h-8 w-8" />}
        title={t('einvoice_clearance.no_project_title', { defaultValue: 'Pick a project first' })}
        description={t('einvoice_clearance.no_project_body', {
          defaultValue:
            'Clearance documents belong to a project, because the invoices behind them do. Registrations do not: a company registered in Mexico is registered on every job it runs there.',
        })}
      />
    );
  }

  const meta = metaQuery.data;
  const documents = documentsQuery.data ?? [];
  const profiles = profilesQuery.data ?? [];
  // A document can only be filed under a registration that is switched on and
  // has an adapter. Offering the others would produce a document that cannot be
  // sent, and the reason would only surface at submission time.
  const filingProfiles = profiles.filter((p) => p.is_active && p.adapter_key !== '');
  const selected = documents.find((d) => d.id === selectedId) ?? null;
  const inDoubtCount = documents.filter((d) => isInDoubt(d.status)).length;
  const rejectedCount = documents.filter((d) => d.status === 'rejected').length;

  const onChanged = () => {
    void queryClient.invalidateQueries({ queryKey: ['einvoice-clearance'] });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-content-secondary">
            {t('einvoice_clearance.filter_status', { defaultValue: 'Status' })}
          </span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-border-light bg-surface-primary p-1.5 text-sm"
          >
            <option value="">
              {t('einvoice_clearance.filter_status_any', { defaultValue: 'Any status' })}
            </option>
            {/* The vocabulary comes from the server. A status added there shows
                up in this list without this file changing. */}
            {(meta?.statuses ?? []).map((status) => (
              <option key={status} value={status}>
                {t(`einvoice_clearance.status.${status}`, { defaultValue: status })}
              </option>
            ))}
          </select>
        </label>

        <span className="text-sm text-content-secondary">
          {t('einvoice_clearance.summary_counts', {
            defaultValue: '{{total}} on this project, {{rejected}} rejected',
            total: documents.length,
            rejected: rejectedCount,
          })}
        </span>

        {inDoubtCount > 0 && (
          <Badge variant="warning" dot>
            {t('einvoice_clearance.in_doubt_badge', {
              defaultValue: '{{count}} awaiting an answer',
              count: inDoubtCount,
            })}
          </Badge>
        )}
      </div>

      {/* Losing /meta is not cosmetic: the country registry is what says whether
          a country can be withdrawn from at all, so without it the screen
          quietly offers no withdrawal anywhere. Say so rather than look empty. */}
      {metaQuery.isError && (
        <p className="rounded border border-semantic-warning bg-semantic-warning-bg p-2 text-xs">
          {t('einvoice_clearance.meta_unavailable', {
            defaultValue:
              'The country registry could not be read, so this screen cannot say which platform a document belongs to or whether that country accepts a withdrawal. Statuses and documents below are still the real ones.',
          })}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <section aria-label={t('einvoice_clearance.list_label', { defaultValue: 'Clearance documents' })}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">
              {t('einvoice_clearance.list_title', { defaultValue: 'Documents on this project' })}
            </h3>
            {!creating && (
              <Button size="sm" onClick={() => setCreating(true)} disabled={filingProfiles.length === 0}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t('einvoice_clearance.document_new', { defaultValue: 'Prepare a document' })}
              </Button>
            )}
          </div>

          {creating && (
            <div className="mb-3">
              <ClearanceDocumentForm
                meta={meta}
                profiles={filingProfiles}
                projectId={activeProjectId}
                pending={createDoc.isPending}
                onCancel={() => setCreating(false)}
                onSubmit={(body) => createDocOnce(() => createDoc.mutateAsync(body))}
              />
            </div>
          )}

          {documentsQuery.isLoading ? (
            <p className="text-sm text-content-secondary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : documents.length === 0 ? (
            <EmptyState
              icon={<Receipt className="h-8 w-8" />}
              title={t('einvoice_clearance.empty_title', { defaultValue: 'No documents prepared yet' })}
              description={t('einvoice_clearance.empty_body', {
                defaultValue:
                  'A clearance document is one invoice prepared for one country platform. It is created from the invoice it clears, then checked, sent and answered here.',
              })}
              action={
                creating ? undefined : filingProfiles.length > 0 ? (
                  <Button size="sm" onClick={() => setCreating(true)}>
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    {t('einvoice_clearance.document_new', { defaultValue: 'Prepare a document' })}
                  </Button>
                ) : (
                  // Not a button that would open a form with nothing to choose
                  // in it. Say which step is actually missing.
                  <p className="text-xs text-content-tertiary">
                    {t('einvoice_clearance.document_needs_profile', {
                      defaultValue:
                        'A document is filed under a registration, and there is no active one with an adapter yet. Register a country below first.',
                    })}
                  </p>
                )
              }
            />
          ) : (
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {documents.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(doc.id)}
                    aria-current={selectedId === doc.id}
                    className={`flex w-full flex-col gap-1 p-3 text-left hover:bg-surface-secondary ${
                      selectedId === doc.id ? 'bg-surface-secondary' : ''
                    }`}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">
                        {doc.invoice_number ||
                          t('einvoice_clearance.unnumbered', { defaultValue: 'No invoice number' })}
                      </span>
                      <Badge variant={statusVariant(doc.status)} size="sm">
                        {t(`einvoice_clearance.status.${doc.status}`, { defaultValue: doc.status })}
                      </Badge>
                      {doc.retry_count > 0 && (
                        <Badge variant="neutral" size="sm">
                          {/* `attempt`, not `count`: this is an index, not a
                              quantity, so it must not wake the plural resolver
                              and demand CLDR forms of a sentence that has one. */}
                          {t('einvoice_clearance.attempt_number', {
                            defaultValue: 'Attempt {{attempt}}',
                            attempt: doc.retry_count + 1,
                          })}
                        </Badge>
                      )}
                    </span>
                    <span className="text-sm text-content-secondary">
                      {formatCurrency(doc.total_amount, doc.currency_code)}
                      {' · '}
                      {doc.country}
                      {' · '}
                      {t(`einvoice_clearance.regime.${doc.regime}`, { defaultValue: doc.regime })}
                    </span>
                    {/* The authority's code belongs on the row, not two clicks
                        away: it is the first thing anybody is asked about. */}
                    {doc.rejection_code && (
                      <span className="font-mono text-xs text-semantic-error">{doc.rejection_code}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label={t('einvoice_clearance.detail_label', { defaultValue: 'Document detail' })}>
          {!selected ? (
            <EmptyState
              icon={<ShieldCheck className="h-8 w-8" />}
              title={t('einvoice_clearance.pick_title', { defaultValue: 'Pick a document' })}
              description={t('einvoice_clearance.pick_body', {
                defaultValue:
                  'What the authority answered, exactly what was sent, the trail behind it, and the acts its current state leaves open.',
              })}
            />
          ) : (
            <DocumentDetail
              key={selected.id}
              doc={selected}
              meta={meta}
              onChanged={onChanged}
            />
          )}
        </section>
      </div>

      <ProfilesSection
        profiles={profiles}
        loading={profilesQuery.isLoading}
        meta={meta}
        onChanged={onChanged}
      />
    </div>
  );
}

/* ── Detail ────────────────────────────────────────────────────────────── */

type OpenForm = 'cancel' | 'resolve' | null;

function DocumentDetail({
  doc,
  meta,
  onChanged,
}: {
  doc: ClearanceDocument;
  meta: ClearanceMeta | undefined;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [findings, setFindings] = useState<ClearanceFinding[]>([]);
  const [refused, setRefused] = useState(false);
  const [waivable, setWaivable] = useState(false);
  const [openForm, setOpenForm] = useState<OpenForm>(null);
  const [confirmSubmit, setConfirmSubmit] = useState<{ acceptWarnings: boolean } | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<string | null>(null);
  const [showPayload, setShowPayload] = useState(false);

  const regime = countryRegime(meta?.countries ?? [], doc.country);
  // The server reads the regime off the country registry, so where meta has an
  // entry it is the same answer the server will give; the document's stored
  // regime is the fallback for a country the registry no longer lists.
  const effectiveRegime = regime?.regime ?? doc.regime;
  const actions = availableActions(doc.status, { cancellable: regime?.is_cancellable ?? false });

  const eventsQuery = useQuery({
    queryKey: ['einvoice-clearance', 'events', doc.id],
    queryFn: () => listDocumentEvents(doc.id),
  });

  const showFindings = (next: ClearanceFinding[], wasRefused: boolean) => {
    setFindings(next);
    setRefused(wasRefused);
    setWaivable(wasRefused && onlyWarnings(next));
  };

  const refusalToast = (titleKey: string, fallback: string) => (err: unknown) => {
    // Both dialogs close first. A refusal renders its findings under the modal
    // that caused it, and leaving the modal up hides the answer to the question
    // the operator just asked.
    setConfirmSubmit(null);
    setConfirmCancel(null);
    // The findings are the part `getErrorMessage` cannot reach, so they go to
    // the panel; the refusal's own sentence goes to the toast.
    showFindings(findingsFromError(err), true);
    addToast({
      type: 'error',
      title: t(titleKey, { defaultValue: fallback }),
      message: getErrorMessage(err),
    });
  };

  /** The authority's own code and words, joined but never rewritten. */
  const verbatim = (code: string, message: string, adapterLine: string): string | undefined =>
    [code, message || adapterLine].filter(Boolean).join(' · ') || undefined;

  const check = useMutation({
    mutationFn: () => validateDocument(doc.id),
    onSuccess: (result) => {
      showFindings(result.findings, false);
      addToast(
        result.findings.length === 0
          ? {
              type: 'success',
              title: t('einvoice_clearance.check_clean', {
                defaultValue: 'Checked against the country rules; nothing blocking',
              }),
            }
          : {
              type: 'warning',
              title: t('einvoice_clearance.check_found', {
                defaultValue: 'The country rules found something',
              }),
            },
      );
      onChanged();
    },
    onError: refusalToast('einvoice_clearance.check_failed', 'Could not check the document'),
  });

  const send = useMutation({
    mutationFn: (acceptWarnings: boolean) => submitDocument(doc.id, acceptWarnings),
    onSuccess: (result) => {
      setConfirmSubmit(null);
      showFindings(result.findings, false);
      if (result.accepted) {
        addToast({
          type: 'success',
          title: t('einvoice_clearance.submit_accepted', {
            defaultValue: 'The platform accepted the document',
          }),
          message: result.message || undefined,
        });
      } else {
        // A rejection is a 200. Reporting it as a success because the HTTP call
        // worked is the single easiest way to lie to an accountant on this
        // screen, so the answer decides the toast, not the status code.
        addToast({
          type: 'error',
          title: t('einvoice_clearance.submit_rejected', {
            defaultValue: 'The authority rejected the document',
          }),
          message: verbatim(result.rejection_code, result.rejection_message, result.message),
        });
      }
      onChanged();
    },
    onError: refusalToast('einvoice_clearance.submit_refused', 'The document was not sent'),
  });

  const withdraw = useMutation({
    mutationFn: (reason: string) => cancelDocument(doc.id, reason),
    onSuccess: (result) => {
      setConfirmCancel(null);
      setOpenForm(null);
      showFindings(result.findings, false);
      addToast(
        result.accepted
          ? {
              type: 'success',
              title: t('einvoice_clearance.cancel_accepted', {
                defaultValue: 'The platform accepted the withdrawal',
              }),
              message: result.message || undefined,
            }
          : {
              type: 'error',
              title: t('einvoice_clearance.cancel_rejected', {
                defaultValue: 'The platform refused the withdrawal',
              }),
              message: verbatim(result.rejection_code, result.rejection_message, result.message),
            },
      );
      onChanged();
    },
    onError: refusalToast('einvoice_clearance.cancel_refused', 'The document was not withdrawn'),
  });

  const record = useMutation({
    mutationFn: (body: ResolveBody) => resolveDocument(doc.id, body),
    onSuccess: () => {
      setOpenForm(null);
      showFindings([], false);
      addToast({
        type: 'success',
        title: t('einvoice_clearance.resolve_recorded', {
          defaultValue: 'Recorded what the platform did',
        }),
      });
      onChanged();
    },
    onError: refusalToast('einvoice_clearance.resolve_failed', 'Could not record the outcome'),
  });

  const events = eventsQuery.data ?? [];

  return (
    <div className="space-y-4 rounded-lg border border-border-light p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-lg font-semibold">
            {doc.invoice_number ||
              t('einvoice_clearance.unnumbered', { defaultValue: 'No invoice number' })}
          </p>
          <p className="text-sm text-content-secondary">
            {formatCurrency(doc.total_amount, doc.currency_code)}
            {doc.invoice_date && ` · ${doc.invoice_date}`}
          </p>
        </div>
        <Badge variant={statusVariant(doc.status)}>
          {t(`einvoice_clearance.status.${doc.status}`, { defaultValue: doc.status })}
        </Badge>
      </div>

      {/* What this country does to an invoice, in its own words. */}
      <p className="text-xs text-content-tertiary">
        {regime?.label || doc.country}
        {' · '}
        {t(`einvoice_clearance.regime.${effectiveRegime}`, { defaultValue: effectiveRegime })}
        {doc.document_format && ` · ${doc.document_format}`}
      </p>

      <AuthorityAnswer doc={doc} regime={regime} />

      {isInDoubt(doc.status) && (
        <p className="rounded border border-semantic-warning bg-semantic-warning-bg p-2 text-xs">
          {t('einvoice_clearance.in_doubt_body', {
            defaultValue:
              'This document was sent and no answer was recorded against it, so nobody here knows whether it arrived. Sending it again risks a second cleared invoice for one sale. Read the outcome off the platform and record it below.',
          })}
        </p>
      )}

      {/* The acts this state leaves open, and nothing else. */}
      <div className="flex flex-wrap gap-2">
        {actions.includes('validate') && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => check.mutate()}
            disabled={check.isPending}
          >
            <ShieldCheck className="mr-1 h-4 w-4" />
            {t('einvoice_clearance.action_validate', { defaultValue: 'Check against the rules' })}
          </Button>
        )}
        {actions.includes('submit') && (
          <Button
            size="sm"
            onClick={() => setConfirmSubmit({ acceptWarnings: false })}
            disabled={send.isPending}
          >
            <Send className="mr-1 h-4 w-4" />
            {t('einvoice_clearance.action_submit', { defaultValue: 'Send to the platform' })}
          </Button>
        )}
        {actions.includes('submit') && waivable && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setConfirmSubmit({ acceptWarnings: true })}
            disabled={send.isPending}
          >
            {t('einvoice_clearance.action_submit_anyway', {
              defaultValue: 'Acknowledge the warnings and send',
            })}
          </Button>
        )}
        {actions.includes('resolve') && (
          <Button
            size="sm"
            onClick={() => setOpenForm(openForm === 'resolve' ? null : 'resolve')}
            disabled={record.isPending}
          >
            <History className="mr-1 h-4 w-4" />
            {t('einvoice_clearance.action_resolve', { defaultValue: 'Record what the platform did' })}
          </Button>
        )}
        {actions.includes('cancel') && (
          <Button
            size="sm"
            variant="danger"
            onClick={() => setOpenForm(openForm === 'cancel' ? null : 'cancel')}
            disabled={withdraw.isPending}
          >
            <Ban className="mr-1 h-4 w-4" />
            {t('einvoice_clearance.action_cancel', { defaultValue: 'Withdraw from the platform' })}
          </Button>
        )}
      </div>

      {/* Where a country has no cancellation flow, say what it does instead
          rather than showing a button that is certain to be refused. */}
      {['cleared', 'reported', 'delivered'].includes(doc.status) && regime && !regime.is_cancellable && (
        <p className="text-xs text-content-tertiary">
          {t('einvoice_clearance.not_cancellable', {
            defaultValue:
              '{{platform}} has no withdrawal flow. The correction here is a further document: {{mechanism}}.',
            platform: regime.platform,
            mechanism: regime.correction_mechanism,
          })}
        </p>
      )}
      {regime?.is_cancellable && regime.cancellation_window_days !== null && (
        <p className="text-xs text-content-tertiary">
          {t('einvoice_clearance.cancellation_window', {
            defaultValue: '{{platform}} accepts a withdrawal within {{days}} days of clearance.',
            platform: regime.platform,
            days: regime.cancellation_window_days,
          })}
        </p>
      )}

      {openForm === 'cancel' && (
        <CancelForm
          platform={regime?.platform || doc.country}
          pending={withdraw.isPending}
          onSubmit={(reason) => setConfirmCancel(reason)}
          onCancel={() => setOpenForm(null)}
        />
      )}

      {openForm === 'resolve' && (
        <ResolveForm
          identifierLabel={regime?.identifier_label || ''}
          identifierRequired={effectiveRegime === 'clearance'}
          pending={record.isPending}
          onSubmit={(body) => record.mutate(body)}
          onCancel={() => setOpenForm(null)}
        />
      )}

      <FindingsList findings={findings} refused={refused} />

      <CountryFields fields={doc.country_fields} />

      <PayloadView
        doc={doc}
        open={showPayload}
        onToggle={() => setShowPayload((v) => !v)}
      />

      <TrailList events={events} loading={eventsQuery.isLoading} />

      <ConfirmDialog
        open={confirmSubmit !== null}
        variant="danger"
        loading={send.isPending}
        title={t('einvoice_clearance.confirm_submit_title', {
          defaultValue: 'Send this document to the platform?',
        })}
        message={
          confirmSubmit?.acceptWarnings
            ? t('einvoice_clearance.confirm_submit_waived', {
                defaultValue:
                  'The warnings stay on the record and the document goes as it stands. This cannot be undone, and a document the platform accepts can only be withdrawn where the country has a withdrawal flow.',
              })
            : t('einvoice_clearance.confirm_submit_body', {
                defaultValue:
                  'The document goes to {{platform}} and cannot be recalled. Where the platform accepts it, it can only be withdrawn if that country has a withdrawal flow.',
                platform: regime?.platform || doc.country,
              })
        }
        confirmLabel={t('einvoice_clearance.confirm_submit_action', { defaultValue: 'Send it' })}
        onConfirm={() => send.mutate(confirmSubmit?.acceptWarnings ?? false)}
        onCancel={() => setConfirmSubmit(null)}
      />

      <ConfirmDialog
        open={confirmCancel !== null}
        variant="danger"
        loading={withdraw.isPending}
        title={t('einvoice_clearance.confirm_cancel_title', {
          defaultValue: 'Withdraw this document from the platform?',
        })}
        message={t('einvoice_clearance.confirm_cancel_body', {
          defaultValue:
            'The platform is asked to cancel a document it has already accepted. The reason you gave is filed with the cancellation and cannot be edited afterwards.',
        })}
        confirmLabel={t('einvoice_clearance.confirm_cancel_action', { defaultValue: 'Withdraw it' })}
        onConfirm={() => withdraw.mutate(confirmCancel ?? '')}
        onCancel={() => setConfirmCancel(null)}
      />
    </div>
  );
}

/* ── What the authority said ───────────────────────────────────────────── */

/**
 * The authority's answer, in the authority's words.
 *
 * Nothing here goes through `t()`. A rejection code and the sentence beside it
 * are what the accountant will be asked to explain, and a translated or tidied
 * version of either is a different fact.
 */
function AuthorityAnswer({
  doc,
  regime,
}: {
  doc: ClearanceDocument;
  regime: CountryRegime | undefined;
}) {
  const { t } = useTranslation();
  const hasRejection = !!(doc.rejection_code || doc.rejection_message);

  if (!doc.authority_identifier && !hasRejection && !doc.cancellation_reason) return null;

  return (
    <div className="space-y-2">
      {doc.authority_identifier && (
        <div className="rounded border border-semantic-success bg-semantic-success-bg p-3">
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {/* The registry names this in the words the accountant hears it
                called: "UUID (Folio Fiscal)", "chave de acesso", "IRN". */}
            {regime?.identifier_label ||
              t('einvoice_clearance.identifier_label', { defaultValue: 'Authority identifier' })}
          </p>
          <p className="mt-1 break-all font-mono text-sm font-semibold">{doc.authority_identifier}</p>
        </div>
      )}

      {hasRejection && (
        <div className="rounded border border-semantic-error bg-semantic-error-bg p-3">
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('einvoice_clearance.rejection_title', { defaultValue: 'What the authority answered' })}
          </p>
          {doc.rejection_code && (
            <p className="mt-1 font-mono text-sm font-semibold">{doc.rejection_code}</p>
          )}
          {doc.rejection_message && (
            <p className="mt-1 whitespace-pre-wrap text-sm">{doc.rejection_message}</p>
          )}
        </div>
      )}

      {doc.cancellation_reason && (
        <div className="rounded border border-border-light p-3">
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('einvoice_clearance.cancellation_reason_title', {
              defaultValue: 'Reason filed with the withdrawal',
            })}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{doc.cancellation_reason}</p>
        </div>
      )}
    </div>
  );
}

/* ── Findings ──────────────────────────────────────────────────────────── */

function FindingsList({ findings, refused }: { findings: ClearanceFinding[]; refused: boolean }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;

  return (
    <div>
      <h4 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <AlertTriangle className="h-4 w-4 text-semantic-warning" />
        {refused
          ? t('einvoice_clearance.findings_refused_title', {
              defaultValue: 'Why it was not sent',
            })
          : t('einvoice_clearance.findings_title', { defaultValue: 'What the rules say' })}
      </h4>
      <ul className="space-y-1">
        {/* Indexed, because one rule can report twice: a completeness rule
            naming two missing national fields emits two findings under one
            rule_id, and keying on the id alone would drop the second. */}
        {findings.map((f, i) => (
          <li key={`${i}-${f.rule_id}`} className="flex items-start gap-2 text-sm">
            <Badge variant={severityVariant(f.severity)} size="sm">
              {f.severity}
            </Badge>
            <span>
              {/* The rule's English is the fallback for a locale with no string
                  for this key yet. */}
              {t(f.key, { defaultValue: f.message })}
              {f.suggestion && (
                <em className="block text-xs not-italic text-content-tertiary">{f.suggestion}</em>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── National fields ───────────────────────────────────────────────────── */

/**
 * The fields the EN 16931 semantic model has nowhere to put.
 *
 * Worth showing beside the payload: a missing one of these is the commonest
 * reason a country rejects a document, and the rule that blocks it names the
 * field by the key that appears here.
 */
function CountryFields({ fields }: { fields: Record<string, unknown> }) {
  const { t } = useTranslation();
  const entries = Object.entries(fields ?? {});
  if (entries.length === 0) return null;

  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-content-secondary">
        {t('einvoice_clearance.country_fields_title', {
          defaultValue: 'National fields carried on this document',
        })}
      </summary>
      <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-mono text-content-tertiary">{key}</dt>
            <dd className="break-all">{String(value ?? '')}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/* ── Payload ───────────────────────────────────────────────────────────── */

/**
 * Exactly what was or will be sent.
 *
 * "Show me what we actually sent" is the first question in any dispute, so this
 * serves the stored bytes rather than a re-rendering of them. A stored size of
 * zero is a real state, not a loading failure: a national format the EN 16931
 * engine cannot build arrives with its payload supplied from elsewhere, or not
 * yet supplied at all.
 */
function PayloadView({
  doc,
  open,
  onToggle,
}: {
  doc: ClearanceDocument;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();

  const payloadQuery = useQuery({
    queryKey: ['einvoice-clearance', 'payload', doc.id, doc.payload_hash],
    queryFn: () => fetchDocumentPayload(doc.id),
    enabled: open && doc.payload_size > 0,
    staleTime: 5 * 60 * 1000,
  });

  if (doc.payload_size === 0) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('einvoice_clearance.payload_absent', {
          defaultValue:
            'No document is stored against this row yet. Countries whose national format the EN 16931 engine does not build take their payload from whatever produces it.',
        })}
      </p>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onToggle}>
          <FileText className="mr-1 h-4 w-4" />
          {open
            ? t('einvoice_clearance.payload_hide', { defaultValue: 'Hide what was sent' })
            : t('einvoice_clearance.payload_show', { defaultValue: 'Show exactly what was sent' })}
        </Button>
        {payloadQuery.data && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              triggerDownload(
                new Blob([payloadQuery.data.text], {
                  type: payloadQuery.data.mediaType || doc.payload_media_type,
                }),
                payloadQuery.data.filename,
              )
            }
          >
            <Download className="mr-1 h-4 w-4" />
            {t('einvoice_clearance.payload_download', { defaultValue: 'Download it' })}
          </Button>
        )}
        <span className="font-mono text-xs text-content-tertiary">
          {doc.payload_media_type}
          {' · '}
          {t('einvoice_clearance.payload_bytes', {
            defaultValue: '{{count}} bytes',
            count: doc.payload_size,
          })}
        </span>
      </div>

      {open && (
        <div className="mt-2">
          {payloadQuery.isLoading ? (
            <p className="text-sm text-content-secondary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : payloadQuery.isError ? (
            <p className="text-sm text-semantic-error">{getErrorMessage(payloadQuery.error)}</p>
          ) : (
            <pre className="max-h-80 overflow-auto rounded border border-border-light bg-surface-secondary p-2 text-xs">
              {payloadQuery.data?.text}
            </pre>
          )}
          {/* The hash is what proves the bytes above are the bytes that went. */}
          <p className="mt-1 break-all font-mono text-[11px] text-content-tertiary">
            {doc.payload_hash}
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Trail ─────────────────────────────────────────────────────────────── */

function TrailList({ events, loading }: { events: ClearanceEvent[]; loading: boolean }) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <p className="text-sm text-content-secondary">
        {t('common.loading', { defaultValue: 'Loading...' })}
      </p>
    );
  }
  if (events.length === 0) return null;

  return (
    <div>
      <h4 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <History className="h-4 w-4 text-content-secondary" />
        {t('einvoice_clearance.trail_title', { defaultValue: 'The trail' })}
      </h4>
      <ol className="space-y-1">
        {events.map((ev) => (
          <li key={ev.id} className="flex flex-wrap items-start gap-2 text-sm">
            <span className="font-mono text-xs text-content-tertiary">{ev.sequence}</span>
            <Badge variant={statusVariant(ev.to_status)} size="sm">
              {t(`einvoice_clearance.event.${ev.event_type}`, { defaultValue: CLEARANCE_EVENT_LABELS[ev.event_type] ?? ev.event_type })}
            </Badge>
            <span className="text-xs text-content-tertiary">
              {ev.from_status || '-'}
              {' → '}
              {ev.to_status || '-'}
            </span>
            <span className="text-content-secondary">{ev.message}</span>
            {ev.authority_code && (
              <span className="font-mono text-xs text-semantic-error">{ev.authority_code}</span>
            )}
            {Object.keys(ev.raw_response ?? {}).length > 0 && (
              <details className="w-full">
                <summary className="cursor-pointer text-xs text-content-tertiary">
                  {t('einvoice_clearance.raw_response', {
                    defaultValue: "The platform's answer as it came",
                  })}
                </summary>
                <pre className="mt-1 max-h-40 overflow-auto rounded border border-border-light bg-surface-secondary p-2 text-xs">
                  {JSON.stringify(ev.raw_response, null, 2)}
                </pre>
              </details>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ── Withdraw ──────────────────────────────────────────────────────────── */

/**
 * The reason is collected before the confirmation, not inside it.
 *
 * `ConfirmDialog` takes a message, not a form, and the platform requires a
 * reason — every platform that accepts a cancellation records why, and six
 * months later the reason is the only part anybody needs.
 */
function CancelForm({
  platform,
  pending,
  onSubmit,
  onCancel,
}: {
  platform: string;
  pending: boolean;
  onSubmit: (reason: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const ready = reason.trim().length > 0;

  return (
    <form
      className="space-y-2 rounded-lg border border-semantic-error p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit(reason.trim());
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_cancel_reason', {
          defaultValue: 'Why this document is being withdrawn',
        })}
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={1000}
          rows={3}
          className="rounded border border-border-light bg-surface-primary p-2"
          required
        />
      </label>
      <p className="text-xs text-content-tertiary">
        {t('einvoice_clearance.cancel_reason_hint', {
          defaultValue: '{{platform}} files this reason with the cancellation and keeps it.',
          platform,
        })}
      </p>
      <div className="flex gap-2">
        <Button type="submit" size="sm" variant="danger" disabled={!ready || pending}>
          {t('einvoice_clearance.cancel_continue', { defaultValue: 'Continue' })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </form>
  );
}

/* ── Record by hand ────────────────────────────────────────────────────── */

/**
 * What an accountant actually does when a submission is left in doubt: log into
 * the portal, look, and write down what they saw. The note is mandatory because
 * a hand-written status change on a fiscal record has to say where the
 * information came from, and a clearance country refuses an acceptance with no
 * identifier — the invoice is not valid without one.
 */
function ResolveForm({
  identifierLabel,
  identifierRequired,
  pending,
  onSubmit,
  onCancel,
}: {
  identifierLabel: string;
  identifierRequired: boolean;
  pending: boolean;
  onSubmit: (body: ResolveBody) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [outcome, setOutcome] = useState<'cleared' | 'rejected'>('cleared');
  const [identifier, setIdentifier] = useState('');
  const [code, setCode] = useState('');
  const [rejectionMessage, setRejectionMessage] = useState('');
  const [note, setNote] = useState('');

  const needsIdentifier = outcome === 'cleared' && identifierRequired;
  const ready = note.trim().length > 0 && (!needsIdentifier || identifier.trim().length > 0);

  return (
    <form
      className="space-y-2 rounded-lg border border-border-light p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        onSubmit({
          outcome,
          authority_identifier: outcome === 'cleared' ? identifier.trim() : '',
          rejection_code: outcome === 'rejected' ? code.trim() : '',
          rejection_message: outcome === 'rejected' ? rejectionMessage.trim() : '',
          note: note.trim(),
        });
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_outcome', { defaultValue: 'What the platform did' })}
        <select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as 'cleared' | 'rejected')}
          className="rounded border border-border-light bg-surface-primary p-2"
        >
          <option value="cleared">
            {t('einvoice_clearance.outcome_cleared', { defaultValue: 'It accepted the document' })}
          </option>
          <option value="rejected">
            {t('einvoice_clearance.outcome_rejected', { defaultValue: 'It rejected the document' })}
          </option>
        </select>
      </label>

      {outcome === 'cleared' && (
        <label className="flex flex-col gap-1 text-sm">
          {/* Labelled with what that country actually returns, so the operator
              knows which field on the portal to copy. */}
          {identifierLabel ||
            t('einvoice_clearance.field_identifier', { defaultValue: 'Authority identifier' })}
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            maxLength={255}
            className="rounded border border-border-light bg-surface-primary p-2 font-mono"
            required={needsIdentifier}
          />
          {needsIdentifier && (
            <span className="text-xs text-content-tertiary">
              {t('einvoice_clearance.identifier_required', {
                defaultValue: 'A clearance country returns this, and the invoice is not valid without it.',
              })}
            </span>
          )}
        </label>
      )}

      {outcome === 'rejected' && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            {t('einvoice_clearance.field_rejection_code', { defaultValue: 'Rejection code' })}
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              maxLength={64}
              className="rounded border border-border-light bg-surface-primary p-2 font-mono"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {t('einvoice_clearance.field_rejection_message', {
              defaultValue: 'The reason, in the words the platform used',
            })}
            <textarea
              value={rejectionMessage}
              onChange={(e) => setRejectionMessage(e.target.value)}
              maxLength={2000}
              rows={2}
              className="rounded border border-border-light bg-surface-primary p-2"
            />
          </label>
        </>
      )}

      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_note', { defaultValue: 'Where this information came from' })}
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          rows={2}
          className="rounded border border-border-light bg-surface-primary p-2"
          required
        />
      </label>

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || pending}>
          {t('einvoice_clearance.resolve_submit', { defaultValue: 'Record it' })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </form>
  );
}

/* ── Registrations ─────────────────────────────────────────────────────── */

/**
 * Registrations are not project-scoped and sit below the working area for that
 * reason: a company's registration in Mexico is the same registration on every
 * job it runs there.
 */
function ProfilesSection({
  profiles,
  loading,
  meta,
  onChanged,
}: {
  profiles: ClearanceProfile[];
  loading: boolean;
  meta: ClearanceMeta | undefined;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // `null` is closed, `'new'` is the create form, a profile is the edit form.
  // One piece of state rather than two booleans, because the three are
  // mutually exclusive and two booleans can express a fourth state that is not.
  const [editing, setEditing] = useState<'new' | ClearanceProfile | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<ClearanceProfile | null>(null);

  const done = (title: string) => {
    setEditing(null);
    addToast({ type: 'success', title });
    onChanged();
  };
  const failed = (err: unknown) => {
    addToast({
      type: 'error',
      title: t('einvoice_clearance.registration_failed', {
        defaultValue: 'The registration was not saved',
      }),
      message: getErrorMessage(err),
    });
  };

  const create = useMutation({
    mutationFn: (body: ProfileWriteBody) => createProfile(body),
    onSuccess: () =>
      done(t('einvoice_clearance.registration_created', { defaultValue: 'Registration added' })),
    onError: failed,
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: ProfileWriteBody }) => updateProfile(id, body),
    onSuccess: () =>
      done(t('einvoice_clearance.registration_saved', { defaultValue: 'Registration saved' })),
    onError: failed,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteProfile(id),
    onSuccess: () => {
      setConfirmRemove(null);
      addToast({
        type: 'success',
        title: t('einvoice_clearance.registration_removed', {
          defaultValue: 'Registration removed',
        }),
      });
      onChanged();
    },
    onError: (err) => {
      // The server refuses while documents are filed under it, and that refusal
      // is the useful part: it names why. Keep the dialog open with it shown.
      setConfirmRemove(null);
      failed(err);
    },
  });

  return (
    <section aria-label={t('einvoice_clearance.profiles_label', { defaultValue: 'Registrations' })}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Building2 className="h-4 w-4 text-content-secondary" />
          {t('einvoice_clearance.profiles_title', { defaultValue: 'Registrations' })}
        </h3>
        {editing === null && (
          <Button size="sm" onClick={() => setEditing('new')}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t('einvoice_clearance.register_country', { defaultValue: 'Register a country' })}
          </Button>
        )}
      </div>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('einvoice_clearance.profiles_note', {
          defaultValue:
            'How each legal entity is registered with one country platform. A document is filed under exactly one of these, and the registration is the only record of the identity it was sent with.',
        })}
      </p>

      {editing !== null && (
        <div className="mb-3">
          <ClearanceRegistrationForm
            /* Remounts on the target, so switching from one registration to
               another does not leave the previous one's answers in the boxes. */
            key={editing === 'new' ? 'new' : editing.id}
            meta={meta}
            initial={editing === 'new' ? null : editing}
            pending={create.isPending || update.isPending}
            onCancel={() => setEditing(null)}
            onSubmit={(body) => {
              if (editing === 'new') create.mutate(body);
              else update.mutate({ id: editing.id, body });
            }}
          />
        </div>
      )}

      {loading ? (
        <p className="text-sm text-content-secondary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : profiles.length === 0 ? (
        // The empty state used to describe the blockage and offer no way past
        // it, which is why the page read as a dead end. The way past it is the
        // button, so the button belongs here.
        <EmptyState
          icon={<Building2 className="h-8 w-8" />}
          title={t('einvoice_clearance.profiles_empty_title', { defaultValue: 'No registrations yet' })}
          description={t('einvoice_clearance.profiles_empty_body', {
            defaultValue:
              'Nothing can be prepared for a country platform until the entity that issues the invoice is registered with it.',
          })}
          action={
            editing === null ? (
              <Button size="sm" onClick={() => setEditing('new')}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t('einvoice_clearance.register_country', { defaultValue: 'Register a country' })}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="divide-y divide-border-light rounded-lg border border-border-light">
          {profiles.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-2 p-3 text-sm">
              <span className="font-medium">{p.company_key}</span>
              <Badge variant="neutral" size="sm">
                {p.country}
              </Badge>
              <Badge variant={p.regime === 'clearance' ? 'blue' : 'neutral'} size="sm">
                {t(`einvoice_clearance.regime.${p.regime}`, { defaultValue: p.regime })}
              </Badge>
              <span className="text-content-secondary">{p.platform}</span>
              {p.sandbox && (
                <Badge variant="warning" size="sm">
                  {t('einvoice_clearance.sandbox', { defaultValue: 'Sandbox' })}
                </Badge>
              )}
              {!p.is_active && (
                <Badge variant="neutral" size="sm">
                  {t('einvoice_clearance.inactive', { defaultValue: 'Inactive' })}
                </Badge>
              )}
              {/* An empty adapter is not cosmetic: a submission under this
                  registration is refused rather than routed somewhere. */}
              {p.adapter_key ? (
                <span className="font-mono text-xs text-content-tertiary">{p.adapter_key}</span>
              ) : (
                <Badge variant="error" size="sm">
                  {t('einvoice_clearance.no_adapter', { defaultValue: 'No adapter' })}
                </Badge>
              )}

              <span className="ml-auto flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditing(p)}
                  aria-label={t('einvoice_clearance.registration_edit', {
                    defaultValue: 'Edit registration',
                  })}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmRemove(p)}
                  aria-label={t('einvoice_clearance.registration_remove', {
                    defaultValue: 'Remove registration',
                  })}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={confirmRemove !== null}
        variant="danger"
        loading={remove.isPending}
        title={t('einvoice_clearance.registration_remove_title', {
          defaultValue: 'Remove this registration?',
        })}
        /* Says what is lost rather than asking whether they are sure. The
           registration is the only record of the identity its documents were
           sent under, and that is what an authority asks about. */
        message={t('einvoice_clearance.registration_remove_body', {
          defaultValue:
            '{{company}} in {{country}} on {{platform}}. This is refused while documents are filed under it. To retire one that has history, clear Active instead and it stops being offered without losing what it recorded.',
          company: confirmRemove?.company_key ?? '',
          country: confirmRemove?.country ?? '',
          platform: confirmRemove?.platform ?? '',
        })}
        confirmLabel={t('einvoice_clearance.registration_remove_confirm', {
          defaultValue: 'Remove',
        })}
        onCancel={() => setConfirmRemove(null)}
        onConfirm={() => {
          if (confirmRemove) remove.mutate(confirmRemove.id);
        }}
      />
    </section>
  );
}
