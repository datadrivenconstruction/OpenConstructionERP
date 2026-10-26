// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** One guarantee: lifecycle actions, advance recovery, documents, commission and the event timeline. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, FileText, Trash2, Unlink } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, WideModal, WideModalField } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import { fetchDocuments } from '@/features/documents/api';
import {
  ALLOWED_TRANSITIONS,
  advanceRecovery,
  deleteGuarantee,
  isDeletable,
  linkDocument,
  postCommission,
  transitionGuarantee,
  transitionNeeds,
  unlinkDocument,
  useGuarantee,
  useGuaranteeMutation,
  type GuaranteeDetail,
  type GuaranteeEvent,
  type GuaranteeStatus,
} from './api';
import { actionLabel, directionLabel, eventLabel, sourceLabel, statusLabel, statusVariant, typeLabel } from './labels';
import { AlertBadge, Money, ValidationBlock, inputCls, selectCls, textareaCls } from './ui';

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm text-content-primary">{children}</dd>
    </div>
  );
}

function Timeline({ events, currency }: { events: GuaranteeEvent[]; currency: string }) {
  const { t } = useTranslation();
  const ordered = [...events].sort((a, b) => b.created_at.localeCompare(a.created_at));
  if (ordered.length === 0) {
    return <p className="text-sm text-content-tertiary">{t('guarantees.timeline_empty', { defaultValue: 'No events yet' })}</p>;
  }
  return (
    <ol className="relative ml-2 border-l border-border-light" data-testid="guarantees-timeline">
      {ordered.map((e) => {
        const amountChanged = e.amount_before !== null && e.amount_after !== null && e.amount_before !== e.amount_after;
        return (
          <li key={e.id} className="relative pb-5 pl-5 last:pb-0">
            <span className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full bg-oe-blue" />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-content-primary">{eventLabel(t, e.action)}</span>
              {e.source && <Badge variant="neutral" size="sm">{sourceLabel(t, e.source)}</Badge>}
              <span className="text-2xs text-content-tertiary"><DateDisplay value={e.created_at} format="datetime" /></span>
            </div>
            {e.to_status && (
              <div className="mt-0.5 text-xs text-content-secondary">
                {e.from_status ? `${statusLabel(t, e.from_status)} → ${statusLabel(t, e.to_status)}` : statusLabel(t, e.to_status)}
              </div>
            )}
            {amountChanged && (
              <div className="mt-0.5 text-xs text-content-secondary">
                <Money value={e.amount_before} currency={currency} /> → <Money value={e.amount_after} currency={currency} />
              </div>
            )}
            {e.note && <div className="mt-0.5 text-xs italic text-content-tertiary">{e.note}</div>}
          </li>
        );
      })}
    </ol>
  );
}

