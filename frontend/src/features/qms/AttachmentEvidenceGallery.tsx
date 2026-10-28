// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Evidence gallery for a QMS inspection (item 12).
 *
 * Lists the auditable document attachments linked to an inspection and lets
 * an authorised user link a new one by document id with an optional caption
 * and a SHA-256 integrity hash. A verified hash renders a green badge so the
 * reviewer can see at a glance that the evidence bytes are pinned.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Paperclip, ShieldCheck, Plus, Loader2 } from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  attachInspectionEvidence,
  listInspectionEvidence,
} from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function AttachmentEvidenceGallery({
  inspectionId,
  canEdit,
}: {
  inspectionId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [adding, setAdding] = useState(false);
  const [documentId, setDocumentId] = useState('');
  const [caption, setCaption] = useState('');
  const [hash, setHash] = useState('');

  const evidenceQ = useQuery({
    queryKey: ['qms', 'inspection-evidence', inspectionId],
    queryFn: () => listInspectionEvidence(inspectionId),
  });

  const attach = useMutation({
    mutationFn: () =>
      attachInspectionEvidence(inspectionId, {
        document_id: documentId.trim(),
        caption: caption.trim() || undefined,
        file_hash_sha256: hash.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'inspection-evidence', inspectionId] });
      qc.invalidateQueries({ queryKey: ['qms', 'inspections'] });
      addToast({
        type: 'success',
        title: t('qms.evidence_attached', { defaultValue: 'Evidence linked' }),
      });
      setAdding(false);
      setDocumentId('');
      setCaption('');
      setHash('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const rows = evidenceQ.data?.items ?? [];
  const hashValid = /^[0-9a-fA-F]{64}$/.test(hash.trim());

  return (
    <Card padding="sm">
      <div className="mb-2 flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          <Paperclip size={13} />
          {t('qms.evidence', { defaultValue: 'Evidence' })}
        </p>
        {canEdit && !adding && (
          <Button variant="ghost" size="sm" icon={<Plus size={13} />} onClick={() => setAdding(true)}>
            {t('qms.link_evidence', { defaultValue: 'Link evidence' })}
          </Button>
        )}
      </div>

      {evidenceQ.isLoading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-content-tertiary">
          <Loader2 size={14} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : rows.length === 0 ? (
        <p className="py-2 text-xs text-content-tertiary">
          {t('qms.evidence_empty', {
            defaultValue: 'No evidence linked yet. Attachments are hash-verifiable and audit-logged.',
          })}
        </p>
      ) : (
        <ul className="mb-2 space-y-1.5">
          {rows.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border-light bg-surface-secondary px-2.5 py-1.5 text-xs"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-content-primary">
                  {a.caption || a.document_id}
                </p>
                <p className="text-2xs text-content-tertiary">
                  {a.attached_at ? <DateDisplay value={a.attached_at} /> : '—'}
                </p>
              </div>
              {a.file_hash_sha256 ? (
                <span title={a.file_hash_sha256}>
                  <Badge variant="success">
                    <ShieldCheck size={11} className="mr-0.5 inline" />
                    {t('qms.hash_verified', { defaultValue: 'Hash verified' })}
                  </Badge>
                </span>
              ) : (
                <Badge variant="neutral">
                  {t('qms.no_hash', { defaultValue: 'No hash' })}
                </Badge>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <div className="space-y-2 border-t border-border-light pt-2">
          <input
            value={documentId}
            onChange={(e) => setDocumentId(e.target.value)}
            placeholder={t('qms.evidence_document_id', { defaultValue: 'Document ID (UUID)' })}
            className={inputCls}
            aria-label={t('qms.evidence_document_id', { defaultValue: 'Document ID (UUID)' })}
          />
          <input
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder={t('qms.evidence_caption', { defaultValue: 'Caption (optional)' })}
            className={inputCls}
            aria-label={t('qms.evidence_caption', { defaultValue: 'Caption (optional)' })}
          />
          <input
            value={hash}
            onChange={(e) => setHash(e.target.value)}
            placeholder={t('qms.evidence_hash', { defaultValue: 'SHA-256 hash (optional, 64 hex chars)' })}
            className={inputCls}
            aria-label={t('qms.evidence_hash', { defaultValue: 'SHA-256 hash (optional)' })}
          />
          {hash.trim() !== '' && !hashValid && (
            <p className="text-2xs text-semantic-warning">
              {t('qms.evidence_hash_invalid', {
                defaultValue: 'Hash must be exactly 64 hexadecimal characters.',
              })}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={attach.isPending}
              disabled={!documentId.trim() || (hash.trim() !== '' && !hashValid)}
              onClick={() => attach.mutate()}
            >
              {t('qms.attach', { defaultValue: 'Attach' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
