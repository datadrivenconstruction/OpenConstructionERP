// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The issued requirements specification: the current version and its date, a
// badge when the requirements changed since the last issue, the button that
// issues a new version, and the list of the versions with their documents.
// An issue is a PDF in the documents module; a draft brief cannot be issued.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { FileText } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import { issueSpecification, type BriefStatus, type SpecificationState } from './api';
import { FIELD_CLASS, FormError, useSubmit } from './BriefBits';
import { documentLink } from './StudiesTab';

function IssueDialog({
  open,
  projectId,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const sub = useSubmit(() => {
    setNote('');
    onDone();
    onClose();
  });
  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="md"
      testId="brief-spec-dialog"
      title={t('engineeringBrief.spec.issue', { defaultValue: 'Issue specification' })}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={() => void sub.run(() => issueSpecification(projectId, note.trim()))} data-testid="brief-spec-confirm">
            {t('engineeringBrief.spec.issue', { defaultValue: 'Issue specification' })}
          </Button>
        </div>
      }
    >
      <WideModalField
        label={t('engineeringBrief.spec.note', { defaultValue: 'Note' })}
        hint={t('engineeringBrief.spec.note_hint', { defaultValue: 'What changed since the last version. The requirements are rendered as a PDF into the documents module.' })}
      >
        <textarea className={FIELD_CLASS} rows={3} value={note} maxLength={5000} onChange={(e) => setNote(e.target.value)} data-testid="brief-spec-note" />
      </WideModalField>
    </WideModal>
  );
}

export function SpecificationPanel({
  projectId,
  status,
  spec,
  canWrite,
  onChanged,
}: {
  projectId: string;
  status: BriefStatus;
  spec: SpecificationState;
  /** False when the caller lacks the edit permission: no issue button. */
  canWrite: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [issuing, setIssuing] = useState(false);
  const latest = spec.items.reduce<SpecificationState['items'][number] | null>(
    (best, i) => (best === null || i.version_no > best.version_no ? i : best),
    null,
  );
  const versions = [...spec.items].sort((a, b) => b.version_no - a.version_no);
  const draft = status === 'draft';
  const reason = draft
    ? t('engineering_brief.errors.brief_not_submitted', { defaultValue: 'Only a submitted brief can be issued.' })
    : spec.current
      ? t('engineering_brief.errors.specification_unchanged', { defaultValue: 'The requirements have not changed since the last issue.' })
      : spec.requirement_count === 0
        ? t('engineering_brief.errors.no_requirements', { defaultValue: 'The brief has no requirements.' })
        : '';

  return (
    <section className="space-y-3 rounded-lg border border-border-light p-4" data-testid="brief-spec">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FileText size={14} aria-hidden />
            {t('engineeringBrief.spec.title', { defaultValue: 'Requirements specification' })}
          </h3>
          <p className="flex flex-wrap items-center gap-2 text-sm text-content-secondary" data-testid="brief-spec-current">
            {latest
              ? t('engineeringBrief.spec.current', {
                  defaultValue: 'Version {{version}}, issued on {{date}}',
                  version: latest.version_no,
                  date: fmtDate(latest.issued_at),
                })
              : t('engineeringBrief.spec.none', { defaultValue: 'Not issued yet' })}
            {spec.stale ? (
              <span data-testid="brief-spec-stale">
                <Badge variant="warning" size="sm">
                  {t('engineeringBrief.spec.stale', { defaultValue: 'Requirements changed since issue' })}
                </Badge>
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {canWrite ? (
            <Button size="sm" disabled={reason !== ''} onClick={() => setIssuing(true)} title={reason || undefined} data-testid="brief-spec-issue">
              {t('engineeringBrief.spec.issue', { defaultValue: 'Issue specification' })}
            </Button>
          ) : null}
          {reason ? (
            <p className="text-xs text-content-tertiary" data-testid="brief-spec-reason">
              {reason}
            </p>
          ) : null}
        </div>
      </div>

      {versions.length > 0 ? (
        <ul className="divide-y divide-border-light text-sm" data-testid="brief-spec-versions">
          {versions.map((v) => (
            <li key={v.id} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5" data-testid="brief-spec-version">
              <span className="text-content-primary">
                {t('engineeringBrief.spec.version', { defaultValue: 'Version {{version}}', version: v.version_no })}
                <span className="ml-2 text-xs text-content-secondary">{fmtDate(v.issued_at)}</span>
                {v.note ? <span className="ml-2 text-xs text-content-tertiary">{v.note}</span> : null}
              </span>
              {v.document_id ? (
                <Link to={documentLink(v.document_id)} className="text-xs text-oe-blue hover:underline" data-testid="brief-spec-document-link">
                  {t('engineeringBrief.spec.open_document', { defaultValue: 'Open document' })}
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <IssueDialog open={issuing} projectId={projectId} onClose={() => setIssuing(false)} onDone={onChanged} />
    </section>
  );
}