export function GuaranteeDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId, guaranteeId = '' } = useParams<{ projectId: string; guaranteeId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const q = useGuarantee(projectId, guaranteeId);
  const g: GuaranteeDetail | undefined = q.data;

  const [transitionTo, setTransitionTo] = useState<GuaranteeStatus | null>(null);
  const [newExpiry, setNewExpiry] = useState('');
  const [newAmount, setNewAmount] = useState('');
  const [note, setNote] = useState('');
  const [recovered, setRecovered] = useState('');
  const [recoveryNote, setRecoveryNote] = useState('');
  const [periodEnd, setPeriodEnd] = useState(todayLocalISO());
  const [docId, setDocId] = useState('');
  const [docKind, setDocKind] = useState('');
  const [docTitle, setDocTitle] = useState('');

  const docsQ = useQuery({
    queryKey: ['guarantees', 'doc-picker', projectId],
    queryFn: () => fetchDocuments(projectId, { limit: 100 }),
    enabled: !!projectId,
  });

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('guarantees.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const transitionMut = useGuaranteeMutation(
    (vars: { status: GuaranteeStatus; new_expiry_date?: string; new_amount?: string; note?: string }) =>
      transitionGuarantee(projectId, guaranteeId, vars),
  );
  const recoveryMut = useGuaranteeMutation((vars: { recovered_amount: string; note?: string }) =>
    advanceRecovery(projectId, guaranteeId, vars),
  );
  const commissionMut = useGuaranteeMutation((end: string) => postCommission(projectId, guaranteeId, end));
  const linkMut = useGuaranteeMutation((vars: { document_id: string; kind: string; title: string }) =>
    linkDocument(projectId, guaranteeId, vars),
  );
  const unlinkMut = useGuaranteeMutation((documentId: string) => unlinkDocument(projectId, guaranteeId, documentId));
  const deleteMut = useGuaranteeMutation(() => deleteGuarantee(projectId, guaranteeId));

  const need = transitionTo ? transitionNeeds(transitionTo) : null;
  const transitionReady = need === 'expiry' ? newExpiry !== '' : need === 'amount' ? /^\d+(\.\d+)?$/.test(newAmount.trim()) : true;

  const closeTransition = () => {
    setTransitionTo(null);
    setNewExpiry('');
    setNewAmount('');
    setNote('');
  };

  const submitTransition = () => {
    if (!transitionTo || !transitionReady) return;
    transitionMut.mutate(
      {
        status: transitionTo,
        ...(need === 'expiry' ? { new_expiry_date: newExpiry } : {}),
        ...(need === 'amount' ? { new_amount: newAmount.trim() } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      },
      {
        onSuccess: () => {
          closeTransition();
          addToast({ type: 'success', title: t('guarantees.transition_done', { defaultValue: 'Guarantee updated' }) });
        },
        onError,
      },
    );
  };

  const submitRecovery = () => {
    if (!/^\d+(\.\d+)?$/.test(recovered.trim())) return;
    recoveryMut.mutate(
      { recovered_amount: recovered.trim(), ...(recoveryNote.trim() ? { note: recoveryNote.trim() } : {}) },
      {
        onSuccess: () => {
          setRecovered('');
          setRecoveryNote('');
          addToast({ type: 'success', title: t('guarantees.recovery_done', { defaultValue: 'Advance recovery recorded' }) });
        },
        onError,
      },
    );
  };

  const submitCommission = () => {
    commissionMut.mutate(periodEnd, {
      onSuccess: (r) =>
        addToast({
          type: r.posted ? 'success' : 'info',
          title: r.posted
            ? t('guarantees.commission_posted', { defaultValue: 'Commission posted for {{days}} days', days: r.days })
            : t('guarantees.commission_none', { defaultValue: 'Nothing to post for this period' }),
        }),
      onError,
    });
  };

  const submitLink = () => {
    if (!docId) return;
    const picked = docsQ.data?.items.find((d) => d.id === docId);
    linkMut.mutate(
      { document_id: docId, kind: docKind.trim() || 'original', title: docTitle.trim() || picked?.name || docId },
      {
        onSuccess: () => {
          setDocId('');
          setDocKind('');
          setDocTitle('');
        },
        onError,
      },
    );
  };

  const handleDelete = async () => {
    const ok = await confirm({
      title: t('guarantees.confirm_delete_title', { defaultValue: 'Delete guarantee?' }),
      message: t('guarantees.confirm_delete_msg', { defaultValue: 'This guarantee and its history will be permanently deleted.' }),
      confirmLabel: t('guarantees.confirm_delete_label', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (!ok) return;
    deleteMut.mutate(undefined as never, {
      onSuccess: () => navigate(`/projects/${projectId}/guarantees`),
      onError,
    });
  };

  const backTo = `/projects/${projectId}/guarantees`;

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={g ? g.reference : t('guarantees.title', { defaultValue: 'Guarantees & Bonds' })}
        subtitle={g ? typeLabel(t, g.guarantee_type) : undefined}
        actions={
          <Link to={backTo}>
            <Button variant="secondary" size="sm" icon={<ArrowLeft size={14} />}>
              {t('guarantees.back', { defaultValue: 'Register' })}
            </Button>
          </Link>
        }
      />

      <RequiresProject emptyHint={t('guarantees.select_project', { defaultValue: 'Open a project first to manage its guarantees and bonds.' })}>
        {q.isLoading ? (
          <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('guarantees.loading', { defaultValue: 'Loading...' })}</Card>
        ) : !g ? (
          <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('guarantees.not_found', { defaultValue: 'Guarantee not found' })}</Card>
        ) : (
          <div className="space-y-5">
            <Card padding="md">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant={statusVariant(g.status)}>{statusLabel(t, g.status)}</Badge>
                <AlertBadge band={g.alert_band} days={g.days_to_expiry} />
                <div className="ml-auto flex flex-wrap gap-2">
                  {ALLOWED_TRANSITIONS[g.status].map((to) => (
                    <Button key={to} variant={to === 'called' ? 'danger' : 'secondary'} size="sm" onClick={() => setTransitionTo(to)}>
                      {actionLabel(t, to)}
                    </Button>
                  ))}
                  {isDeletable(g.status) && (
                    <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={handleDelete}>
                      {t('guarantees.delete', { defaultValue: 'Delete' })}
                    </Button>
                  )}
                </div>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
                <Fact label={t('guarantees.field_amount', { defaultValue: 'Amount' })}><Money value={g.amount} currency={g.currency} /></Fact>
                <Fact label={t('guarantees.original_amount', { defaultValue: 'Original amount' })}><Money value={g.original_amount} currency={g.currency} /></Fact>
                <Fact label={t('guarantees.field_expiry_date', { defaultValue: 'Expiry date' })}><DateDisplay value={g.expiry_date} /></Fact>
                <Fact label={t('guarantees.field_issue_date', { defaultValue: 'Issue date' })}><DateDisplay value={g.issue_date} /></Fact>
                <Fact label={t('guarantees.field_direction', { defaultValue: 'Direction' })}>{directionLabel(t, g.direction)}</Fact>
                <Fact label={t('guarantees.field_issuer_bank', { defaultValue: 'Issuing bank' })}>{g.issuer_bank || '—'}</Fact>
                <Fact label={t('guarantees.field_bank_reference', { defaultValue: 'Bank reference' })}>{g.bank_reference || '—'}</Fact>
                <Fact label={t('guarantees.field_beneficiary', { defaultValue: 'Beneficiary' })}>{g.beneficiary || '—'}</Fact>
                <Fact label={t('guarantees.field_applicant', { defaultValue: 'Applicant' })}>{g.applicant || '—'}</Fact>
                <Fact label={t('guarantees.field_percent', { defaultValue: '% of contract' })}>{g.percent_of_contract ?? '—'}</Fact>
                <Fact label={t('guarantees.field_claim_period', { defaultValue: 'Claim period (days)' })}>{g.claim_period_days ?? '—'}</Fact>
                <Fact label={t('guarantees.field_defects_period', { defaultValue: 'Defects period (months)' })}>{g.defects_period_months ?? '—'}</Fact>
              </dl>
              {g.notes && <p className="mt-4 text-sm text-content-secondary">{g.notes}</p>}
            </Card>

            <ValidationBlock findings={g.findings} />

            {g.guarantee_type === 'advance_payment' && (
              <Card padding="md" data-testid="guarantees-advance">
                <h3 className="text-sm font-semibold text-content-primary">{t('guarantees.advance_title', { defaultValue: 'Advance recovery' })}</h3>
                <dl className="mt-3 grid grid-cols-3 gap-4">
                  <Fact label={t('guarantees.advance_original', { defaultValue: 'Advance paid' })}><Money value={g.advance_amount} currency={g.currency} /></Fact>
                  <Fact label={t('guarantees.advance_recovered', { defaultValue: 'Recovered so far' })}><Money value={g.advance_recovered} currency={g.currency} /></Fact>
                  <Fact label={t('guarantees.advance_outstanding', { defaultValue: 'Outstanding' })}><Money value={g.outstanding_advance} currency={g.currency} /></Fact>
                </dl>
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] sm:items-end">
                  <WideModalField label={t('guarantees.recovery_amount', { defaultValue: 'Recovered amount' })}>
                    <input className={inputCls} inputMode="decimal" value={recovered} onChange={(e) => setRecovered(e.target.value)} />
                  </WideModalField>
                  <WideModalField label={t('guarantees.note', { defaultValue: 'Note' })}>
                    <input className={inputCls} value={recoveryNote} onChange={(e) => setRecoveryNote(e.target.value)} />
                  </WideModalField>
                  <Button variant="primary" onClick={submitRecovery} loading={recoveryMut.isPending} disabled={!/^\d+(\.\d+)?$/.test(recovered.trim())}>
                    {t('guarantees.record_recovery', { defaultValue: 'Record recovery' })}
                  </Button>
                </div>
              </Card>
            )}

            <Card padding="md">
              <h3 className="text-sm font-semibold text-content-primary">{t('guarantees.documents_title', { defaultValue: 'Documents' })}</h3>
              {g.documents.length === 0 ? (
                <p className="mt-2 text-sm text-content-tertiary">{t('guarantees.documents_empty', { defaultValue: 'No documents linked' })}</p>
              ) : (
                <ul className="mt-2 divide-y divide-border-light">
                  {g.documents.map((d) => (
                    <li key={d.id} className="flex items-center gap-3 py-2 text-sm">
                      <FileText size={14} className="text-content-tertiary" />
                      <span className="font-medium text-content-primary">{d.title}</span>
                      <Badge variant="neutral" size="sm">{d.kind}</Badge>
                      <Button className="ml-auto" variant="ghost" size="sm" icon={<Unlink size={14} />} onClick={() => unlinkMut.mutate(d.document_id, { onError })}>
                        {t('guarantees.unlink', { defaultValue: 'Unlink' })}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4 sm:items-end">
                <WideModalField label={t('guarantees.document', { defaultValue: 'Document' })}>
                  <select className={selectCls} value={docId} onChange={(e) => setDocId(e.target.value)}>
                    <option value="">{t('guarantees.document_pick', { defaultValue: 'Choose a document' })}</option>
                    {(docsQ.data?.items ?? []).map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </WideModalField>
                <WideModalField label={t('guarantees.document_kind', { defaultValue: 'Kind' })}>
                  <input className={inputCls} value={docKind} onChange={(e) => setDocKind(e.target.value)} placeholder={t('guarantees.document_kind_ph', { defaultValue: 'e.g. original' })} />
                </WideModalField>
                <WideModalField label={t('guarantees.document_title', { defaultValue: 'Title' })}>
                  <input className={inputCls} value={docTitle} onChange={(e) => setDocTitle(e.target.value)} />
                </WideModalField>
                <Button variant="secondary" onClick={submitLink} loading={linkMut.isPending} disabled={!docId}>
                  {t('guarantees.link_document', { defaultValue: 'Link document' })}
                </Button>
              </div>
            </Card>

            {g.commission_rate_pct && (
              <Card padding="md">
                <h3 className="text-sm font-semibold text-content-primary">{t('guarantees.commission_title', { defaultValue: 'Bank commission' })}</h3>
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('guarantees.commission_hint', { defaultValue: 'Posts the commission accrued up to the period end as a finance cost.' })}
                </p>
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <WideModalField label={t('guarantees.period_end', { defaultValue: 'Period end' })}>
                    <input type="date" className={inputCls} value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
                  </WideModalField>
                  <Button variant="secondary" onClick={submitCommission} loading={commissionMut.isPending} disabled={!periodEnd}>
                    {t('guarantees.post_commission', { defaultValue: 'Post commission' })}
                  </Button>
                </div>
              </Card>
            )}

            <Card padding="md">
              <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('guarantees.timeline_title', { defaultValue: 'Timeline' })}</h3>
              <Timeline events={g.events} currency={g.currency} />
            </Card>
          </div>
        )}
      </RequiresProject>

      <WideModal
        open={transitionTo !== null}
        onClose={closeTransition}
        busy={transitionMut.isPending}
        size="sm"
        title={transitionTo ? actionLabel(t, transitionTo) : ''}
        footer={
          <>
            <Button variant="ghost" onClick={closeTransition} disabled={transitionMut.isPending}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
            <Button variant="primary" onClick={submitTransition} loading={transitionMut.isPending} disabled={!transitionReady}>
              {t('guarantees.confirm', { defaultValue: 'Confirm' })}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {need === 'expiry' && (
            <WideModalField label={t('guarantees.new_expiry', { defaultValue: 'New expiry date' })} required>
              <input type="date" className={inputCls} value={newExpiry} onChange={(e) => setNewExpiry(e.target.value)} autoFocus />
            </WideModalField>
          )}
          {need === 'amount' && (
            <WideModalField label={t('guarantees.new_amount', { defaultValue: 'New amount' })} required>
              <input className={inputCls} inputMode="decimal" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} autoFocus />
            </WideModalField>
          )}
          <WideModalField label={t('guarantees.note', { defaultValue: 'Note' })}>
            <textarea className={textareaCls} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </WideModalField>
        </div>
      </WideModal>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
