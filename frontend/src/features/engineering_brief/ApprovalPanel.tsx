// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The head of the brief: title, status, the date of the operating proof, the
// catalogue, and the approval workflow with what blocks submission. Which
// buttons exist follows the capability flags the server sent with the brief.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, Pencil, Send, Undo2, XCircle } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import {
  approveBrief,
  patchBrief,
  returnBrief,
  setBrief,
  submitBrief,
  type Brief,
  type CatalogueSummary,
  type Can,
  type Finding,
} from './api';
import { FIELD_CLASS, FormError, useBriefAction, useSubmit } from './BriefBits';
import { BRIEF_STATUS, BRIEF_TONE, findingText, itemLabel, keyText, type LabelContext, type TFn } from './labels';
import { useBriefCatalogues } from './hooks';

function ActionButton({
  can,
  label,
  icon,
  variant,
  busy,
  onClick,
  testId,
}: {
  can: Can;
  label: string;
  icon: React.ReactNode;
  variant: 'primary' | 'secondary';
  busy: boolean;
  onClick: () => void;
  testId: string;
}) {
  const { t } = useTranslation();
  // An action that does not fit the state at all is left off; one that is only refused for this caller shows why.
  if (can.applies === false) return null;
  return (
    <Button
      variant={variant}
      size="sm"
      icon={icon}
      loading={busy}
      disabled={!can.allowed}
      title={!can.allowed && can.reason ? t(`engineering_brief.errors.${can.reason}`, { defaultValue: can.reason.replace(/_/g, ' ') }) : undefined}
      onClick={onClick}
      data-testid={testId}
    >
      {label}
    </Button>
  );
}

