// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "E-invoice" card on an invoice: status, deadline badge, one primary
 * action, download, folded details. Renders nothing unless the tenant has an
 * e-invoicing market for the seller country and a document exists.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { AlertTriangle, Check, ChevronDown, ChevronRight, Clock, Download } from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchDocumentPayload,
  listDocuments,
  submitDocument,
  validateDocument,
} from './api';
import { statusVariant } from './documentStatus';
import { getDocumentLifecycle, type LifecycleAction } from './lifecycleApi';
import { deadlineVariant, formatDuration, primaryAction, primaryDeadline, STEPS, stepIndex } from './lifecycleView';
import { useEInvoiceMarkets } from './useEInvoiceMarkets';

// Steps reuse the status words; only the combined authority step has its own.
const STEP_LABEL_KEYS: Record<(typeof STEPS)[number], string> = {
  draft: 'einvoice.status.draft',
  validated: 'einvoice.status.validated',
  sent: 'einvoice.status.submitted',
  done: 'einvoice.step.done',
  accepted: 'einvoice.status.delivered',
};

export const MARKET_SETTINGS_PATH = '/settings?tab=market';

export function EInvoiceCard({
  projectId,
  invoiceId,
  sellerCountry,
}: {
  projectId: string;
  invoiceId: string;
  sellerCountry?: string | null;
}) {
  const { t, i18n } = useTranslation();
  const markets = useEInvoiceMarkets();
  const visible = markets.isVisibleFor(sellerCountry);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);

  const docs = useQuery({
    queryKey: ['einvoice-clearance', 'documents', projectId, invoiceId],
    queryFn: () => listDocuments({ projectId, invoiceId }),
    enabled: visible,
  });
  const documentId = docs.data?.[0]?.id;
  const lc = useQuery({
    queryKey: ['einvoice-clearance', 'lifecycle', documentId],
    queryFn: () => getDocumentLifecycle(documentId as string),
    enabled: !!documentId,
  });

  const act = useMutation({
    mutationFn: async (action: LifecycleAction) => {
      if (!documentId) return;
      if (action === 'validate') await validateDocument(documentId);
      else if (action === 'send') await submitDocument(documentId);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['einvoice-clearance'] });
    },
    onError: (err: unknown) =>
      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) }),
  });

  if (!visible || !documentId || !lc.data) return null;
  const view = lc.data;
  const platform = view.platform;
  const current = stepIndex(view.status);
  const deadline = primaryDeadline(view.deadlines);
  const primary = primaryAction(view.allowed_actions);
  const rejected = view.status === 'rejected';
  const errors = view.findings.filter((f) => f.severity === 'error');

  const download = async () => {
    const payload = await fetchDocumentPayload(documentId);
    const blob = new Blob([payload.text], { type: payload.mediaType || 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = payload.filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const actionLabel = (a: LifecycleAction): string => {
    switch (a) {
      case 'validate':
        return t('einvoice.action.validate', { defaultValue: 'Validate' });
      case 'send':
        return t('einvoice.action.send', { defaultValue: 'Send to {{platform}}', platform });
      case 'cancel':
        return t('einvoice.action.cancel', { defaultValue: 'Cancel' });
      case 'correct':
        return t('einvoice.action.correct', { defaultValue: 'Issue corrective invoice' });
      case 'check_status':
        return t('einvoice.action.checkStatus', { defaultValue: 'Check status' });
      default:
        return t('einvoice.action.download', { defaultValue: 'Download file' });
    }
  };

  const deadlineText = deadline
    ? deadline.state === 'overdue'
      ? t('einvoice.deadline.overdue', {
          defaultValue: 'Deadline passed {{duration}} ago',
          duration: formatDuration(deadline.seconds_left, i18n.language),
        })
      : t('einvoice.deadline.reportWithin', {
          defaultValue: 'Report within {{duration}}',
          duration: formatDuration(deadline.seconds_left, i18n.language),
        })
    : '';

  return (
    <Card className="p-4 space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('einvoice.card.title', { defaultValue: 'E-invoice' })} · {platform}
        </h3>
        <Badge variant={statusVariant(view.status)}>
          {t(`einvoice.status.${view.status}`, { defaultValue: view.status })}
        </Badge>
        {deadline && (
          <Badge variant={deadlineVariant(deadline.state)}>
            <span aria-label={deadlineText} className="inline-flex items-center gap-1">
              <Clock size={12} aria-hidden="true" />
              {deadlineText}
            </span>
          </Badge>
        )}
      </div>

      <ol className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
        {STEPS.map((step, i) => (
          <li
            key={step}
            aria-current={i === current ? 'step' : undefined}
            className={i === current ? 'font-semibold text-content-primary' : undefined}
          >
            {i < current && <Check size={12} className="inline me-1" aria-hidden="true" />}
            {t(STEP_LABEL_KEYS[step], { defaultValue: step })}
            {i < STEPS.length - 1 && <ChevronRight size={12} className="inline ms-1 rtl:rotate-180" aria-hidden="true" />}
          </li>
        ))}
      </ol>

      {rejected && errors.length > 0 && (
        <div role="alert" className="rounded-lg border border-semantic-error/40 bg-semantic-error-bg p-3 text-sm">
          <AlertTriangle size={14} className="inline me-1" aria-hidden="true" />
          {errors.map((f) => (
            <div key={f.rule_id}>
              <span dir="ltr" className="font-mono">{f.rule_id}</span> {f.message}
            </div>
          ))}
          <div className="mt-1">{t('einvoice.rejected.fix', { defaultValue: 'Fix and revalidate' })}</div>
        </div>
      )}

      {view.mode === 'export' && (
        <p className="text-xs text-content-secondary">
          {t('einvoice.mode.exportBanner', {
            defaultValue: 'Export only: download the file and upload it to {{platform}} yourself.',
            platform,
          })}{' '}
          <Link to={MARKET_SETTINGS_PATH} className="underline">
            {t('einvoice.setup.linkFromFinance', { defaultValue: 'Set up in Market & standards' })}
          </Link>
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {primary && primary !== 'cancel' && primary !== 'correct' && (
          <Button size="sm" onClick={() => act.mutate(primary)} disabled={act.isPending}>
            {actionLabel(primary)}
          </Button>
        )}
        {primary && (primary === 'cancel' || primary === 'correct') && (
          <Button size="sm" variant="secondary" disabled>
            {actionLabel(primary)}
          </Button>
        )}
        <Button size="sm" variant="secondary" onClick={() => void download()}>
          <Download size={14} className="me-1" aria-hidden="true" />
          {actionLabel('download')}
        </Button>
      </div>

      <button
        type="button"
        className="flex items-center gap-1 text-xs text-content-secondary"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} className="rtl:rotate-180" />}
        {t('einvoice.card.details', { defaultValue: 'Details (hash, QR, identifier, findings)' })}
      </button>
      {open && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt>{view.identifier_label}</dt>
          <dd dir="ltr" className="font-mono break-all">{view.authority_identifier || '-'}</dd>
          {view.findings.map((f) => (
            <div key={f.rule_id + f.message} className="contents">
              <dt dir="ltr" className="font-mono">{f.rule_id}</dt>
              <dd>{f.message}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
