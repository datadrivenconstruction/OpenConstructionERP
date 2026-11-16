// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Document PDF" button: the customer-facing document of one record (invoice,
 * change order) in the firm's published wording. Missing mandatory data
 * (EN 16931, country rules) is named in a toast instead of a broken PDF.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSignature } from 'lucide-react';
import { API_BASE, fetchWithAuth, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import type { DocIssue } from './api';

export function IssueDocumentButton({
  kind,
  recordId,
  fallbackName,
  testId,
}: {
  kind: string;
  recordId: string;
  fallbackName: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const label = t('settings.document_templates.issue_pdf', { defaultValue: 'Document PDF' });

  const run = async () => {
    setBusy(true);
    try {
      const r = await fetchWithAuth(
        `${API_BASE}/v1/doc-templates/${encodeURIComponent(kind)}/records/${encodeURIComponent(recordId)}/pdf`,
      );
      if (r.status === 422) {
        const body = (await r.json().catch(() => ({}))) as { detail?: { issues?: DocIssue[] } };
        const issues = body.detail?.issues ?? [];
        addToast({
          type: 'error',
          title: t('settings.document_templates.issue_blocked', { defaultValue: 'Required data is missing' }),
          message: issues
            .map((i) => t(`validation.${i.rule_id}`, { defaultValue: i.rule_id, ...i.params }))
            .join('\n'),
        });
        return;
      }
      if (!r.ok) throw new Error(`${r.status}`);
      triggerDownload(await r.blob(), `${fallbackName}.pdf`);
    } catch {
      addToast({
        type: 'error',
        title: t('settings.document_templates.issue_failed', { defaultValue: 'The document could not be created' }),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={() => void run()}
      disabled={busy}
      title={label}
      aria-label={label}
      data-testid={testId}
      className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-oe-blue disabled:opacity-50"
    >
      <FileSignature size={14} />
    </button>
  );
}