function FindingList({ findings, tone }: { findings: Finding[]; tone: 'error' | 'warning' }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  return (
    <ul className="space-y-1" data-testid={`brief-findings-${tone}`}>
      {findings.map((f, i) => (
        <li key={`${f.code}:${f.ref}:${i}`} className="flex items-start gap-2 text-sm">
          {tone === 'error' ? (
            <XCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
          ) : (
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          )}
          <span className="text-content-primary">
            {findingText(t as TFn, f.code, f.detail)}
            {f.ref ? <span className="ml-1.5 font-mono text-xs text-content-tertiary">{f.ref}</span> : null}
            {f.detail ? <span className="ml-1.5 text-xs text-content-secondary">{f.detail}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ApprovalPanel({
  projectId,
  brief,
  findings,
  catalogueName,
  onChanged,
}: {
  projectId: string;
  brief: Brief;
  findings: Finding[];
  catalogueName: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const submit = useBriefAction(() => submitBrief(projectId), onChanged);
  const back = useBriefAction(() => returnBrief(projectId), onChanged);
  const approve = useBriefAction(() => approveBrief(projectId), onChanged);
  const blocking = findings.filter((f) => f.severity === 'error');
  const warnings = findings.filter((f) => f.severity === 'warning');
  const title = brief.title.trim() || t('engineeringBrief.untitled', { defaultValue: 'Engineering brief' });

  return (
    <section className="space-y-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="brief-approval">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-content-primary">{title}</h2>
            <span data-testid="brief-status">
              <Badge variant={BRIEF_TONE[brief.status]} size="sm">
                {keyText(t as TFn, BRIEF_STATUS[brief.status])}
              </Badge>
            </span>
          </div>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-content-secondary">
            <div className="flex gap-1.5">
              <dt>{t('engineeringBrief.proof_date', { defaultValue: 'Operation proof' })}:</dt>
              <dd className="text-content-primary" data-testid="brief-proof-date">
                {brief.operation_proof_date ? fmtDate(brief.operation_proof_date) : t('engineeringBrief.not_set', { defaultValue: 'Not set' })}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>{t('engineeringBrief.catalogue', { defaultValue: 'Catalogue' })}:</dt>
              <dd className="text-content-primary">{catalogueName}</dd>
            </div>
            {brief.approved_at ? (
              <div className="flex gap-1.5">
                <dt>{t('engineeringBrief.approved_on', { defaultValue: 'Approved on' })}:</dt>
                <dd className="text-content-primary">{fmtDate(brief.approved_at)}</dd>
              </div>
            ) : null}
          </dl>
          {brief.summary ? <p className="max-w-3xl text-sm text-content-secondary">{brief.summary}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {brief.can.edit.allowed ? (
            <Button variant="ghost" size="sm" icon={<Pencil size={14} />} onClick={() => setEditing(true)} data-testid="brief-edit-details">
              {t('engineeringBrief.edit_details', { defaultValue: 'Edit details' })}
            </Button>
          ) : null}
          <ActionButton
            can={brief.can.submit}
            label={t('engineeringBrief.submit', { defaultValue: 'Submit for review' })}
            icon={<Send size={14} />}
            variant="primary"
            busy={submit.isPending}
            onClick={() => submit.mutate()}
            testId="brief-submit"
          />
          <ActionButton
            can={brief.can.return}
            label={t('engineeringBrief.return', { defaultValue: 'Return to draft' })}
            icon={<Undo2 size={14} />}
            variant="secondary"
            busy={back.isPending}
            onClick={() => back.mutate()}
            testId="brief-return"
          />
          <ActionButton
            can={brief.can.approve}
            label={t('engineeringBrief.approve', { defaultValue: 'Approve' })}
            icon={<CheckCircle2 size={14} />}
            variant="primary"
            busy={approve.isPending}
            onClick={() => approve.mutate()}
            testId="brief-approve"
          />
        </div>
      </div>

      {brief.requirements_changed ? (
        <p className="flex items-center gap-2 text-sm text-semantic-warning" data-testid="brief-requirements-changed">
          <AlertTriangle size={14} aria-hidden />
          {t('engineeringBrief.requirements_changed', {
            defaultValue: 'Requirements were changed in the requirements register after the brief was bound.',
          })}
        </p>
      ) : null}
      {brief.status === 'in_review' && brief.gates_in_use ? (
        <p className="text-sm text-content-secondary" data-testid="brief-gate-hint">
          {t('engineeringBrief.gate_hint', { defaultValue: 'This project uses gates: the brief is approved by the gate decision.' })}
        </p>
      ) : null}

      <div className="space-y-2" data-testid="brief-findings">
        <h3 className="text-sm font-medium text-content-primary">
          {t('engineeringBrief.findings.title', { defaultValue: 'Before submission' })}
        </h3>
        {blocking.length === 0 && warnings.length === 0 ? (
          <p className="text-sm text-content-secondary" data-testid="brief-findings-clear">
            {t('engineeringBrief.findings.clear', { defaultValue: 'Nothing blocks submission.' })}
          </p>
        ) : (
          <>
            {blocking.length > 0 ? (
              <p className="text-xs font-medium uppercase tracking-wide text-semantic-error">
                {t('engineeringBrief.findings.blocking', { defaultValue: 'Blocking ({{count}})', count: blocking.length })}
              </p>
            ) : null}
            <FindingList findings={blocking} tone="error" />
            {warnings.length > 0 ? (
              <p className="text-xs font-medium uppercase tracking-wide text-semantic-warning">
                {t('engineeringBrief.findings.warnings', { defaultValue: 'Warnings ({{count}})', count: warnings.length })}
              </p>
            ) : null}
            <FindingList findings={warnings} tone="warning" />
          </>
        )}
      </div>

      <DetailsDialog open={editing} projectId={projectId} brief={brief} onClose={() => setEditing(false)} onDone={onChanged} />
    </section>
  );
}

function DetailsDialog({
  open,
  projectId,
  brief,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  brief: Brief;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(brief.title);
  const [summary, setSummary] = useState(brief.summary);
  const [proof, setProof] = useState(brief.operation_proof_date ?? '');
  const form = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setTitle(brief.title);
      setSummary(brief.summary);
      setProof(brief.operation_proof_date ?? '');
      form.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={form.busy}
      size="md"
      testId="brief-details-dialog"
      title={t('engineeringBrief.edit_details', { defaultValue: 'Edit details' })}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={form.error} />
          <Button variant="ghost" onClick={onClose} disabled={form.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            loading={form.busy}
            data-testid="brief-details-save"
            onClick={() =>
              form.run(() =>
                patchBrief(projectId, { title, summary, operation_proof_date: proof || null }),
              )
            }
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <WideModalField label={t('engineeringBrief.field.title', { defaultValue: 'Title' })}>
          <input className={FIELD_CLASS} value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.proof_date', { defaultValue: 'Operation proof' })}>
          <input className={FIELD_CLASS} type="date" value={proof} onChange={(e) => setProof(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.field.summary', { defaultValue: 'Summary' })}>
          <textarea className={FIELD_CLASS} rows={4} value={summary} maxLength={20000} onChange={(e) => setSummary(e.target.value)} />
        </WideModalField>
      </div>
    </WideModal>
  );
}

/** Starting the brief: pick the catalogue that brings the categories, topics and milestone chain. */
export function BriefSetup({ projectId, labels, onDone }: { projectId: string; labels: LabelContext; onDone: () => void }) {
  const { t } = useTranslation();
  const cataloguesQ = useBriefCatalogues();
  const [pick, setPick] = useState('');
  const [title, setTitle] = useState('');
  const form = useSubmit(onDone);
  const catalogues: CatalogueSummary[] = cataloguesQ.data ?? [];
  const chosen = catalogues.find((c) => `${c.source}:${c.id}` === pick) ?? catalogues[0];

  return (
    <section className="space-y-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="brief-setup">
      <WideModalField label={t('engineeringBrief.catalogue', { defaultValue: 'Catalogue' })}>
        <select
          className={FIELD_CLASS}
          value={chosen ? `${chosen.source}:${chosen.id}` : ''}
          onChange={(e) => setPick(e.target.value)}
          disabled={cataloguesQ.isLoading}
          data-testid="brief-setup-catalogue"
        >
          {catalogues.map((c) => (
            <option key={`${c.source}:${c.id}`} value={`${c.source}:${c.id}`}>
              {itemLabel(labels, { code: c.code, name_key: c.name.key ?? '', labels: c.name.text }, c.code)}
            </option>
          ))}
        </select>
      </WideModalField>
      <WideModalField label={t('engineeringBrief.field.title', { defaultValue: 'Title' })}>
        <input className={FIELD_CLASS} value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} />
      </WideModalField>
      <div className="flex items-center justify-end gap-2">
        <FormError message={form.error} />
        <Button
          loading={form.busy}
          disabled={!chosen}
          data-testid="brief-setup-create"
          onClick={() =>
            chosen &&
            form.run(() =>
              setBrief(projectId, {
                catalogue_source: chosen.source,
                catalogue_id: chosen.id,
                catalogue_version: chosen.latest_version ?? undefined,
                title,
                summary: '',
                operation_proof_date: null,
              }),
            )
          }
        >
          {t('engineeringBrief.create', { defaultValue: 'Create engineering brief' })}
        </Button>
      </div>
    </section>
  );
}
