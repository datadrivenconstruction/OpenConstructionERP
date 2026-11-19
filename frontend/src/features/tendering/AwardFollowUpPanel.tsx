// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * After the award: tell every unsuccessful bidder in one action, then file
 * the contract, award record and letters in the project's documents.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FolderInput, Send } from 'lucide-react';

import { Badge, Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { fileAwardDocuments, getRejections, sendRejections, type FiledDocument, type RejectionState } from './api';
import { rejectionsToSend } from './awardFlow';

interface Props {
  packageId: string;
}

const STATE_VARIANT: Record<RejectionState, 'success' | 'warning' | 'error' | 'neutral'> = {
  sent: 'success',
  pending: 'neutral',
  failed: 'error',
  no_email: 'warning',
};

export function AwardFollowUpPanel({ packageId }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [preview, setPreview] = useState(false);
  const [filed, setFiled] = useState<FiledDocument[] | null>(null);
  const key = ['tendering', 'rejections', packageId];
  const q = useQuery({ queryKey: key, queryFn: () => getRejections(packageId) });
  const n = rejectionsToSend(q.data);

  const sendM = useMutation({
    mutationFn: () => sendRejections(packageId),
    onSuccess: (res) => {
      qc.setQueryData(key, res);
      setPreview(false);
      addToast({
        type: res.failed ? 'warning' : 'success',
        title: t('tendering.rejections.sent_toast', {
          defaultValue: 'Rejection letters sent: {{sent}}, failed: {{failed}}',
          sent: res.sent,
          failed: res.failed,
        }),
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const fileM = useMutation({
    mutationFn: () => fileAwardDocuments(packageId),
    onSuccess: (res) => setFiled(res.documents),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (!q.data?.awarded) return null;
  const stateLabel: Record<RejectionState, string> = {
    sent: t('tendering.rejections.state_sent', { defaultValue: 'Sent' }),
    pending: t('tendering.rejections.state_pending', { defaultValue: 'Not sent yet' }),
    failed: t('tendering.rejections.state_failed', { defaultValue: 'Failed' }),
    no_email: t('tendering.rejections.state_no_email', { defaultValue: 'No email address' }),
  };
  const kindLabel: Record<FiledDocument['kind'], string> = {
    contract: t('tendering.filing.kind_contract', { defaultValue: 'Contract' }),
    award_record: t('tendering.filing.kind_award_record', { defaultValue: 'Award record' }),
    award_letter: t('tendering.filing.kind_award_letter', { defaultValue: 'Award letter' }),
    rejection_letter: t('tendering.filing.kind_rejection_letter', { defaultValue: 'Rejection letter' }),
  };
  const filedLabel: Record<FiledDocument['state'], string> = {
    filed: t('tendering.filing.state_filed', { defaultValue: 'Filed' }),
    already_filed: t('tendering.filing.state_already_filed', { defaultValue: 'Already filed' }),
    skipped: t('tendering.filing.state_skipped', { defaultValue: 'Not drafted yet' }),
  };

  return (
    <Card className="mt-3" data-testid="award-follow-up">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-content-primary">
            {t('tendering.rejections.title', { defaultValue: 'After the award' })}
          </h4>
          {q.data.issuing_entity && (
            <p className="text-xs text-content-secondary">
              {t('tendering.header.issued_in', {
                defaultValue: 'Letters and the contract are issued by {{company}}',
                company: q.data.issuing_entity.name,
              })}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={n === 0}
            onClick={() => setPreview((v) => !v)}
            data-testid="send-rejections"
          >
            <Send size={14} className="me-1" />
            {t('tendering.rejections.send', { defaultValue: 'Send rejections ({{n}})', n })}
          </Button>
          <Button size="sm" variant="secondary" disabled={fileM.isPending} onClick={() => fileM.mutate()}>
            <FolderInput size={14} className="me-1" />
            {t('tendering.filing.file', { defaultValue: 'File to documents' })}
          </Button>
        </div>
      </div>

      {(preview || n === 0) && q.data.rows.length > 0 && (
        <ul className="mt-3 divide-y divide-border-light text-sm" data-testid="rejections-preview">
          {q.data.rows.map((r) => (
            <li key={r.bid_id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="min-w-0 truncate">
                {r.company_name}
                {r.email && <span className="ms-2 text-xs text-content-tertiary">{r.email}</span>}
              </span>
              <Badge variant={STATE_VARIANT[r.state]}>{stateLabel[r.state]}</Badge>
            </li>
          ))}
        </ul>
      )}
      {preview && n > 0 && (
        <div className="mt-3 flex items-center justify-end gap-2">
          <span className="text-xs text-content-secondary">
            {t('tendering.rejections.confirm_hint', {
              defaultValue: 'Each firm gets its rejection letter as a PDF; a copy is filed in the project documents.',
            })}
          </span>
          <Button size="sm" disabled={sendM.isPending} onClick={() => sendM.mutate()} data-testid="confirm-rejections">
            {t('tendering.rejections.send_now', { defaultValue: 'Send now' })}
          </Button>
        </div>
      )}

      {filed && (
        <ul className="mt-3 text-sm" data-testid="filed-documents">
          {filed.map((d, i) => (
            <li key={`${d.kind}-${i}`} className="flex items-center justify-between gap-2 py-1">
              <span>{kindLabel[d.kind]}</span>
              <Badge variant={d.state === 'skipped' ? 'warning' : 'success'}>{filedLabel[d.state]}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
