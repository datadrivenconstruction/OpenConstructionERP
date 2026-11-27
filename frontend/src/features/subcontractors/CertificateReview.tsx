/**
 * One certificate on a subcontractor's record: type, expiry, review state, and
 * the actions a reviewer needs (open the file, mark it verified). An upload
 * alone leaves it awaiting review; the server enforces who may verify.
 */
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Badge, Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  downloadCertificate,
  unverifyCertificate,
  verifyCertificate,
  type Certificate,
} from './api';

const VARIANT: Record<string, 'success' | 'warning' | 'error' | 'neutral'> = {
  verified: 'success',
  awaiting_review: 'warning',
  expired: 'error',
  revoked: 'error',
};

const STATE_LABEL: Record<string, string> = {
  awaiting_review: 'Awaiting review',
  verified: 'Verified',
  expired: 'Expired',
  revoked: 'Revoked',
};

export function CertificateReview({ cert, label }: { cert: Certificate; label: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = useAuthStore((s) => s.userRole);
  const canVerify = role === 'admin' || role === 'manager';
  const state = cert.review_status ?? (cert.status === 'valid' ? 'awaiting_review' : cert.status);
  const hasFile = !!cert.metadata?.source_document_id;

  const toggle = useMutation({
    mutationFn: () => (state === 'verified' ? unverifyCertificate(cert.id) : verifyCertificate(cert.id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['subcontractors', 'certificates'] }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const open = () =>
    downloadCertificate(cert).catch((err) => addToast({ type: 'error', title: getErrorMessage(err) }));

  return (
    <div className="flex items-center gap-2" data-testid="certificate-row">
      <Badge variant={VARIANT[state] ?? 'neutral'}>
        {label}
        {cert.valid_until ? ` · ${cert.valid_until}` : ''}
      </Badge>
      <span className="text-xs text-content-secondary" data-testid="certificate-review-status">
        {t(`subcontractors.cert_review.${state}`, { defaultValue: STATE_LABEL[state] ?? state })}
      </span>
      {hasFile && (
        <Button variant="ghost" size="sm" onClick={open}>
          {t('subcontractors.cert_review.open', { defaultValue: 'Open file' })}
        </Button>
      )}
      {canVerify && (state === 'awaiting_review' || state === 'verified') && (
        <Button variant="secondary" size="sm" loading={toggle.isPending} onClick={() => toggle.mutate()}>
          {state === 'verified'
            ? t('subcontractors.cert_review.unverify', { defaultValue: 'Withdraw verification' })
            : t('subcontractors.cert_review.verify', { defaultValue: 'Mark as verified' })}
        </Button>
      )}
    </div>
  );
}
